# ADR-0013：有界 LangGraph 动态计划与副作用禁重放

- 状态：accepted
- 日期：2026-07-22
- 任务：`M10-T3`
- 依赖：`ADR-0007`、`ADR-0011`、`ADR-0012`

## 背景

现有 `create_research_graph()` 只生成固定三步演示计划，`LangGraphRuntime` 也只在模型与工具之间循环；两者都没有可恢复的结构化计划、失败诊断、重规划预算或循环检测。`RunFailure.retryable=true` 只能表达候选重试语义，不能单独授权整个工作流重新规划，否则鉴权、校验、审批或结果未知的副作用可能被错误重放。

M10-T3 需要真实执行 LangGraph 和 checkpointer，同时保持 M10-T1 的可信 thread、M10-T2 的审批边界和 M11 的进程重启范围。默认 Container、HTTP、多 Agent、PostgreSQL 和跨崩溃副作用恢复不属于本任务。

## 决策

### 1. 使用独立显式导入的重规划 Runtime

新增 `ReplanningLangGraphRuntime`，通过真实 `StateGraph` 执行 `plan -> execute -> diagnose -> replan`。它实现现有 `AgentRuntime.run()`，可由 `RunCoordinator` 显式注入，但不替换默认 Container，也不从 `backend.app.agent` 顶层导出第三方 LangGraph 模块。

planner 与 step executor 是瞬时注入协议。planner 只能返回 `TaskPlan`/`PlanStep`；executor 只能返回带安全输出或 `RunFailure` 的 `PlanStepResult`。planner 产生的 `side_effecting`/`requires_approval` 元数据不是授权来源；实际工具仍必须经过 `ToolRegistry` 和 M10-T2 审批边界。

### 2. Checkpoint 只保存最小可解释计划状态

checkpoint Schema 固定为 `bounded-replanning-v1`、版本 1，保存：

- owner scope 摘要与计划 revision；
- 当前操作 ID、已完成操作 ID 和副作用/审批标记；
- 实际执行次数、重规划次数和历史计划签名；
- 最近一次安全 `RunFailure` 分类与标准化终态。

原始请求、工具参数、中间工具输出、planner/executor、事件 sink 和取消对象都不进入 checkpoint。计划和步骤事件只公开稳定 operation、预算、revision 与错误分类，不包含原始输入或异常文本。

### 3. 重规划需要三重允许

只有同时满足以下条件才进入 `replan`：

1. `RunFailure.retryable` 为真；
2. `failure.code` 命中服务端 `DEFAULT_REPLANNABLE_FAILURE_CODES` 白名单；
3. category 不属于 auth/authorization、validation、approval、security、storage 或 cancellation，失败步骤也不是副作用步骤。

默认白名单只包含模型临时不可用、限流、超时和只读工具/MCP 超时或 I/O 候选。非白名单错误即使错误地标记 retryable 也不会改路；副作用步骤失败直接以稳定诊断停止。

### 4. 步骤、重规划和路径循环均有硬上限

`max_steps` 约束实际 step executor 调用总数，`max_replans` 约束 planner 改路次数。每次 replan 的剩余步骤数不能超过剩余执行预算。

计划签名只基于 operation 与副作用/审批标记，不包含可随意更名的 step ID；因此相同操作路径换 ID 后仍被判为循环。新计划不能引用已完成 step ID，也不能再次安排已完成的副作用 operation。

### 5. 恢复只对安全边界开放

同一进程的新 Runtime 实例复用共享 saver 时：

- 已有终态直接重放，不再次调用 planner 或 executor；
- 被任务取消打断的只读 pending step 可以从 LangGraph checkpoint 恢复；
- pending 副作用 step 的结果视为未知，返回 `side_effect_resume_unsafe` 并记录 `plan.stopped`，绝不自动重放。

这只证明同进程 E3。如何持久记录副作用开始/完成、处理提交结果未知、执行 lease 和进程重启由 M10-T5/M11 验收。

## 后果

- 固定三步演示之外，课程已有一条可解释、可 checkpoint、可由 durable Coordinator 执行的动态计划纵切。
- `RunFailure.retryable` 不再被当作自动重规划授权；服务端白名单、类别和步骤副作用属性共同 fail closed。
- 计划变化、步骤执行、失败、停止与终态先经过现有 EventStore/Coordinator 边界，可按 sequence 重放。
- 当前 planner/executor 仍由组合根显式提供，默认应用链未迁移；真实模型规划质量、生产容量和多进程一致性没有证据。

## 未采用方案

- 直接修改固定 `create_research_graph()`：会破坏早期确定性 Workflow 教学示例，并无法承载 Runtime/checkpoint 契约。
- 只检查 `failure.retryable`：调用方误分类即可重放权限或副作用失败。
- 原地重试同一失败 step：这不是重规划，且对结果未知副作用不安全。
- 把原始请求、工具参数或中间结果写入计划 state：扩大敏感面并违背 M10-T1 最小 checkpoint 决策。
- 自动恢复 pending 副作用节点：没有持久 ToolExecution 结果和幂等仲裁，无法证明不会重复执行。
- 在本任务切换默认 Container 或增加 HTTP 端点：分别属于后续集成与 M12，不是 M10-T3 最小纵切。

## 验证依据

- `backend/tests/test_langgraph_replanning.py`
- `backend/tests/test_langgraph_checkpointing.py`
- `backend/tests/test_langgraph_approval_resume.py`
- `backend/tests/test_run_coordinator.py`
- `V-20260722-001`
