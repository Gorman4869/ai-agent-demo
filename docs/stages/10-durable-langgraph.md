# M10：LangGraph 持久工作流与任务推理

> 工程状态只查看 `../continuity/status.md`。M10 验证跨 invocation 恢复；真正进程重启后的 PostgreSQL 恢复由 M11 验收。

## 本阶段目标

使用 LangGraph 建立 checkpoint、interrupt、审批 resume、动态重规划和真实多 Agent 对照；已知恢复路径不重复副作用，结果未知时 fail closed。

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
| 易错 | 多 Agent 一定优于单 Agent | 架构评审 | 用数据而非角色数量判断 | M10-T4 |

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

- `ReplanningLangGraphRuntime` 记录 operation 计划、已完成步骤、revision、失败分类、执行次数、重规划次数和历史路径签名；原始问题、工具参数和中间输出不进入 checkpoint。
- 只有 `retryable=true`、错误码命中服务端白名单、category 安全且步骤无副作用时才允许有限改路。权限、校验、审批、存储和取消错误禁止重规划。
- 相同操作路径即使更换 step ID 也会触发循环检测；新计划不能重复已完成副作用。结果未知的 pending 副作用返回 `side_effect_resume_unsafe`，不自动重放。
- 通过以下离线命令执行真实 StateGraph、共享 saver 恢复与 durable Coordinator/EventStore 纵切：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_replanning -v
```

该纵切使用确定性 planner/executor fixture 验证框架和领域契约，证据最高为本地 E3，不是在线规划质量、进程重启或跨崩溃副作用恰好一次。固定输入、固定规则和无需失败改路的任务仍优先使用普通 Workflow。

### 第 4 次：多 Agent 对照

- `create_manager_as_tools_topology()` 建立独立 researcher、writer、reviewer：manager 只调用三个 `Agent.as_tool()`，researcher 只有固定事实查询工具，writer 没有业务工具，reviewer 只有要求检查工具。
- `run_offline_multi_agent_comparison()` 对三个固定课程问题分别运行真实 `Runner.run()` manager-as-tools 和同工具单 Agent。每次嵌套角色执行都受 turns 上限、无 Trace 配置和共享 `ToolRegistry` 权限/Schema 边界约束。
- 当前固定集两组质量均为 1.0、失败率均为 0。manager 每例 9 次 fixture request/108 fixture Token、复杂度 12；单 Agent每例 3 次/36 Token、复杂度 3，本地实测延迟也更低，因此结论保留单 Agent。
- 运行完整可复现实验：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.multi_agent
```

输出中的 `E2_offline_fixture`、`local_runner_with_fixture_model_delay` 和 `deterministic_fixture_usage_not_provider_billing` 是证据范围，不是在线 Provider、真实 tokenizer、账单或生产容量。manager-as-tools 不修改现有 `OpenAIAgentsRuntime` 对 handoff event 的 fail-closed 处理，也不进入默认 Container。

### 第 5 次：恢复故障矩阵

M10-T5 用 10 个确定性场景对三个纵切做故障注入：

| 边界 | 注入点 | 安全结果 |
| --- | --- | --- |
| Checkpoint | 读取不可用、状态损坏 | delegate/planner/executor 不运行，Run 以稳定失败和 `run.failed` 结束 |
| 只读重规划 | step 执行中断、`tool_timeout` | 共享 saver 可由新 Runtime 恢复；timeout 只在白名单与预算内改路 |
| 审批等待 | 换 Runtime、取消、丢 saver | 只消费一次；取消或缺 checkpoint 时 handler 不运行 |
| 结果未知副作用 | 重规划 step 中断、审批后 checkpoint 写失败 | 不重放；返回 `side_effect_resume_unsafe` 并记录 `plan.stopped` 或 `approval.stopped` |
| 副作用 timeout | executor 返回可重试 timeout | 仍禁止重规划，记录 `plan.stopped` |

执行专项：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_recovery_faults -v
```

故障 saver 只在测试进程内阻断 checkpoint 写入，用来保留“handler 已发生、graph 仍停在 interrupt”的窗口。它不是 PostgreSQL 或进程崩溃模拟器；M11 才实现持久 ToolExecution、lease、恢复扫描和真实进程重启验收。

## 三张核心状态图

### 1. Run 生命周期与审批暂停

```text
created
  -> running
       -> waiting_approval
            -> running
                 -> completed | failed | cancelled
       -> completed | failed | cancelled
```

`run.waiting_approval` 与 `run.resumed` 必须和 Run 状态原子提交。客户端只提交 approve/reject 选择；Run、principal、call、tool 和参数摘要都来自服务端记录。

### 2. 有界重规划图

```text
START -> plan -> execute -> END
          ^        |
          |        v
          +-- replan <- diagnose
```

只有 retryable、错误码白名单、category 安全、非副作用步骤和剩余预算同时满足，`diagnose` 才能进入 `replan`。任何一项不满足都形成稳定终态，不原地重试失败步骤。

### 3. 恢复决策图

```text
读取 checkpoint
  -> 终态：直接返回，不再调用 planner/executor
  -> pending 只读步骤：同进程共享 saver 后继续
  -> pending 副作用：结果未知，side_effect_resume_unsafe
  -> 版本/owner/结构不合法：稳定失败，不猜测迁移
  -> saver 不可用：checkpoint_unavailable，不隐藏重试
```

EventStore 是生命周期和过程事件流水，checkpointer 是工作流快照。两者都不能单独提供跨进程 exactly-once；M10 也没有该证据。

## M10 里程碑跟练

四次训练共约 9–13 小时。每次先写预期状态图和未验证边界，再运行命令；学习者个人结果只写 `../progress.md`。

### 第 1 次：Checkpoint、线程隔离与状态边界

- 时间预算：2–3 小时。
- 目标：画出 `RunCoordinator -> RuntimeCheckpointContext -> StateGraph -> InMemorySaver`，区分 checkpoint 与 EventStore。
- 动作：运行 checkpoint 专项；定位 owner/run 如何派生 thread；任选缺 thread、错 owner、未知版本或损坏计数一个失败分支，记录稳定 code 和 delegate 调用数。
- 命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_checkpointing -v
```

- 产物：可信 thread 数据流、最小 checkpoint Schema、一次损坏状态复盘。
- 工作映射：长任务续接、工单处理、后台批任务和租户隔离。
- 通关：能说明原始 owner/input/prompt 为什么不进 checkpoint；能证明共享内存 saver 只覆盖同进程换 Runtime 实例。

### 第 2 次：Interrupt、服务端审批与单次消费

- 时间预算：2–3 小时。
- 目标：从 `prepare -> interrupt -> waiting_approval -> Command(resume) -> ToolRegistry` 完成一次服务端绑定审批。
- 动作：先跑 approve，再跑 reject/expired/tampered/duplicate；从事件读取公开绑定字段，指出原始参数存放位置，并核对 handler 调用数。
- 命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_approval_resume backend.tests.test_run_store_contract -v
```

- 产物：审批时序图、公开/私有数据表、重复 resume 与取消结果摘要。
- 工作映射：发版、付款、发邮件、写工单等高风险动作。
- 通关：能解释为什么 `approved=true` 不是授权；能证明审批、Run 状态和 handler 单次消费的边界。

### 第 3 次：失败重规划与多 Agent 取舍

- 时间预算：2–3 小时。
- 目标：用失败分类和预算控制动态计划，并用同一固定集判断多 Agent 是否值得。
- 动作：运行重规划专项，分别观察只读 timeout 改路、权限失败停止、循环检测和副作用禁止重放；再运行真实 manager-as-tools 对照。
- 命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_replanning -v
.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.multi_agent
```

- 产物：重规划三重门、预算表、单 Agent/多 Agent 质量与复杂度决策记录。
- 工作映射：研究任务改路、供应商降级、角色协作架构评审。
- 通关：不会把 retryable 当自动重试授权；能根据质量、失败率、调用量、延迟和复杂度保留更简单的方案。

### 第 4 次：故障演练与里程碑验收

- 时间预算：3–4 小时。
- 目标：从恢复矩阵任选一个结果未知故障，完成“注入 -> 观察 -> 稳定终态 -> 副作用计数 -> 未验证范围”，再运行完整离线门。
- 动作：运行 M10 故障专项和聚焦集；使用[M10 一页速查表](../m10-langgraph-cheat-sheet.md)复盘；最后运行全仓验证与连续性检查。
- 命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_recovery_faults -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

- 产物：故障复盘、自测答卷、速查表使用记录和费曼复述。
- 工作映射：发布门禁、故障恢复评审、审批安全审计和架构答辩。
- 通关：全部退出码、跳过、警告和离线边界如实记录；不得把内存故障夹具描述成 PostgreSQL、进程 kill 或 exactly-once。

## 故障定位演练

| 注入或现象 | 第一定位层 | 合格判断 |
| --- | --- | --- |
| 同一 Run 换实例后找不到状态 | checkpoint context / saver | thread 相同且复用同一个 saver；新建空 saver 应稳定失败 |
| 相同 run ID 读到其他用户状态 | owner scope | thread 必须由可信 owner/run 派生，客户端无写入口 |
| checkpoint 版本或计数损坏 | state validation | 返回稳定 version/state code，planner/delegate 不运行 |
| 客户端只传 `approved=true` | approval binding | 缺完整服务端决议时不能执行工具 |
| 两个 Coordinator 同时 resume | Run/Event CAS | 只有 commit winner 调 Runtime，handler 最多一次 |
| 只读工具 `tool_timeout` | diagnose/replan gate | 白名单、category、retryable 和预算全部满足才改路 |
| 副作用工具 timeout 或 checkpoint 写失败 | side-effect boundary | 不重放，返回 `side_effect_resume_unsafe` 或禁止重规划诊断 |
| 多 Agent 调用量上升但质量不变 | evaluation/architecture | 保留单 Agent，不能用角色数量代替收益证据 |

排查顺序：Run/owner/thread -> saver 快照 -> state version/shape -> Run/Event 生命周期 -> approval binding/grant -> failure category/allowlist -> step/replan budget -> side-effect outcome -> 多 Agent 评测。不要先放宽权限、预算或重试次数。

## M10 验证命令与证据等级

M10 聚焦验收：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_checkpointing backend.tests.test_langgraph_approval_resume backend.tests.test_langgraph_replanning backend.tests.test_langgraph_recovery_faults backend.tests.test_multi_agent backend.tests.test_workflow_comparison_eval -v
.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.multi_agent
```

里程碑门：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

| 证据 | 最高等级 | 能证明 | 不能证明 |
| --- | --- | --- | --- |
| import、配置、对象构造 | E1 | API 形状与默认值 | graph、interrupt 或角色链已执行 |
| 真实框架 + 确定性 fixture | E2 | StateGraph、Command、Runner 进入实际调用链 | Provider、真实费用或生产性能 |
| 框架 + Coordinator/Store/Registry 契约 | E3 | 同进程恢复、审批绑定、失败诊断和副作用禁重放 | PostgreSQL、进程重启、多进程与 exactly-once |
| 经单独授权的生产恢复验证 | E4 | 指定环境和当次恢复结果 | 永久兼容或无限容量 |

既有不可变证据索引：M10-T1 为 `V-20260720-011/012`，M10-T2 为 `V-20260720-013/014`，M10-T3 为 `V-20260722-001/002`，M10-T4 为 `V-20260722-003/004`，M10-T5 为 `V-20260722-005/006`。M10-T6 实际结果只从 verification log 查询，不在本章复制动态状态。

## 常见错误与排查

| 现象 | 原因 | 排查 |
| --- | --- | --- |
| 同一 Run 无法续接 | thread ID 变化或没有复用 saver | 对比 owner/run 派生结果和 checkpointer 实例 |
| checkpoint 有状态但事件列表为空 | 混淆 graph 快照与 EventStore | 分别检查 saver 和 Run/Event Store，不互相代替 |
| 审批后执行两次 | 绕过 Coordinator CAS 或 approval 单次消费 | 检查 pause/resume commit、grant 和 handler 计数 |
| 客户端布尔值恢复成功 | 把客户端输入当授权 | 只接受服务端绑定决议和完整摘要匹配 |
| 永久错误不断重规划 | 只检查 retryable | 检查 code 白名单、category、side_effecting 和预算 |
| 相同路径换 step ID 后循环 | 签名错误地包含 cosmetic ID | 以 operation 与副作用/审批标记生成路径签名 |
| 副作用结果未知时自动重试 | 没有持久 ToolExecution 仲裁 | 返回 unsafe 终态；持久恢复留 M11 |
| 多 Agent 无限互调 | specialist/manager 无 turns 上限 | 限制调用预算，失败向外传播 |
| 误称支持进程重启 | 使用的是 `InMemorySaver` | 只写同进程跨 invocation/换实例；M11 验收真重启 |
| checkpoint 查询报 Subgraph not found | 把 namespace 当顶层子图 | 顶层只设置服务端派生 `thread_id` |

## M10 自测题库

### 概念题（5 题，共 20 分）

1. checkpoint 与 EventStore 分别保存什么，为什么不能互相替代？
2. thread ID 为什么必须由服务端 owner/run 派生，摘要为什么仍不是授权替代品？
3. `interrupt()`、`Command(resume=...)`、ApprovalStore 和 ToolRegistry 各自负责哪一段？
4. 一个失败进入 replan 前必须通过哪些门，为什么 retryable 不足够？
5. 什么时候多 Agent 值得额外复杂度，当前固定集为什么保留单 Agent？

评分：每题 4 分；定义正确 2 分，边界或反例 2 分。

### 实操题（4 题，共 40 分）

1. 运行 checkpoint 专项，画出 owner/run/thread/state 数据流，并解释一个损坏 checkpoint 为什么不会调用 delegate。
2. 完成 approve、reject 和 duplicate resume 三条审批路径，列出 Run 事件顺序、公开字段、私有参数位置和 handler 调用数。
3. 构造只读 timeout 与副作用 timeout，分别证明前者可有界改路、后者稳定停止；给出 planner/executor 调用序列。
4. 运行 manager-as-tools 对照，依据质量、失败率、fixture request/Token、本地延迟和复杂度写出保留或拒绝多 Agent 的决策。

评分：每题 10 分；可复现证据 4 分，状态/数据流解释 3 分，失败与边界 3 分。

### 工作场景题（4 题，共 40 分）

1. 设计一个付款审批工作流：说明 thread、审批绑定、原始参数、Run/Event 原子提交和重复 resume 仲裁。
2. 写工单工具超时且结果未知。判断哪些动作可以重规划，哪些必须停止，并说明后续持久幂等需要什么。
3. 产品要求“服务器重启后继续审批”。指出 M10 现有证据缺什么，并列出 M11 的 PostgreSQL checkpointer、持久私有参数、ToolExecution、lease 和恢复扫描要求。
4. 团队提议把研究任务拆成五个 Agent。设计固定对照，说明何种质量/失败率收益才值得增加调用与运维复杂度。

评分：每题 10 分；方案 4 分，取舍 3 分，风险与未验证范围 3 分。

总分达到 80 分通关。以下任一项出现即使总分达标也不通过：把 import 当框架执行证据、让客户端提供 thread/身份/审批、把 retryable 当自动重试授权、自动重放结果未知副作用、把 `InMemorySaver` 写成进程重启、把 fixture Token/延迟写成 Provider 账单/生产性能、或预设多 Agent 一定更好。

## M10 一页速查表

工作时优先打开 [M10 LangGraph 持久工作流一页速查表](../m10-langgraph-cheat-sheet.md)。先凭记忆画三张状态图，再用速查表纠正；如果仍需通读本章才能判断一个 timeout 是否可重规划，说明该项尚未内化。

## M10 费曼复述任务

不查资料，向一名只熟悉普通 CRUD 的前端同事讲 6 分钟：

1. 用“书签、暂停单、流水账”区分 checkpoint、interrupt 和 EventStore。
2. 一次高风险工具调用如何从服务端计划进入 waiting，再由 `Command(resume=...)` 恢复？
3. 为什么客户端 `approved=true`、模型说“已授权”或 Skill 指令都不能授权？
4. 为什么只读 timeout 可能改路，而副作用 timeout 必须停止？
5. 新 Runtime 实例恢复和操作系统进程重启有什么本质差别？
6. 多 Agent 比单 Agent 多了哪些调用、预算和失败面，什么证据才值得采用？
7. 给出一个真实故障，并按固定排查顺序说出第一项检查和安全终态。

复述合格标准：语言简单，能画出三张状态图，包含一个审批工作案例、两个副作用边界和两个未验证边界。若把 checkpoint 说成事件日志、把内存换实例说成真重启、或把多 Agent 数量说成质量，必须重述。

## M10 与 30 项大纲映射

完整目标见[30 个主题映射](../syllabus-map.md)。M10 直接补齐 11、14、15、18，并为 13、24、26 提供关联证据：

| 编号 | 主题 | M10 产物 | 当前证据与边界 |
| --- | --- | --- | --- |
| 11 | LangGraph | checkpoint、interrupt/Command、重规划和故障恢复 | E3 同进程；PostgreSQL 真重启留 M11 |
| 13 | Agent Harness | 可信 context、取消、预算、稳定错误和 side-effect stop | 显式 Runtime 纵切；默认 Container 迁移留后续任务 |
| 14 | 多 Agent 协同 | 真实 manager-as-tools 与同工具单 Agent 对照 | E2/E3 离线 fixture；真实模型质量未验证 |
| 15 | Workflow 编排 | Run 生命周期、条件路由、暂停、恢复和有界重规划 | E3；跨进程一致性未验证 |
| 18 | 任务推理策略 | 结构化 plan、diagnose、replan、循环/预算停止 | 确定性 planner/executor；真实模型规划质量未验证 |
| 24 | 自动化测试 | checkpoint、审批、重规划、多 Agent 与 10 场景故障矩阵 | 默认离线；生产故障和跨平台未覆盖 |
| 26 | 安全治理与权限 | owner thread、服务端审批、单次 grant、副作用禁重放 | 同进程 E3；持久幂等和审计留 M11/M13 |

## M10 最终验收清单

- [ ] 能画出 Run 审批生命周期、有界重规划图和恢复决策图，并解释每个终态。
- [ ] 能独立运行 checkpoint、审批、重规划、故障专项和多 Agent 对照。
- [ ] 能区分 checkpoint、EventStore、ApprovalStore 和 ToolRegistry 的职责与敏感数据边界。
- [ ] 能演示暂停、approve/reject、重复 resume、同进程换 Runtime 实例恢复和 waiting 取消。
- [ ] 能证明只读 timeout 只在失败三重门、非副作用限制和剩余预算均满足时改路，副作用结果未知时绝不自动重放。
- [ ] 能根据固定质量、失败率、调用量、延迟和复杂度解释为何当前保留单 Agent。
- [ ] 能运行 M10 聚焦集、`scripts/verify.ps1` 和连续性检查，并如实记录失败、跳过、警告和 E2/E3 边界。
- [ ] 概念、实操、场景题总分至少 80，且没有安全红线错误。
- [ ] 完成一页速查表使用练习和一次合格费曼复述。
- [ ] 能指出 M10 对 30 项大纲 11/14/15/18 的直接覆盖，以及 M11/M12/M13 的后续承接点。

完成上述课程条目可以验收 M10-T6 的材料；学习者个人完成情况只写 `../progress.md`，工程状态仍由连续性状态页和实际 verification 决定。

## 官方资源

- LangGraph Persistence：<https://docs.langchain.com/oss/python/langgraph/persistence>
- LangGraph Interrupts：<https://docs.langchain.com/oss/python/langgraph/interrupts>
- OpenAI Agent orchestration：<https://openai.github.io/openai-agents-python/agents/#multi-agent-system-design-patterns>
