# ADR-0042：视觉输入与不可信结构化观察

- 状态：accepted
- 日期：2026-09-02
- 任务：`M14-T3`
- 依赖：`ADR-0002`、`ADR-0005`、`ADR-0008`
- SDK 基线：`openai==2.45.0`（由既有 `openai-agents==0.18.2` 依赖提供）

## 背景

现有 `OfflineMultimodalAgent` 只验证 PNG 字节、签名、IHDR CRC、宽高和像素预算，并把调用方提供的
文字标为不可信。它没有把真实图片送入视觉模型，也没有统一结构化模型输出、timeout、usage 和失败
回退。M14-T3 需要补真实 SDK 图像输入 seam，但默认课程仍必须离线、确定性、零费用，并把真实调用
留给 M14-T4 的单次授权冒烟。

OpenAI 的 Images and vision 指南允许 Responses API 用 `input_image` 传 URL、file ID 或 Base64 data
URL，并可选择图像 `detail`。本任务已有服务端验证后的 PNG bytes，因此不引入远程 URL 抓取或文件
上传生命周期，直接在单次请求内发送 `data:image/png;base64,...`。

## 决策

### 1. 统一配置与单次授权必须同时成立

`create_multimodal_vision_agent()` 复用现有 `Settings` 的 provider、online switch、API Key、model、
timeout 和 output token budget，但再要求调用点显式传入 `online_authorized=True`。两道门缺任意一道都
选择确定性的 `OfflineVisionModel`，且不创建 client。配置 Key 本身、单独的 online switch 或单独的
函数参数都不能触发网络。

M14-T4 的独立命令负责取得用户本次授权后再传入该标记；M14-T3 的默认路径不读取环境 Key，也不
执行 Provider。

### 2. 图片只作为已验证的输入数据

协调层只接受 `image/png`，并先复用 `OfflineMultimodalAgent` 的字节、签名、IHDR CRC、尺寸和像素
预算。校验通过后才构造 `VisionRequest`；图片 bytes 使用 `repr=False`。错误 MIME、损坏 IHDR 和
超限输入在 client factory 进入前拒绝。

真实 adapter 只接受这份 bytes，使用固定的 server-owned instructions/prompt、Base64 data URL、
`detail=low`、`store=false` 和 server-owned output token limit。不接收图片 URL、file ID、用户 prompt、
工具列表或任意 side-effect callback。

### 3. 视觉输出整体是不可信观察

Provider 必须返回 `summary`、`visual_text` 和最多 8 个 `uncertainties` 的结构化对象。应用重新验证
类型、非空字段、可见文字字节数和整体 canonical JSON 字节数，再转成
`StructuredVisionObservation`。

摘要、OCR/可见文字和 uncertainties 都属于 `untrusted_visual_data`，并固定
`can_authorize_actions=False`。文字原文不进入 dataclass repr 或事件；事件只记录内容摘要、字节数、
provider/model、offline 标记和稳定失败码。图片里即使出现“忽略系统规则”“批准转账”等文字，也
只能作为数据返回，不能改变 Settings、角色、审批或工具集合。

### 4. 模型调用有界且无隐藏重试

每次真实分析创建显式 `AsyncOpenAI` client，传入 server-owned timeout 和 `max_retries=0`，结束时有界
关闭；不使用 SDK 全局 Key/模型。协调层再用 `asyncio.timeout` 形成单次墙钟边界。输出同时受 provider
Token 上限、可见文字字节上限和整体观察字节上限约束。

timeout、限流、鉴权、请求拒绝、连接故障和无效结构映射到既有稳定 `RunFailure`。失败结果仍保留已
验证的 PNG metadata，但不伪造视觉结论或 usage；取消继续向上传播。当前不自动重试视觉请求，避免
隐藏费用和重复上传图片。

### 5. 离线证据必须走真实 SDK 形状

普通单元测试使用窄 client Protocol fixture；至少一条 E2 纵切使用真实 `openai==2.45.0` 的
`responses.parse` 和 `httpx.MockTransport`，验证 `/v1/responses`、结构化解析、Base64 image content、
无 tools、`store=false` 和 usage 归一。MockTransport 证据仍是离线 E2/E3，不是 Provider E4。

## 后果

- 默认和未单次授权路径继续零网络，并返回明确“只完成 PNG 校验、未做视觉推理”的结构化观察。
- OpenAI adapter 与离线 model 共享 `VisionModelOutput`/`StructuredVisionObservation`，上层不解析 SDK
  payload，也不会因为 provider 变化获得额外权限。
- M14-T4 可以复用同一 adapter 做一次低预算在线冒烟和 usage/费用记录，不需要改写领域合同。
- 当前只接受 PNG，并继续使用既有签名/IHDR 校验；没有完整 decode、安全重编码、metadata 剥离、
  恶意图片扫描、内容审核或生产上传存储生命周期。
- `detail=low` 是本任务的 server-owned 成本边界，不证明适合细粒度 OCR；真实质量由 M14-T4/T5 评估。

## 未采用方案

- 只看 `AI_AGENT_ONLINE_ENABLED` 就调用 Provider：不能满足 M14-T4 的用户单次授权边界。
- 让调用方传远程图片 URL：会引入 SSRF、redirect、认证、下载大小和 transport 一致性新风险。
- 把图片文字拼回 system prompt 或工具参数：会把不可信数据升级为控制面。
- 给视觉模型注册工具：M14-T3 只生成观察，工具/审批属于后续综合 Run，必须由应用 policy 管理。
- SDK 默认重试或无界输出：会隐藏重复上传、费用和延迟，也让失败语义不稳定。
- 把 MockTransport 成功写成在线视觉成功：没有真实模型、真实图片上传、usage/费用和质量证据。

## 验证依据

- `backend/app/advanced/multimodal.py`
- `backend/tests/test_multimodal_agent.py`
- `docs/m14-vision-input.md`
- [OpenAI Images and vision](https://developers.openai.com/api/docs/guides/images-vision)
- `V-20260902-001`
