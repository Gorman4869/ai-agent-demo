# M14-T4 MiniMax 国内视觉冒烟

这是现有 M14-T4 的备用 Provider 纵切。它复用固定无个人数据 PNG、PNG guard、统一
`StructuredVisionObservation` 和提示注入安全边界，但使用 MiniMax 国内 OpenAI-compatible Chat
Completions，不改变默认离线运行时。

## 固定接口与模型

- 国内 Base URL：`https://api.minimax.cn/v1`，代码固定，不从环境读取。
- 模型：`MiniMax-M3`，`MINIMAX_MODEL` 和 `-VisionModel` 必须完全一致。
- 图片：仓库内存生成的 `prompt-injection-png-v1`，Base64 PNG，`detail=low`。
- 生成：`thinking=disabled`、`temperature=0`、`max_completion_tokens<=256`、一次请求、零重试。
- 工具：无 tools、无副作用、无用户 prompt、无远程图片 URL。

选择 `MiniMax-M3` 而不是 `MiniMax-M3.1-Flash`，是因为官方文档允许前者关闭 thinking，而后者
强制 thinking。M14-T4 需要小而可解释的 output Token 上限，不能让隐藏思考挤占结构化结果。

MiniMax Chat Completions 文档未列出 `response_format/json_schema`。adapter 因此只用 server-owned
prompt 要求一个 JSON 对象，再由本地 Pydantic 严格解析。任何 Markdown fence、额外文字、字段
漂移、截断或 usage 异常都 fail closed；这不是 Provider 原生 structured-output 保证。

## 授权与环境门

“Key 已配置”不等于授权调用。只有用户对下一次请求给出新的明确单次授权后，CLI 才会读取以下
环境：

| 配置 | 要求 |
| --- | --- |
| `AI_AGENT_ONLINE_ENABLED` | `true` |
| `MINIMAX_API_KEY` | 仅本机环境变量；不输出、不入库 |
| `MINIMAX_MODEL` | `MiniMax-M3` |
| `AI_AGENT_MAX_MODEL_CALLS` | `1` |
| `AI_AGENT_RUN_TIMEOUT_MS` | 不超过 `30000` |
| `AI_AGENT_MODEL_TIMEOUT_MS` | 不超过 `20000` |
| `AI_AGENT_MAX_INPUT_TOKENS` | 不超过 `2000` |
| `AI_AGENT_MAX_OUTPUT_TOKENS` | 不超过 `256` |
| `AI_AGENT_MAX_COST_CNY` | 不超过 `0.05` |
| `AI_AGENT_MAX_MODEL_RETRIES` | `0` |

当前官方普通按量价格为 `MiniMax-M3` 标准层、输入不超过 512k 时 input `¥2.10`、output `¥8.40`
/ 1M Token。按本地最大 2000 input + 256 output 计算，声明上界为 `¥0.00635040`。实际 usage 只能
请求后获得；本地上限不是 Provider 侧逐 Token 硬停止。

Key 类型必须在执行前确认：普通按量 API Key 才使用上述现金费率；M Plan/Token Plan 订阅 Key 的
消耗属于套餐额度，不能把同一估算写成实际现金账单。

## 唯一执行入口

取得新授权并确认 Key 类型后，才允许在只影响该子进程的环境中设置模型和低预算，并清除
`ALL_PROXY/all_proxy`、保留 HTTP/HTTPS proxy：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-online.ps1 `
  -Authorized `
  -Suite M14 `
  -VisionProvider MiniMax `
  -VisionModel MiniMax-M3 `
  -InputPricePerMillionCny 2.10 `
  -OutputPricePerMillionCny 8.40
```

未授权时脚本在启动 Python、读取 Key 或访问 Provider 前返回 64。配置/代理问题返回 65；Provider
fallback、严格 JSON/usage/信任边界或成本验收失败返回 1。stdout 不包含 summary、OCR、
uncertainties、raw payload、异常或 Key。

## 当前证据

离线测试已覆盖真实 OpenAI SDK + MockTransport 的 `/v1/chat/completions` 形状、Base64 图片、
`thinking=disabled`、无 tools、usage 归一、严格 JSON、安全回退、代理门、人民币预算和内容无关
摘要。它们是 E2/E3，不是 MiniMax 在线 E4；当前没有读取真实 Key、发送图片或产生费用。

官方依据：

- [MiniMax 国内 OpenAI SDK 与多模态输入](https://platform.minimax.cn/docs/api-reference/text-openai-api)
- [MiniMax 国内 Chat Completions](https://platform.minimax.cn/docs/api-reference/text-chat-openai)
- [MiniMax 国内定价](https://platform.minimax.cn/docs/pricing/overview)
