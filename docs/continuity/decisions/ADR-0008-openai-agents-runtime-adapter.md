# ADR-0008：OpenAI Agents Runtime 适配与离线证据边界

- 状态：accepted
- 日期：2026-07-16
- 任务：`M8-T4`
- 依赖：`ADR-0002`、`ADR-0005`、`ADR-0007`
- 本地依赖基线：`openai-agents==0.18.2`

## 背景

M8-T3 已建立 SDK 无关的 async `AgentRuntime` 与持久 Coordinator。现有 `sdk_runtime.py` 只构造一个 `Agent`，没有调用 `Runner.run_streamed()`，也没有规定工具、结构化输出、usage、取消和 Provider 错误如何映射。

本地 0.18.2 的 `Runner.run_streamed()` 是同步流工厂，真正异步的是 `RunResultStreaming.stream_events()`；`cancel("immediate")` 是同步控制。SDK `RunConfig` 的缺省值会启用 tracing，并默认允许敏感 Trace 内容，因此不能直接使用缺省配置。

默认课程测试必须保持零网络、零费用，同时又要证明适配器使用真实 SDK 数据形状。fake Runner 是离线契约证据，不是在线模型成功证据。

## 决策

### 1. Runner 可替换，应用边界不感知 SDK

`OpenAIAgentsRuntime` 实现现有 `AgentRuntime`，只返回 `RuntimeResult` 并发送 `RuntimeEvent`。Runner 和 stream 通过窄 Protocol 注入，离线测试使用 fake；生产适配调用锁定版本的 `Runner.run_streamed()`。Coordinator 不解析 SDK 类型，也不增加 Provider 业务分支。

### 2. 显式 client/model，不使用进程全局 Key

完整在线配置才允许 Container 注册 SDK Runtime。每次 Run 从服务端 Settings 建立显式 `AsyncOpenAI` client 和 `OpenAIResponsesModel`，模型名与 timeout 全部显式传入；不调用全局 Key setter，不依赖宿主环境自动选择模型。client 自身 `max_retries=0`，唯一重试层由 SDK `ModelRetrySettings` 消费应用预算，避免两层隐藏重试叠加。client 生命周期由该 Run 的 async context 管理，Container 构造本身不联网。

### 3. 强制关闭 SDK Trace

每次 Runner 调用都创建受控 `RunConfig`：

```text
tracing_disabled = true
trace_include_sensitive_data = false
model = explicit model object
model_settings.include_usage = true
model_settings.max_tokens = server output budget
model_settings.retry = bounded SDK retry policy
```

即使未来 SDK 默认值或环境变量变化，这两个 Trace 字段也不得省略。API Key、prompt、工具参数、结果和 Provider payload 不进入普通日志。

### 4. 每 Run 工具上下文隔离

现有 `ToolRegistry` 仍是共同工具领域契约。SDK `FunctionTool` 只负责协议转换：

1. 按当前 Run 的可信 `ToolExecutionContext` 选择可见定义。
2. JSON 参数只作为模型输入，不能提供 principal、roles 或审批状态。
3. 使用 SDK tool call ID 调用 `ToolRegistry.execute()`，继续执行角色、审批和 Schema 校验。
4. 返回给模型的工具结果使用有界 JSON；持久事件只保留 call ID、工具名、成功状态和稳定错误码。
5. 两个并发 Run 不共享角色、审批或工具结果跟踪器。

同步 handler 在 worker thread 执行；取消无法撤销已经开始的外部副作用。后续超时、隔离与副作用恢复由生产工程任务继续处理。

### 5. 事件采用显式白名单

只允许以下 SDK 信息进入 Runtime：

| SDK 事实 | Runtime 事件 | 允许字段 |
| --- | --- | --- |
| `response.output_text.delta` | `model.output.delta` | `delta`；结构化模式增加正整数 `segment` |
| `RunItemStreamEvent(tool_called)` | `tool.started` | `id`、`name` |
| `RunItemStreamEvent(tool_output)` 成功 | `tool.completed` | `id`、`name`、`ok` |
| `RunItemStreamEvent(tool_output)` 失败 | `tool.failed` | `id`、`name`、`ok`、`error_code` |
| 完成后的 SDK aggregate usage | `model.usage` | scope、provider、model、requests、Token、unknown cost |

其他正常 raw response 事件显式忽略；未知顶层包装、缺失关键字段或不一致终态属于稳定 contract failure。不得把 raw response、SDK item、response ID、工具 arguments/output 或异常文本放进 EventStore。

文本 delta 是模型输出内容的一部分，可以持久化供未来 SSE 重放，但必须限制单块和累计 UTF-8 字节，并依靠 `repr=False` 与日志白名单避免普通日志泄漏。结构化模式用递增 `segment` 标识每个 JSON 对象；消费者只能在同一 segment 内追加，最终 Run answer 对应最后 segment。

### 6. 结构化输出只在 Runtime 内归一化

学习 Agent 使用最小 Pydantic 输出模型。Runtime 接受字符串或可规范 JSON 化的结构化输出；课程输出模型的 `answer` 字段归一为 `RuntimeResult.answer`。空输出、不可序列化对象和不一致的 `is_complete` 使用稳定 contract failure。SDK/Pydantic 对象不进入 Store。

### 7. Usage 与预算不夸大

0.18.2 的 `result.context_wrapper.usage` 是一次 Run 的聚合，`request_usage_entries` 有每请求 Token，但没有每次 duration 与可信费用。M8-T4 因此只写 `scope=run` 的聚合 usage 事件；未知费用必须是 `null` 和 `cost_source=unknown`，不能写零，也不能构造要求单次 duration 的 `UsageRecord`。

SDK turns、输出 Token、client timeout/retry 在调用前受限；完成后再核对 aggregate requests/input/output Token。输入 Token 和费用无法仅凭当前 SDK 在每次调用前可靠硬关闭，持久 usage ledger、定价与完整预算中止留 M13，并进入 known issues。

### 8. 取消、错误和 Store 失败分层

- 调用前已取消时不创建 Runner。
- 流中取消调用一次 immediate cancel，停止新 emit，并在有限宽限内继续 drain；外层 task 取消完成清理后重新抛出 `CancelledError`。
- 限流、连接、timeout、鉴权、请求错误、MaxTurns、模型行为和 guardrail 映射为稳定安全失败；不使用 `str(exception)` 作为公开内容。
- Provider/SDK 流迭代错误由 Runtime 归一；Event sink/Store 错误不伪装成 Provider 错误，继续向 Coordinator 传播并遵守 `KI-016`。
- Runtime 不自动重跑整个工具型 Run，避免重复副作用。

### 9. 证据等级

离线 fake fixture、真实 SDK dataclass、socket 守卫和完整回归通过时，`M8-T4` 最高为 `code_complete`。只有用户再次给出单次授权并由 M8-T6 完成真实模型、真实工具、真实 usage 与费用记录后，才可把在线部分标为 `verified`。

## 后果

- 默认 `manual + mock` 路径继续不导入在线配置、不发网络请求。
- SDK 版本变化只影响适配器和 fixture，不改变 Coordinator、Store 或旧 API。
- 工具权限继续由应用控制，不由模型或 SDK context 绕过。
- 输出 delta 会成为持久内容，后续 API/日志必须继续把它当敏感业务数据。
- aggregate usage 可用于离线映射和事后预算判断，但不等于生产 usage ledger 或费用硬门禁。
- 在线调用、真实 Provider 行为、资源清理和费用仍未验证。

## 实现校准（2026-07-16）

实现与独立复审对设计作出以下收紧；这些条目覆盖本 ADR 前文中较宽泛的描述：

1. 使用结构化输出时，SDK 的 `response.output_text.delta` 承载 JSON framing，而不是可直接展示的答案。Runtime 采用增量 JSON 解码，只把 `answer` 字符串与安全递增 `segment` 作为 `model.output.delta` 发出；同一对象跨 chunk 保持编号，终态只核对最后 segment 与 typed final output 一致。JSON 括号、键名和 Provider raw 内容均不得持久化。
2. M8-T4 不执行需要审批、高风险或有副作用的工具。每 Run 工具快照仍经过身份、角色和 Schema 校验，但审批中断、恢复、幂等副作用和持久审批证据属于 M10；在这些能力完成前必须 fail closed。
3. SDK 的 `max_turns` 使用 `min(max_steps, max_model_calls)`，并把超限映射到更紧的应用预算。但 SDK retry 会计入 aggregate requests，因此真实请求数仍可能先超出近似上限，再在 Run 结束后被发现；输入 Token 同样只能事后核对，费用没有可信定价时不能执行硬门禁。
4. client timeout 是 HTTP 各阶段和流读取 timeout，不是整个模型执行的硬墙钟。Coordinator 的 `run_timeout_ms` 才是当前 Run 级期限；已开始的 Provider 请求和 worker thread 仍只能有界清理，不能宣称被撤销。
5. 流取消必须在原 `stream_events()` 迭代器上执行 immediate cancel 并继续 drain，停止任何新事件。若外层 task 取消与 Event sink/Store 失败竞态，Store 失败优先向 Coordinator 传播，避免把持久化故障伪装成普通取消。
6. 显式 client 每 Run 创建并在有界清理内关闭。同步低风险工具通过 worker thread 运行；即使 Run 已取消，阻塞线程也可能继续占用 executor，该风险由 `KI-017` 跟踪。

本次离线实现最高状态为 `code_complete`。Provider 对 strict schema、真实流、真实 usage 和费用的行为尚无在线证据，继续由 M8-T6 的单次授权冒烟验证。

## 未采用方案

- 使用字符串模型和 SDK 全局 Key：依赖隐式进程状态，容易串配置并泄漏。
- 使用默认 `RunConfig`：会继承不符合课程安全边界的 tracing 默认值。
- 把 Provider raw event 直接写入 Store：数据形状不稳定且会携带未审核内容。
- 把 aggregate usage 构造成一条 `UsageRecord`：会混淆 Run 汇总与单次模型调用，并伪造 duration/cost。
- Runtime 内自动重试整个 Runner：工具副作用状态未知时可能重复执行。
- 直接改用 Responses API：失去本阶段学习 Agents SDK Runner、tool loop 和事件模型的目标。

## 计划验证

- `backend/tests/test_openai_agents_runtime.py`
- `backend/tests/test_container.py`
- `backend/tests/test_framework_runtimes.py`
- M8-T3 Runtime、Coordinator、Store 与旧 API 兼容回归
- `scripts/verify.ps1`
- `scripts/check-continuity.ps1`
