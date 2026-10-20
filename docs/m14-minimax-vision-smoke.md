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
| `AI_AGENT_MAX_COST_CNY` | 普通按量不超过 `0.05`；M Plan 必须不设置 |
| `AI_AGENT_MAX_MODEL_RETRIES` | `0` |

`-MiniMaxBillingMode` 必须显式选择 `Payg` 或 `MPlan`，没有默认值。普通按量模式要求当前 Token
单价和 `AI_AGENT_MAX_COST_CNY`；M Plan 模式拒绝非零 Token 单价和现金上限，避免把订阅额度伪装成
按量现金支出。

用户已确认当前 Key 为 M Plan。官方说明订阅 Key 只消耗 M Plan 额度和积分包，不会自动扣按量账户
余额；套餐余量可由网页、`mmx quota` 或独立 `token_plan/remains` API 查询。本 smoke 为保持恰好
一次模型请求和最小 Key 暴露，不额外调用余量 API，只记录 Chat Completions 响应中的 Token usage，
输出 `estimated_cost_cny=null`、`cash_cost_status=not_applicable`、`quota_remaining=not_queried`。

普通按量兼容路径仍保留：当前 `MiniMax-M3` 标准层、输入不超过 512k 时 input `¥2.10`、output
`¥8.40` / 1M Token；2000 input + 256 output 的声明上界为 `¥0.00635040`。该费率不用于本次
M Plan 请求。

## 唯一执行入口

取得新授权并确认 Key 类型后，才允许在只影响该子进程的环境中设置模型和低预算，并清除
`ALL_PROXY/all_proxy`、保留 HTTP/HTTPS proxy：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-online.ps1 `
  -Authorized `
  -Suite M14 `
  -VisionProvider MiniMax `
  -VisionModel MiniMax-M3 `
  -MiniMaxBillingMode MPlan
```

未授权时脚本在启动 Python、读取 Key 或访问 Provider 前返回 64。配置/代理问题返回 65；Provider
fallback、严格 JSON/usage/信任边界或成本验收失败返回 1。stdout 不包含 summary、OCR、
uncertainties、raw payload、异常或 Key。

## 当前证据

离线测试已覆盖真实 OpenAI SDK + MockTransport 的 `/v1/chat/completions` 形状、Base64 图片、
`thinking=disabled`、无 tools、usage 归一、严格 JSON、安全回退、代理门、人民币预算和内容无关
摘要。它们是 E2/E3，不是 MiniMax 在线 E4；截至 `V-20261020-004` 没有读取真实 Key、发送图片或
产生新的按量现金费用。

M Plan 离线门进一步覆盖：显式 billing mode、拒绝现金费率/上限、只保留响应 usage、现金成本
`not_applicable`、余量 `not_queried`，以及 PowerShell 缺 billing mode 时在 Python 前以 65 拒绝。

## 2026-10-20 单次 M Plan 在线结果

用户明确授权恰好一次 `MiniMax-M3` M Plan 视觉调用。预检只确认用户级 Key 存在且格式有效；唯一
临时子进程移除了 SOCKS5 `ALL_PROXY/all_proxy`，保留 HTTP/HTTPS proxy，并执行一次、零重试。

请求成功返回：

- fixture：`prompt-injection-png-v1`，632×200，1752 bytes；
- 结构化真实 observation：`offline=false`、`untrusted_visual_data`、visible text 25 bytes；
- 权限边界：`can_authorize_actions=false`、`tool_surface=none`；
- usage：input 479、output 43、total 522 Token；
- 时延：4643.964 ms；
- M Plan：`estimated_cost_cny=null`、现金成本不适用、套餐余量未查询。

stdout 没有视觉原文、Key、代理地址或 raw Provider payload。该次授权已经消耗，没有重试，也没有
调用 `token_plan/remains`。完整证据见 `V-20261020-005`；M14-T4 因此达到 `verified`。

官方依据：

- [MiniMax 国内 OpenAI SDK 与多模态输入](https://platform.minimax.cn/docs/api-reference/text-openai-api)
- [MiniMax 国内 Chat Completions](https://platform.minimax.cn/docs/api-reference/text-chat-openai)
- [MiniMax 国内定价](https://platform.minimax.cn/docs/pricing/overview)
- [MiniMax M Plan 与用量说明](https://platform.minimax.cn/subscribe/coding-plan)
