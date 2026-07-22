# M10-T5 交接：恢复与故障注入

- 日期：2026-07-22，Asia/Shanghai
- 完成任务：`M10-T5`
- 完成状态：`verified`
- 下一任务：`M10-T6 / planned`
- 验证基线 HEAD：`7538fb4`
- M10-T5 实现提交：`1e332f3`
- 验证记录：`V-20260722-005`、`V-20260722-006`
- 分支：`main`
- 任务等级：A 类 checkpoint、审批副作用与恢复诊断边界，时间盒 2–4 小时
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 新增 10 项独立故障矩阵，覆盖 checkpoint 读取不可用/状态损坏、只读 pending step 中断恢复、只读工具 timeout 改路、审批等待换 Runtime 恢复/取消/丢 checkpoint，以及两条结果未知副作用路径。
2. 审批 handler 完成后若 checkpoint 写失败，单次 approval 已消费；后续 Runtime 将 `approval_already_consumed` 识别为结果未知，返回 `side_effect_resume_unsafe` 并发出 `approval.stopped`，绝不再次调用 handler。
3. 重规划 pending 副作用继续 fail closed：新 Runtime 返回 `side_effect_resume_unsafe`、发出 `plan.stopped` 且 executor 不重放；副作用步骤即使返回可重试 timeout 也不允许重规划。
4. 损坏 checkpoint 通过真实 Coordinator 形成 `run.failed`；只读 timeout 通过真实 EventStore 形成失败、replan、完成事件；审批等待取消不会执行工具。
5. 更新后端规约、实施计划、Stage 10、known issue、status 与 verification；`KI-004` 保持 mitigated，剩余缺口明确归 M11。

## 本次修改文件

- `backend/app/agent/approval_runtime.py`
- `backend/tests/test_langgraph_recovery_faults.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/stages/10-durable-langgraph.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-07-22-m10-t5-recovery-fault-injection.md`

## 实际验证

- 启动恢复：M10-T4 Demo 仍选择 single Agent；多 Agent专项 14 项、M1 7 项和连续性 52/69 通过，起始代码与记录无漂移。
- 新增故障专项最终 10 项通过，无 ResourceWarning。
- checkpoint、审批、重规划和故障专项合计 44 项通过。
- 最终 M10-T1–T5、Coordinator、Store、ToolRegistry 和 M10-T4 对照定向回归 123 项通过；三行 notifier 失败日志来自既有负向用例，命令退出 0。
- M1 隔离：禁用 `site-packages` 的手写 Loop 7 项通过；专用 LangGraph 模块仍未从 `backend.app.agent` 顶层导出。
- 连续性在本 handoff 加入后为 52 个稳定任务、70 个 Markdown，通过。
- 提交后恢复：实现提交 `1e332f3` 工作区干净；专项首次 10 项通过但出现一条 Windows asyncio 0.187 秒慢任务诊断，原命令复跑 10 项无诊断通过；M1 7 项和连续性 52/70 通过。
- 所有证据均为本地离线 E3；没有网络、密钥、Provider 或费用。

## 失败尝试与复审修正

- 两次只读搜索猜错测试文件名和 ADR 标题后缀，均用 `rg --files` 按实际结构纠正，没有据此修改结论。
- 新测试首轮因函数默认参数先于 `_approval_planner` 定义求值而导入失败；改为运行时解析默认 planner 后进入测试。
- 第二轮 10 项中 8 项通过、2 项夹具断言错误：终态事件实际字段为既有 `failure_code`；单次写故障未覆盖 LangGraph 后续写入，导致成功终态仍落盘。改为本 invocation 全程阻断 saver 写入、恢复前显式解除，最终真实保留结果未知窗口并 10 项通过。
- `git diff` 与 formatter 搜索的组合命令因仓库没有对应配置而退出 1；`git diff --check` 本身无 whitespace 错误，后续按实际 Python 测试和 diff 复审验收。

## 警告与未验证范围

- `_FailAfterEffectSaver` 是测试夹具，只在同一 Python 进程内阻断 checkpoint 写入。它证明恢复契约和副作用不重放，不是 PostgreSQL、操作系统进程崩溃或网络分区模拟器。
- approval 单次消费提供的是“不会重复执行”证据；如果消费后、handler 前退出，可能出现未执行，因此不能宣称跨崩溃 exactly-once。
- `InMemorySaver`、ApprovalStore、RunStore、EventStore 和私有参数仍会随进程退出丢失。持久 ToolExecution 结果、lease、恢复扫描、多进程仲裁和真正进程重启由 M11 实现。
- 没有修改默认 Container、HTTP/SSE、前端、公共 Runtime/Store Protocol、依赖、锁文件或构建配置；未运行 `scripts/verify.ps1`，M10-T6 里程碑验收再执行计划要求的完整门。
- 没有读取 Key、执行在线 Provider、计算真实费用或验证生产容量。

## 未提交改动

M10-T5 代码、测试、规约、课程和首轮连续性记录已由本地实现提交 `1e332f3` 固定。当前只修改本 handoff、`status.md` 与 `verification-log.md` 以记录提交后恢复锚点；没有任务外改动，没有安装依赖，没有远程 Git 操作。

## 下一条原子动作

开始 `M10-T6` 前，只读审阅 Stage 10、30 项大纲映射和 M10-T1–T5 verification，列出里程碑必须汇总的跟练步骤、真实工作映射、常见错误、概念/实操/场景题、一页速查表、费曼任务与完整验收命令。只做 M10 课程与里程碑验收，不提前实现 M11 PostgreSQL、记忆或 RAG。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_recovery_faults -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期故障专项 10 项、M1 7 项通过且无 ResourceWarning，连续性保持 52 个稳定任务、70 个 Markdown。若一致，不要重做 M10-T5，直接进入 M10-T6 只读验收清单。没有用户新的单次授权，不得读取 Key 或执行真实模型。
