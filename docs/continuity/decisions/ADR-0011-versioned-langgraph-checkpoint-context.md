# ADR-0011：版本化 LangGraph Checkpoint 与可信线程上下文

- 状态：accepted
- 日期：2026-07-20
- 任务：`M10-T1`
- 依赖：`ADR-0003`、`ADR-0006`、`ADR-0007`、`ADR-0010`

## 背景

现有 `LangGraphRuntime` 每次调用都从新 state 开始，不能证明同一 Run 在两次 invocation 之间恢复。Run/Event Store 已持久化生命周期与可重放事件，但它不是工作流节点快照，不能替代 LangGraph checkpointer。

thread ID 若由客户端或模型提供，会让攻击者尝试读取其他用户的 checkpoint。另一方面，把原始用户标识、请求、Skill prompt、事件 sink 或取消对象写进 graph state，会扩大持久化敏感面并让状态 Schema 难以迁移。

M10-T1 只能证明进程内共享内存恢复。interrupt、审批 resume、进程重启和 PostgreSQL 恢复属于后续任务，不能为了宣称“持久化”而混入当前纵切。

## 决策

### 1. Coordinator 派生版本化线程上下文

`RunCoordinator` 使用 Store 中的可信 `owner_id` 与 `run_id` 调用 `RuntimeCheckpointContext.for_run()`。上下文只保存版本化 SHA-256 owner scope 和 thread ID，不保存原始 owner；`RuntimeRequest` 校验 thread 必须与同一个 run 绑定，且字段继续隐藏 repr。

客户端、模型和工具参数都没有 thread ID 写入入口。摘要不是授权替代品；Store 与 Coordinator 仍负责真实 owner 校验。

### 2. 独立包装现有 Runtime

新增 `CheckpointedLangGraphRuntime`，它包装一个既有 `AgentRuntime`，持有共享 `BaseCheckpointSaver` 并在构造时编译一次真实 `StateGraph`。默认使用现有依赖中的 `InMemorySaver`，也允许测试或后续 composition root 显式注入兼容 saver。

现有 `LangGraphRuntime`、三 Runtime 对照和 Container 默认选择保持不变。新模块使用显式导入，不从 `backend.app.agent` 顶层导出，避免 M1 在 `python -S` 下被第三方 LangGraph 依赖污染。

### 3. 持久 state 与瞬时 context 分离

checkpoint state 版本固定为 1，只包含：

- `state_version`
- owner scope 摘要
- `invocation_count`
- 标准化 `RuntimeResult` 的状态、答案、失败字段与 step

delegate、`RuntimeRequest`、Skill prompt、事件 sink 与 `RuntimeControl` 只通过 LangGraph `context_schema` 传给本次 invocation，不写入 checkpoint。答案和公开失败信息沿用现有 RuntimeResult 契约；原始请求、工具参数、工具结果和异常文本不得进入 state。

### 4. 当前迁移边界为显式拒绝

执行前读取已有 checkpoint 并验证版本、owner scope 与计数。M10-T1 只接受 `state_version=1`；未知版本、错 owner 或损坏 state 返回稳定失败，不静默猜测、降级或原地修改。

后续需要升级 Schema 时，先新增显式 migrator 和旧版本固定 fixture，再提高当前版本。没有迁移实现前，“拒绝未知版本”就是迁移边界。

### 5. 节点失败不触发隐藏重试

图先执行 `advance` 节点并保存新的 invocation 计数，再执行 delegate 节点。delegate 抛出普通异常时返回稳定 `checkpoint_node_failed`，不保留原始文本；前一 superstep 仍可供下一次同 thread invocation 恢复。

`StoreError` 与外层 `CancelledError` 原样传播。checkpointer 不可用返回可重试的稳定存储失败，但 Runtime 不自动重试 delegate，尤其不能在 checkpoint 写入结果未知时重复副作用。

## 后果

- 两个 Runtime 实例只要共享同一个 saver，就能对同一 owner/run thread 跨 invocation 恢复；相同 run ID 的不同 owner 使用不同 thread。
- graph state 有可测试的最小 Schema 和版本边界，瞬时对象不会污染 checkpoint。
- EventStore 继续负责生命周期与事件重放；checkpointer 负责工作流快照，两者不能互相替代。
- `InMemorySaver` 在进程退出后丢失，也不提供多进程一致性、容量、加密或清理保证。M11 才验收 PostgreSQL 与真实重启恢复。
- 当前没有 interrupt/resume 或审批中间态，`RuntimeResult` 仍只表示终态；M10-T2 扩展时必须单独决策。

## 未采用方案

- 客户端直接提供 `thread_id`：破坏服务端 owner/run 绑定，存在跨用户探测风险。
- 直接使用原始 `run_id` 作为 thread：相同 ID 的不同 owner 不能隔离，也暴露内部标识。
- 把完整 RuntimeRequest 放进 graph state：会持久化原始输入、Skill prompt 和可信执行上下文，扩大泄漏与迁移风险。
- 修改现有 `LangGraphRuntime` 和默认 Container：会扩大 M10-T1 迁移范围并破坏已验证的三 Runtime 对照与 M1 隔离门。
- 捕获节点异常后从头自动重试：无法在副作用与 checkpoint 写入结果未知时保证恰好一次。
- 把 `InMemorySaver` 描述成重启持久化：证据只能覆盖同一进程共享对象，结论不成立。

## 验证依据

- `backend/tests/test_langgraph_checkpointing.py`
- `backend/tests/test_runtime_contract.py`
- `backend/tests/test_run_coordinator.py`
- `backend/tests/test_skill_context.py`
- `V-20260720-011`
