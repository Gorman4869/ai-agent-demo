# M10-T3 交接：有界动态计划与失败重规划

- 日期：2026-07-22，Asia/Shanghai
- 完成任务：`M10-T3`
- 完成状态：`verified`
- 下一任务：`M10-T4 / planned`
- 验证基线 HEAD：`545d5af`
- M10-T3 实现提交：`e27a8ef`
- 验证记录：`V-20260722-001`、`V-20260722-002`
- 关联决策：`ADR-0013`
- 分支：`main`
- 任务等级：A 类 checkpoint、错误分类与副作用禁重放边界，时间盒 2–4 小时
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 新增显式导入的 `ReplanningLangGraphRuntime`，真实执行 `plan -> execute -> diagnose -> replan` StateGraph，并通过现有 `AgentRuntime` 进入可注入的 durable Coordinator Run。
2. 新增 `PlanStep`、`TaskPlan`、`PlanContext`、`PlanStepResult` 和 planner/executor Protocol；operation、完成步骤、revision、预算、失败和计划签名进入版本化 checkpoint，原始请求、参数和中间输出不进入。
3. 重规划需要 retryable、服务端错误码白名单和安全 category 三重允许；auth、validation、approval、security、storage、cancellation 和副作用步骤全部停止。
4. 分离实际 step 调用预算与 replan 预算；替换计划必须适配剩余预算，相同 operation 路径即使换 ID 也判循环。
5. 新计划不能重复已完成 step ID 或已完成副作用 operation；approval step 在 executor 前阻断，planner 标记不作为工具授权。
6. 同进程共享 saver 时终态直接重放；外部取消打断的只读 pending step 可由新 Runtime 实例恢复；结果未知副作用返回安全失败和停止事件，不再次调用 executor。
7. 新增 14 项风险驱动测试，覆盖成功、白名单改路、永久错误、预算、循环、取消、审批、副作用完成/失败/结果未知、终态重放、脱敏和 Coordinator/EventStore 纵切。
8. 新增 `ADR-0013`、后端规约第 21 节、实施结果和 Stage 10 跟练说明；`KI-005` 更新为 mitigated。

## 本次修改文件

- `backend/app/agent/replanning_runtime.py`
- `backend/tests/test_langgraph_replanning.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/stages/10-durable-langgraph.md`
- `docs/continuity/decisions/ADR-0013-bounded-langgraph-replanning.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-07-22-m10-t3-bounded-replanning.md`

## 实际验证

- 恢复检查：M10-T2 handoff 的审批/Store 42 项、M1 7 项和连续性 52/66 通过，起始代码与记录无漂移。
- 新专项最终 14 项通过；真实 StateGraph、共享 `InMemorySaver`、`RunCoordinator`、EventStore 和 terminal Run 均被执行，无 ResourceWarning。
- 最终定向 124 项通过，覆盖重规划、checkpoint、审批、Coordinator、Runtime、工具安全、Store、Skill 和旧框架实验。
- M1 隔离：禁用 `site-packages` 的手写 Loop 7 项通过；新模块未从 `backend.app.agent` 顶层导出。
- 连续性在新增 ADR 后为 52 个稳定任务/67 个 Markdown；加入本 handoff 后重跑为 52/68，通过。
- 所有证据均为本地离线 E3；没有网络、密钥、Provider 或费用。

## 失败尝试与复审修正

- 首个 `git status` 使用本轮不可用的旧工具名，命令未执行；切换到可用 shell 工具后按原顺序重跑。
- AGENTS 首次默认编码乱码，显式 UTF-8 后正确读取；ADR、领域文件和 formatter 搜索各有一次猜测路径或 Windows wildcard 失败，均按实际清单/符号修正。
- 79 项定向首轮有 1 项既有毫秒级 deadline 用例偶发读到 Runtime 已调用；单用例、Coordinator 19 项和相同 79 项组合重跑全部通过，没有修改生产 Coordinator 或放宽测试。
- 首轮 12 项专项后，聚焦复审补齐冻结 `PlanContext`、`auth` category、已完成副作用换 ID 禁重放、checkpoint 交叉状态校验和 Coordinator/EventStore 纵切，最终专项 14 项、定向 124 项通过。

## 警告与未验证范围

- planner/executor 使用确定性 fixture；没有真实模型规划质量、Provider、Token、费用、在线延迟或容量证据。
- `InMemorySaver` 只证明同进程恢复。pending 副作用 fail closed 只证明不自动重放，不等于跨崩溃恰好一次；持久 ToolExecution、lease 和结果仲裁属于 M10-T5/M11。
- PlanStep 的副作用/审批元数据不是授权来源；真实工具仍必须经过 `ToolRegistry` 与 M10-T2 审批。默认 Container、旧 HTTP/SSE 和 Agents SDK 未迁移。
- 未执行全仓 `scripts/verify.ps1`，原因是没有依赖、构建配置、默认组合根、前后端 API 或既有共享 Protocol 变化；实际风险由 124 项定向集覆盖。
- 没有实现 M10-T4 多 Agent 或 M10-T5 故障注入。

## 未提交改动

M10-T3 代码、测试、ADR、规约、阶段说明和首轮连续性记录已由本地实现提交 `e27a8ef` 固定。当前仅本 handoff、`status.md` 与 `verification-log.md` 的提交后恢复锚点尚未提交；没有任务外改动，没有安装依赖，没有远程 Git 操作。

## 下一条原子动作

开始 `M10-T4` 前，只读审阅实施计划 M10-T4、现有 Agents SDK 对 handoff 的 fail-closed 处理、LangGraph/ToolRegistry 角色和工具隔离，以及 M8-T4/M8-T5 的对照 fixture。先选择 manager-as-tools 或 handoff 中一种最小真实模式，固定独立角色指令/工具、调用预算和单 Agent 对照指标；没有明确收益时保留单 Agent，不提前进入 M10-T5。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_replanning -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期重规划专项 14 项、M1 手写 Loop 7 项通过且无 ResourceWarning，连续性为 52 个稳定任务/68 个 Markdown。若一致，不要重做 M10-T3，直接进入 M10-T4 只读方案核对。没有用户新的单次授权，不得读取 Key 或执行真实模型。
