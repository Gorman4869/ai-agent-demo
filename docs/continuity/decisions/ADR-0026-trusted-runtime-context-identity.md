# ADR-0026：可信 Runtime Context Identity 传播边界

- 状态：accepted
- 日期：2026-08-09
- 任务：`M11-T4`
- 依赖：`ADR-0010`、`ADR-0013`、`ADR-0025`

## 背景

`ContextAwareRuntime` 已能从注入的 factory 获取 owner/session 并执行 collector→Assembler，但现有 `RuntimeRequest` 只有输入、执行上下文、提示上下文和 checkpoint 摘要。默认 `RunCoordinator` 在调用 Runtime 时持有完整 `RunRecord.owner_id/session_id`，Runtime 端却无法从请求获得这组可信身份。

从 `input_text`、工具参数、`ToolExecutionContext.principal_id` 或 run ID 推导 session 都不成立：这些值分别属于用户内容、模型/工具数据、执行授权或运行标识，不能替代持久 Run 已绑定的会话所有权。把 Context factory 配成静态 closure 也无法为并发 Run 提供正确隔离。

本纵切只固定 Coordinator→Runtime 的身份合同，不接默认 Container，不把同步 PostgreSQL Memory/pgvector 放入 async Runtime，也不提前实现 M11-T5 的持久记忆主链。

## 决策

### 1. Agent Runtime 层拥有最小身份对象

`backend.app.agent.runtime` 定义冻结的 `RuntimeContextIdentity(owner_id, session_id)`。两个字段必须是有界、非空、无空白和控制字符的标识，并从常规 repr 隐藏。

`RuntimeRequest` 在现有字段末尾增加可选 `context_identity`，保持旧位置参数和直接 Runtime 调用兼容。该字段不参与请求相等比较，也不进入 prompt、事件或 checkpoint。

### 2. RunCoordinator 只从当前 RunRecord 构造身份

`RunCoordinator` 的 execute 与 approval resume 共用 `_run_runtime()`；每次调用都从当前 owned `RunRecord.owner_id/session_id` 新建 identity。用户输入、工具参数、execution principal、模型结果和 run ID 均不参与 session 或 owner 选择。

Coordinator 同时使用相同 Run owner 构造 `RuntimeCheckpointContext`。当 RuntimeRequest 同时携带 checkpoint 和 context identity 时，两者 owner 必须匹配，否则请求构造 fail closed。

### 3. Context 层只映射，不推断

显式 `RuntimeIdentityBindingFactory` 只把 `RuntimeRequest.context_identity` 映射为既有 `RuntimeContextBinding`，并附加应用固定 system constraints。identity 缺失或格式不合法时产生稳定无内容 preparation error；`ContextAwareRuntime` 继续映射为 `context_unavailable`，不调用 source 或 delegate。

Context query 仍只取原 `RuntimeRequest.input_text`。factory 不读取 execution principal、run ID、prompt_context 或工具参数来修补缺失身份。

### 4. 保持显式集成边界

直接调用 Manual、SDK 或 LangGraph Runtime 时，identity 可以缺省，因为这些 Runtime 本身不读取 Context Store。显式使用 `ContextAwareRuntime` 的调用方必须提供 identity；默认 Container 接线将在后续纵切统一替换旧 Skill wrapper，不能把两个 prompt owner 叠加。

本身份对象不证明 session 确实属于 owner；该事实来自已验证 RunStore/RunRecord 所有权合同和 Coordinator 的 owned read。它也不是对外部请求开放的认证 DTO。

## 后果

- 并发 Run 可把持久 Run 已确认的 owner/session 传到 Context collector，不再依赖静态 closure 或不可信字段猜测。
- checkpoint owner 与 Context owner 在 RuntimeRequest 构造时相互校验，降低错误组合导致跨 owner 上下文的风险。
- `RuntimeRequest` 是多里程碑共享契约，必须覆盖直接构造、三种 Runtime、Coordinator execute/resume、Context adapter、Container 和完整离线门。
- 当前同步 collector 仍只能作为显式内存路径；PostgreSQL async source、默认 Container、审批恢复时的 Context 刷新策略和持久记忆写入仍未验证。

## 未采用方案

- 从 `ToolExecutionContext.principal_id` 同时充当 owner/session：principal 只表达执行身份，没有会话标识，且会混淆授权与数据范围。
- 把 session 编码进 run ID 或 checkpoint digest 后再反解：现有摘要是单向安全绑定，不保存可恢复 session，猜测会破坏隔离合同。
- 让 Context factory 查询 RunStore：会让每个 Runtime wrapper 重复持久化依赖和 async 生命周期，并在本纵切扩大到默认 composition。
- 把 identity 设为所有 RuntimeRequest 必填：会破坏大量无需 Context Store 的直接 Runtime 教学和测试调用，不能提供额外应用安全收益。
- 立即接默认 Container：现有默认 Runtime 已由 SkillAwareRuntime 占用 prompt_context，且 PostgreSQL source 需要 async 边界；应在身份合同稳定后单独迁移。

## 验证依据

- `backend/tests/test_runtime_contract.py`
- `backend/tests/test_run_coordinator.py`
- `backend/tests/test_context_runtime.py`
- `V-20260809-014`
