# M10：LangGraph 持久工作流与任务推理

> 工程状态只查看 `../continuity/status.md`。M10 验证跨 invocation 恢复；真正进程重启后的 PostgreSQL 恢复由 M11 验收。

## 本阶段目标

使用 LangGraph 建立 checkpoint、interrupt、审批 resume、动态重规划和真实多 Agent 对照，同时保证副作用只执行一次。

- 时间预算：2 周，约 18–28 小时。
- 任务：M10-T1 至 M10-T6。
- 工作映射：长任务审批、工单自动化、研究工作流和故障恢复。

## 20% 关键知识

| 类型 | 知识点 | 工作场景 | 学到什么程度 | 验证任务 |
| --- | --- | --- | --- | --- |
| 必学 | State、thread ID、checkpoint | 长任务续接 | 跨调用恢复且隔离 | M10-T1 |
| 必学 | interrupt/Command resume | 人工审批 | 服务端绑定且单次执行 | M10-T2 |
| 必学 | 错误分类与重规划预算 | 工具故障 | 不循环、不乱重试 | M10-T3 |
| 高频 | manager 与 handoff | 多角色任务 | 能对比并选择 | M10-T4 |
| 易错 | checkpoint 等同 EventStore | 恢复设计 | 能说明快照与流水的区别 | 自测 |
| 易错 | 多 Agent 一定优于单 Agent | 架构评审 | 用数据而非角色数量判断 | M10-T5 |

## 跟练顺序

### 第 1 次：Checkpoint 与线程隔离

- 把 Run ID 稳定映射为 thread ID。
- 使用共享 checkpointer 验证跨 invocation 续接。
- 注入错用户、错 Run、缺 thread ID 和 checkpoint 损坏。

#### M10-T1 已验证纵切

代码入口：

- `backend/app/agent/runtime.py`：`RuntimeCheckpointContext`，由 owner/Run 派生版本化摘要。
- `backend/app/agent/checkpoint_runtime.py`：`CheckpointedLangGraphRuntime`，共享 `InMemorySaver` 并编译真实 `StateGraph`。
- `backend/app/services/run_coordinator.py`：只从持久 Run 注入可信 checkpoint 上下文。
- `backend/tests/test_langgraph_checkpointing.py`：10 项稳定线程、恢复、隔离、损坏、脱敏和失败恢复证据。

执行链：

```text
stored owner + run
  -> RuntimeCheckpointContext.for_run()
  -> thread_id
  -> advance superstep checkpoint
  -> existing AgentRuntime delegate
  -> normalized terminal state checkpoint
```

`RuntimeRequest`、Skill prompt、事件 sink 和取消对象只走本次 invocation context，不进入 checkpoint。`state_version=1` 是当前唯一接受版本；未知版本 fail closed，等后续有迁移 fixture 和显式 migrator 后再升级。

本纵切的“跨实例恢复”是两个 Runtime 对象共享同一内存 saver，不是操作系统进程重启。M10-T2 已增加 interrupt/审批 resume；M11 才把 saver 替换为 PostgreSQL 并验证真正重启恢复。

### 第 2 次：人工审批

- `ApprovalLangGraphRuntime` 的 `prepare` 节点先把服务端规划的调用写成 ApprovalRequest，`execute` 节点再调用 `interrupt()`；恢复不会重新规划工具参数。
- 从 `run.waiting_approval` 事件取得审批 ID、call、tool 和参数摘要，只向 `RunCoordinator.resume_approval()` 提交 `approve` 或 `reject`。客户端裸 `approved=true`、错摘要、错 call 或错 tool 均不能恢复执行。
- 批准后仍由 `ToolRegistry` 消费绑定 Run 的单次 approval；拒绝、过期、篡改和并发重复 resume 的 handler 调用数都必须为 0 或 1。
- 用以下离线命令复现本次纵切：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_approval_resume backend.tests.test_run_store_contract -v
```

新 Runtime 实例必须复用同一 `InMemorySaver` 和服务端内存 Store 才能恢复。该证据最高为同进程 E3；进程退出、结果未知和 PostgreSQL 恢复不在本次结论内。

### 第 3 次：计划与重规划

- 记录计划、已完成步骤、失败分类和尝试次数。
- retryable 故障允许有限改路；权限和校验错误禁止重试。
- 验证预算耗尽和循环检测。

### 第 4 次：多 Agent 对照

- 建立独立 researcher、writer、reviewer 指令和输出契约。
- 对比单 Agent、manager 和 handoff 的质量、调用数、延迟和成本。
- 如果没有收益，报告保留单 Agent 结论。

## 计划验证命令

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_langgraph_checkpointing -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_langgraph_approval_resume -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_langgraph_replanning -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_multi_agent -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_workflow_comparison_eval -v
```

## 常见错误与排查

| 现象 | 原因 | 排查 |
| --- | --- | --- |
| 同一 Run 无法续接 | thread ID 变化 | 对比 Run/thread 映射与 checkpointer 配置 |
| 审批后执行两次 | resume 重复或幂等缺失 | 检查 approval 单次状态和 tool execution |
| 永久错误不断重规划 | 错误分类错误 | 检查 retryable 和最大重规划次数 |
| 多 Agent 无限互调 | handoff 无预算 | 限制角色切换和返工次数 |
| 误称支持重启恢复 | 使用的是内存 checkpointer | 保留为 M11 验收，不修改证据措辞 |
| checkpoint 查询报 Subgraph not found | 把自定义 namespace 当成顶层子图 | 顶层只设置服务端派生 `thread_id`，不要虚构 `checkpoint_ns` |

## 自测

1. checkpoint 与 EventStore 分别解决什么问题？
2. 为什么 thread ID 不能由客户端任意指定？
3. 现场完成暂停、换调用实例恢复和副作用恰好一次。
4. 设计一个不应该重规划的权限失败案例。
5. 如何证明多 Agent 值得额外复杂度？

## 费曼复述

用“书签、暂停单和流水账”解释 checkpoint、interrupt 和 EventStore，并说明内存 checkpointer 为什么不能保证进程重启恢复。

## 官方资源

- LangGraph Persistence：<https://docs.langchain.com/oss/python/langgraph/persistence>
- LangGraph Interrupts：<https://docs.langchain.com/oss/python/langgraph/interrupts>
- OpenAI Agent orchestration：<https://openai.github.io/openai-agents-python/agents/#multi-agent-system-design-patterns>
