# ADR-0035：以可重放性和持久幂等为门的安全重试

- 状态：accepted
- 日期：2026-08-29
- 任务：`M13-T2`
- 依赖：`ADR-0007`、`ADR-0008`、`ADR-0017`、`ADR-0020`、`ADR-0034`

## 背景

仓库已有 Run 总 deadline、协作式取消、模型瞬态错误重试、MCP 单次请求 timeout、持久
`ToolExecution` 和恢复仲裁，但各 Runtime 的错误分类和重试等待并不统一：Manual/LangGraph
模型重试没有显式退避，SDK 只设置重试次数，MCP 适配器又把断线、远端失败和非法响应压成
通用工具错误。

如果只依据 `retryable=true` 自动重试，就可能在远端已成功但本地未收到响应时重复执行写操作。
反过来，完全不重试只读查询，则会把限流、短暂断线和本地 I/O 抖动直接暴露为失败。
Trace 和 usage ledger 只能描述已经发生的事实，不能充当幂等证明或重试授权。

## 决策

### 1. 中央目录只登记稳定、无内容的运行错误

`backend.app.reliability` 维护 Provider、MCP、Tool、Store、Run 和预算错误的 `code`、
`category`、公开安全消息与 `retryable`。Provider/MCP 适配器只能使用已登记错误码；原始异常、
远端结果、请求参数和凭据不进入 `RunFailure`、事件或日志。

`retryable` 只表示错误类别可能是瞬态，不等于允许当前操作重放。未知错误码 fail closed。

### 2. 所有自动重试同时通过六道门

一次失败只有同时满足以下条件才允许进入下一次尝试：

1. 错误目录标记为可重试；
2. 未超过该操作的重试次数预算；
3. 有副作用操作具有可信的持久幂等键；
4. 操作本身已被声明为幂等且可安全重放；
5. 结果未知时仍有足够证据证明重放安全；
6. 指数退避不会耗尽剩余 Run deadline。

任一条件无法证明就停止重试。当前 Manual、Agents SDK 和 LangGraph 主链没有把持久
`ToolExecution` 的外部结果仲裁证明注入普通工具调用，因此所有有副作用工具继续零自动重试；
即使已有一次人工批准，也不能把单次批准当成持久幂等键。

### 3. 只重试模型请求和只读工具，不重试整个 Runtime

- Manual/LangGraph 只对显式 `RetryableModelError` 使用有界指数退避；
- Agents SDK 使用公开 `ModelRetrySettings`、显式 backoff 和 provider-suggested policy；
- 共享 `ToolRegistry` 只重试无副作用工具的已分类 timeout、I/O 或 MCP 瞬态失败；
- Store mutation、Run terminal commit 和整个 Runtime 不套通用重试循环。既有持久命令、CAS、
  event ID、lease 和 recovery 继续拥有各自的重放协议，不能被本策略绕开。

默认生产组合为模型最多 2 次重试、100 ms 起步且最多 2,000 ms；只读工具最多 1 次重试、
100 ms 起步且最多 1,000 ms。直接构造旧 Runtime 的测试/兼容入口仍可显式使用零延迟或零重试。

### 4. 退避等待必须响应同一个 Run 取消和 deadline

`CancellationToken` 暴露剩余毫秒预算并提供可被取消唤醒的等待。Manual、LangGraph 和同步
工具 worker 在退避期间都使用同一个 Run token；取消获胜后不得开始下一次模型或工具尝试。

Coordinator 仍唯一拥有持久 `run.cancelled`、终态 CAS 和总 deadline。该协作式等待不等于硬杀
Python 线程、SDK transport 或已经发出的远端请求，`KI-017` 继续保留。

### 5. 重试事实进入持久观测，但不携带内容

`model.retrying` 和 `tool.retrying` 只记录 step、attempt、delay、可信工具名/调用 ID及稳定错误码。
M13-T1 的事件溯源投影把工具退避映射为 tool span 与 `agent.tool.retry` metric。参数、结果、
异常文本和 Provider payload 均不进入事件或 Trace。

## 后果

- 三种 Runtime 的生产组合共享同一次数/退避配置和只读工具执行策略；Provider 错误语义保持
  SDK 适配器所有，MCP 断线、超时、远端失败与非法响应不再被压成一个通用错误。
- 限流、短暂断线和只读 I/O 可恢复；鉴权、请求拒绝、非法响应、预算耗尽和不安全重放立即停止。
- 数据库故障不静默回退内存，也不对结果未知 mutation 做通用自动重试。
- 本任务不实现有副作用工具的自动重试；未来只有持久幂等键、外部结果仲裁和恢复测试全部存在
  时，才能另立 ADR 放宽。

## 未采用方案

- 重试整个 Agent Runtime：会重复模型调用、工具和持久事件，无法证明 exactly-once。
- 仅依据 HTTP 状态或 `retryable` 布尔值重试：缺少操作可重放性和结果未知判断。
- 把审批 ID 当作幂等键：审批只授权一次调用，不证明外部副作用没有发生或可安全重放。
- 为副作用工具生成进程内随机键：重启后丢失，不能满足持久幂等。
- 用固定 sleep：无法响应取消，且可能越过总 deadline。

## 验证依据

- `backend/tests/test_reliability.py`
- `backend/tests/test_manual_agent_loop.py`
- `backend/tests/test_runtime_comparison.py`
- `backend/tests/test_openai_agents_runtime.py`
- `backend/tests/test_mcp_tool_adapter.py`
- `backend/tests/test_run_coordinator.py`
- `V-20260829-001`
