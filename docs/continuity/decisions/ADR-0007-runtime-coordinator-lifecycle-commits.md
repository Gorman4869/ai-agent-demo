# ADR-0007：异步 Runtime、持久通知与生命周期一次提交边界

- 状态：accepted
- 日期：2026-07-16
- 任务：`M8-T3`
- 实现锚点：`b171ad0`

## 背景

M8-T2 已建立 durable Run、EventStore 和 version CAS，但尚未规定 Runtime 如何异步执行、过程事件如何通知，以及 Run 状态与生命周期事件如何避免半提交。旧 `ManualAgentLoop` 同步执行并返回包含完整事件的 `AgentRunResult`；直接把它改写成 async 或把所有旧事件原样持久化，会同时破坏旧教学链、泄漏工具结果，并把未来 SDK 绑进 API。

此外，以下顺序都不成立：

```text
transition terminal -> append terminal event
```

终态 Store 会拒绝晚到事件；反过来先 append 再 transition 又有崩溃窗口。`queued -> running` 与 `run.started` 也有同样问题。生命周期必须有明确的一次提交用例边界。

## 决策

### 1. 统一异步 Runtime 契约

定义四个 SDK 无关类型和一个 Protocol：

- `RuntimeRequest`：Run ID、隐藏 repr 的输入和可信执行上下文。
- `RuntimeControl`：每次调用独立的协作式 `CancellationToken`。
- `RuntimeEvent`：只允许非 `run.*` 的过程事件。
- `RuntimeResult`：当前只允许 completed、failed、cancelled，并强制 answer/failure 一致。
- `AgentRuntime.run(request, emit, control)`：统一 async 边界。

Runtime 负责模型、工具或工作流，不读取或写入 RunStore。`waiting_approval`、interrupt 和 resume 在 M10 扩展，不能伪装成失败。

### 2. ManualRuntime 是兼容适配器

`ManualRuntime` 每个 Run 通过工厂创建新的同步 Loop，再用 `asyncio.to_thread()` 执行；旧 `ManualAgentLoop.run()`、`execute_agent()`、旧 HTTP/SSE 和旧 observer 不修改。

适配器消费旧首尾 `run.*` 事件以校验结果，只映射审核过的过程字段。工具参数、原始结果、错误消息、输入和答案副本均不进入过程 Store。未知旧事件类型返回稳定 contract failure。

取消 Python 线程只能协作进行。异步任务取消时先设置同一个 token，等待有限清理宽限；宽限后消费后台 worker 的最终结果/异常而不无限阻塞 Coordinator。ManualRuntime 在同步 Loop 完成后才回放过程事件，因此不是实时审计，该限制由 `KI-017` 跟踪。

### 3. Coordinator 独占生命周期

`RunCoordinator` 只编排 Runtime、Store、通知器和控制信号：

```text
commit_start
  -> Runtime.run(progress -> append -> notify)
  -> commit_terminal
```

- `StartCommit` 一次提交 `queued -> running` 与 `run.started`。
- `TerminalCommit` 一次提交 completed/failed/cancelled、答案或安全失败与匹配终态事件。
- 普通 EventStore append 拒绝四类已拥有的生命周期事件。
- start 与各终态使用由 Run、阶段和目标状态派生的稳定 event ID。
- 精确重放返回原状态/事件和 `created=false`；不增加 sequence，也不重复实时通知。

内存实现始终按 Run lock → Event lock 获取锁，并在无 await 的临界区完成 owner 校验、event replay、version CAS、状态构造、sequence 分配和双边发布。模型、工具与 notifier 均在锁外执行。M11 PostgreSQL 实现必须用同一 Protocol 和单数据库事务。

### 4. 事件先持久化，通知只是最佳努力

`PersistentEventEmitter` 固定顺序为：

1. 调用 EventStore。
2. 得到 Store 分配的 sequence 与时间。
3. Store 操作及锁已经结束。
4. 有界 await notifier。

Store 失败时不通知；notifier 抛错或超时只记录不含异常文本的安全诊断，不回滚事件，也不改变 Run 结果。EventStore 是真相源，M12 SSE 从它补发。

### 5. 并发、取消和 deadline

- 同一 Coordinator 内，同 owner/run 的并发 `execute()` 共享一个 shielded task；取消一个 waiter 不取消执行。
- 多个 Coordinator 同时启动时，只有 `StartCommit.created=true` 的执行者调用 Runtime；重放者等待并读取 durable 终态，避免重复副作用。
- `cancel()` 不只设置内存 token，还提交 cancelled CAS。完成、取消和超时由 Store version 决定唯一赢家。
- 若取消发生在过程 emit 的 token 检查之后、append 之前，append 在终态检查处失败，执行方读取并返回 durable 赢家。
- 执行 deadline 从首次协调任务创建开始；启动通知消耗预算。deadline 后允许有限 worker 清理、生命周期提交和有界通知，因此不承诺严格相等的端到端硬墙钟。

### 6. Container 与旧 API 边界

Container 默认构造匹配的内存 Store、`ManualRuntime + MockModel` 和 RunCoordinator，消费 `max_steps`、`max_model_retries` 与 Run 执行 deadline。默认路径不创建在线 Runner 或网络连接。

旧路由仍闭包绑定 legacy `run_service`，响应和 SSE 不变，也不双写 durable Store。M8-T3 只提供程序化新链；M12 才迁移统一 HTTP/SSE。

## 后果

- 新 SDK 和 LangGraph Runtime 可以复用同一 application boundary，不修改 Coordinator。
- 生命周期状态与事件在内存实现中不再半提交；取消/完成竞争有确定持久赢家。
- 通知失败不会伪造事件丢失，消费者可以按 sequence 重放。
- 仓库仍有 legacy 与 durable 两条 Run 链，测试必须持续证明旧 API 不双写。
- `KI-015` 降为 mitigated，但 PostgreSQL、多 worker、连接结果未知和进程重启尚未证明。
- 过程 Store 不可用会保留 running Run 等待恢复，不能安全伪造 failed；由 `KI-016` 跟踪。
- 同步 worker 不是真流式、不能硬取消；由 `KI-017` 跟踪。

## 未采用方案

- 把旧 ManualAgentLoop 改写成 async：会破坏 M1 教学价值和既有兼容门。
- 直接持久化旧 AgentEvent：会泄漏工具 value/error_message，且没有持久 ID、sequence 或有界 JSON 保证。
- 用 `transition()` 加 `append()` 模拟生命周期事务：存在半提交或终态拒绝窗口。
- 先 notify 后 append：消费者会看到无法重放的幽灵事件。
- 让 Coordinator 解析 Provider/SDK 对象或包含工具业务规则：会破坏 Runtime 替换缝。
- fire-and-forget emit：无法证明顺序，也无法让 Store 失败阻止通知。
- 强制终止 Python worker thread：Python 没有安全通用机制，可能破坏工具和共享状态。
- 在 Store 不可用时写一个仅内存 failed：会伪造 durable 事实并掩盖结果未知。

## 验证依据

- `backend/tests/test_runtime_contract.py`
- `backend/tests/test_run_coordinator.py`
- `backend/tests/test_run_store_contract.py`
- `backend/tests/test_api.py`
- `backend/tests/test_container.py`
- `V-20260716-005`
