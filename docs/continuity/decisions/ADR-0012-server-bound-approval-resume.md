# ADR-0012：服务端绑定的 LangGraph 审批暂停与恢复

- 状态：accepted
- 日期：2026-07-20
- 任务：`M10-T2`
- 依赖：`ADR-0006`、`ADR-0007`、`ADR-0011`

## 背景

M10-T1 已提供服务端 owner/thread 绑定和版本化 checkpoint，但共享 `RuntimeResult` 只能表达终态，`EventStore` 也只有开始与终态原子提交。若把审批等待伪装成失败，Run 无法合法恢复；若只在 graph 内 `interrupt()` 而不提交 Run 状态，外层 API 又看不到可恢复的审批状态。

审批还不能信任模型或客户端提供的 `approved=true`。高风险或有副作用的工具必须绑定确定的 Run、身份、tool call、工具名和参数摘要，恢复后仍经过共享 `ToolRegistry` 的角色、审批和 Schema 检查。原始参数不得进入 checkpoint、Run 事件或公开对象。

## 决策

### 1. Runtime 显式区分暂停与终态

保留 `RuntimeResult` 的终态约束，新增 `RuntimeApprovalPause` 作为非终态结果，并用 `RuntimeOutcome` 表达二者。可恢复实现显式满足 `ApprovalResumableRuntime`，恢复入口只接收服务端生成的 `RuntimeApprovalResume`。

普通 Runtime 不会因此自动获得审批能力；不支持恢复的 Runtime 在等待状态下 fail closed。checkpoint 相关实现继续使用专用模块显式导入，不从 `backend.app.agent` 顶层导出第三方 LangGraph 模块，保留 M1 的 `python -S` 路径。

### 2. 审批请求、决议和消费是三个不同阶段

`InMemoryApprovalStore` 以 `(run_id, principal_id, tool_call_id, tool_name, arguments_digest)` 保存服务端审批请求，并在私有内存区保存脱离调用方引用的原始参数。公开请求、checkpoint 和事件只含 ID、工具标识、SHA-256 参数摘要与过期时间。

审批入口只接受 `approve` 或 `reject` 枚举语义；Python `bool` 和其他值直接拒绝。决议必须再次匹配完整绑定，过期由服务端时钟判定。批准只生成一条精确 grant；真正执行时 `ToolRegistry` 仍按同一 Run 和调用绑定消费一次。拒绝和过期不生成可消费 grant。

### 3. Graph 先固定请求，再进入 interrupt

`ApprovalLangGraphRuntime` 使用两个真实 `StateGraph` 节点：

1. `prepare` 根据服务端 planner 固定工具调用并创建审批请求，将安全元数据写入 state。
2. `execute` 调用公开 `interrupt()`；恢复时只接收服务端写入的审批 ID，再从 ApprovalStore 读取权威决议和私有参数。

Coordinator 使用公开 `Command(resume=...)` 恢复 graph。恢复不会重新运行 `prepare`，新 Runtime 实例也不会重新规划或替换已暂停调用。执行前同时核对 checkpoint、审批请求和决议的 ID、call、tool 与参数摘要。

### 4. Run 状态和生命周期事件必须原子提交

`EventStore` 增加 `PauseCommit` 与 `ResumeCommit`：

- `running -> waiting_approval + run.waiting_approval`
- `waiting_approval -> running + run.resumed`

内存适配器继续按 Run lock 再 Event lock 的固定顺序一次发布状态与事件；普通 `append()` 拒绝这两类生命周期事件。数据库适配器必须提供等价事务。

多个 Coordinator 可同时提交同一个 resume，但只有 `commit_resume(created=true)` 的赢家调用 Runtime。其他调用等待持久终态；重复 resume 和重复 grant 消费均不能再次执行 handler。等待审批的 Run 可以直接取消。

### 5. 当前恢复与副作用证据边界

M10-T2 的恢复只证明同一进程中，新 Runtime/Coordinator 实例复用同一 `InMemorySaver`、ApprovalStore、RunStore 和 EventStore 后可以继续。它不是操作系统进程重启、多进程或 PostgreSQL 恢复证据。

当前自动化证明正常批准、拒绝、过期、篡改、并发重复 resume 和终态重放不会重复副作用。若进程在工具已产生副作用但 terminal commit 结果未知时退出，仍需要持久 ToolExecution 幂等键、lease 和恢复扫描；该故障注入由 M10-T5/M11 继续验收，当前不得宣称跨崩溃恰好一次。

## 后果

- Run、Event 和 graph checkpoint 对同一次审批有一致且可重放的中间状态。
- 客户端只能表达选择，不能提供身份、工具参数、grant 或可信 resume payload。
- 原始工具参数保留在当前进程的服务端私有存储中，不进入 checkpoint 和事件；因此进程退出后也会丢失。
- `ToolExecutionContext.run_id` 让 M10 请求按 Run 隔离，同时保留旧无 Run grant 的直接调用兼容形式。
- Store 公共契约增加两个非终态原子提交，M11 PostgreSQL 适配器必须继承相同合同测试。

## 未采用方案

- 把 `waiting_approval` 塞进 `RuntimeResult`：破坏终态不变量，并使既有 Runtime/Coordinator 误判完成。
- 只在 graph 中 interrupt，不提交 Run/Event：外层状态不可查询、不可取消，也无法由 CAS 仲裁恢复执行者。
- `Command(resume={"approved": true})` 直接驱动工具：客户端布尔值成为授权来源，无法绑定身份和参数。
- 把原始参数写入 checkpoint 或事件：扩大敏感面，并让恢复 Schema 承担业务载荷。
- 恢复时重新调用 planner：工具名或参数可能漂移，审批不再对应原调用。
- 自动重试结果未知的副作用节点：没有持久幂等记录时无法证明不会重复执行。

## 验证依据

- `backend/tests/test_langgraph_approval_resume.py`
- `backend/tests/test_run_store_contract.py`
- `backend/tests/test_tool_security.py`
- `backend/tests/test_run_coordinator.py`
- `V-20260720-013`
