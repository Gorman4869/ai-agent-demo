# ADR-0043：MiniMax 国内视觉适配与独立费用门

- 状态：accepted
- 日期：2026-10-20
- 任务：`M14-T4`
- 依赖：`ADR-0042`
- SDK 基线：复用既有 `openai==2.45.0`

## 背景

M14-T4 首次 OpenAI 尝试在本机 SDK client 构造阶段被 SOCKS 环境阻断。用户随后选择把国内
MiniMax 平台作为备用 Provider，并已在本机环境配置 Key。MiniMax 官方国内文档确认
`MiniMax-M3` 与 `MiniMax-M3.1-Flash` 可通过 OpenAI-compatible Chat Completions 输入图片，国内
Base URL 为 `https://api.minimax.cn/v1`。

现有 OpenAI 视觉 adapter 使用 Responses API `responses.parse` 和 Provider 原生 structured
output。MiniMax Chat Completions 文档没有列出 `response_format/json_schema`，不能把当前 adapter
仅换 Key/Base URL 后冒充已兼容。

## 决策

### 1. 使用独立 MiniMax adapter，不改变默认模型运行时

新增 `MiniMaxVisionModel`，只实现共享 `VisionModel` 协议并复用 `MultimodalVisionAgent` 的 PNG
校验、timeout、结构化观察、不可信数据和失败回退。默认 `Settings`、主 Run、OpenAI Responses
adapter 与离线路径不迁移到 MiniMax；本次只扩展 M14-T4 opt-in smoke。

### 2. 国内端点与模型由代码固定

客户端固定 `https://api.minimax.cn/v1`，不接受环境或模型输出提供的任意 Base URL。模型固定
`MiniMax-M3`；它支持 `thinking={type: disabled}`，因此单次视觉冒烟可在 256 output Token 上限内
避免隐藏思考 Token。`MiniMax-M3.1-Flash` 强制思考，不进入本次低预算门。

请求固定 Base64 PNG、`detail=low`、`temperature=0`、`max_completion_tokens`、零 SDK retry，且不
提供 tools、远程图片 URL、用户 prompt 或 side-effect callback。

### 3. Prompt 约束加本地严格解析，不宣称 Provider structured output

server-owned prompt 要求只返回包含 `summary`、`visual_text`、`uncertainties` 的 JSON 对象。本地
使用 Pydantic `extra=forbid` 严格解析；Markdown fence、额外文字、字段缺失、截断、非 stop、无效
usage 均映射为 `provider_invalid_response` 并回退 PNG metadata。

该策略是 fail-closed 的结构化观察适配，不是 MiniMax 原生 JSON schema 保证。真实模型是否稳定
遵守格式必须由一次授权 E4 验证，未验证前由 `KI-033` 跟踪。

### 4. Key、授权和人民币费用独立

CLI 只在显式 `--authorized` 后读取 `MINIMAX_API_KEY`，并要求 `AI_AGENT_ONLINE_ENABLED=true`、
`MINIMAX_MODEL=MiniMax-M3` 与命令模型完全一致。Key 使用 `SecretStr`，不进入 repr、摘要、错误、
文档或 Git。

MiniMax 国内标准费率以人民币计价，因此新增 `AI_AGENT_MAX_COST_CNY` 与 CNY rate 参数；不得复用
OpenAI 的 USD 字段。单次上限仍为 2000 input、256 output、一次调用、零重试；费用只在返回 usage
后按操作者提供费率估算，不是账单或 Provider 侧硬停止。

### 5. 环境与证据边界不变

SOCKS 缺依赖时继续在 SDK 构造前 fail closed。离线测试通过真实 OpenAI SDK 与
`httpx.MockTransport` 验证 `/v1/chat/completions` 请求形状，但不读取真实 Key、不访问 MiniMax、
不产生费用，证据最高为 E2/E3。

## 后果

- 不新增依赖，不改变默认离线、主 Runtime、HTTP API、数据库或前端。
- MiniMax 输出继续是 `untrusted_visual_data`，固定 `can_authorize_actions=false`。
- 真实 E4 前还需确认 Key 是普通按量付费还是 M Plan/Token Plan 订阅 Key；前者可用当前官方 CNY
  Token 费率估算，后者只能记录套餐额度/usage，不得伪装为同一现金账单。
- 任何真实 MiniMax 请求都需要新的单次用户授权；“Key 已配置”只解除环境准备条件，不是调用授权。

## 未采用方案

- 把 MiniMax Key 填入 `OPENAI_API_KEY` 并复用 `responses.parse`：接口形状和 structured-output 证据
  不一致，也会混淆 Provider 审计。
- 允许任意 `OPENAI_BASE_URL`：会把 Key 的发送目标变成可配置外传面。
- 选择强制 thinking 的 `MiniMax-M3.1-Flash`：低 output Token 冒烟可能只产生思考或空 content。
- 宽松提取 Markdown 中的 JSON：会隐藏 Provider 合同漂移，削弱 fail-closed 验收。

## 验证依据

- `backend/app/advanced/multimodal.py`
- `backend/app/minimax_vision_smoke.py`
- `backend/tests/test_minimax_vision_smoke.py`
- `docs/m14-minimax-vision-smoke.md`
- [MiniMax 国内 OpenAI SDK](https://platform.minimax.cn/docs/api-reference/text-openai-api)
- [MiniMax 国内定价](https://platform.minimax.cn/docs/pricing/overview)
- `V-20261020-003`
