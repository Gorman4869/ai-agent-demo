# M10-T2 交接：服务端审批 Interrupt 与 Resume

- 日期：2026-07-20，Asia/Shanghai
- 完成任务：`M10-T2`
- 完成状态：`verified`
- 下一任务：`M10-T3 / planned`
- 验证基线 HEAD：`cdc9436`
- M10-T2 实现提交：待本地提交固定
- 验证记录：`V-20260720-013`
- 关联决策：`ADR-0012`
- 分支：`main`
- 任务等级：A 类共享 Runtime/EventStore/Coordinator 契约变更，时间盒 2–4 小时
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 保留 `RuntimeResult` 终态不变量，新增 `RuntimeApprovalPause`、`RuntimeApprovalResume`、`RuntimeOutcome` 与 `ApprovalResumableRuntime`。
2. 扩展 `InMemoryApprovalStore`：ApprovalRequest 绑定 Run、principal、tool call、tool name 与规范参数摘要；决议只接受 approve/reject，服务端判定过期，批准后生成精确单次 grant。
3. 新增显式导入的 `ApprovalLangGraphRuntime`，真实执行 `prepare -> interrupt() -> Command(resume=...) -> execute`。prepare 先固定调用，恢复不会重新运行 planner。
4. 原始工具参数只保留在服务端私有内存，checkpoint/事件只保存审批 ID、稳定工具标识、摘要与过期时间；恢复执行仍经过共享 `ToolRegistry` 的角色、审批、Schema 和单次消费。
5. `EventStore` 增加 `PauseCommit`/`ResumeCommit`，原子提交 `running -> waiting_approval + run.waiting_approval` 与 `waiting_approval -> running + run.resumed`；普通 append 无法伪造这些生命周期事件。
6. Coordinator 新增 `resume_approval()`；只有 resume commit 赢家调用 Runtime，其他并发 Coordinator 等待持久终态。等待审批 Run 可以取消。
7. 新增 9 项审批专项及 Store 合同/故障覆盖，证明批准、拒绝、过期、篡改、裸布尔 decision、并发重复、单次消费、脱敏、新 Runtime 实例恢复和等待取消。
8. 新增 `ADR-0012`、后端规约第 20 节、阶段 10 纵切说明和实施结果；`KI-004` 继续为 mitigated，未把内存恢复写成进程重启。

## 本次修改文件

- `backend/app/agent/runtime.py`
- `backend/app/agent/approval_runtime.py`
- `backend/app/agent/__init__.py`
- `backend/app/services/run_coordinator.py`
- `backend/app/stores/base.py`
- `backend/app/stores/memory.py`
- `backend/app/stores/__init__.py`
- `backend/app/tools/registry.py`
- `backend/app/tools/__init__.py`
- `backend/tests/test_langgraph_approval_resume.py`
- `backend/tests/test_run_store_contract.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/stages/10-durable-langgraph.md`
- `docs/continuity/decisions/ADR-0012-server-bound-approval-resume.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/handoffs/2026-07-20-m10-t2-approval-resume.md`

## 实际验证

- 恢复检查：M10-T1 handoff 的 Checkpoint/Skill 20 项、M1 7 项和连续性检查通过，起始代码与记录无漂移。
- 审批/Store 专项最终 42 项通过；定向审批、Store、工具安全、Coordinator 与 checkpoint 回归 85 项通过，无 ResourceWarning。
- M1 隔离：修复顶层导入后，禁用 `site-packages` 的手写 Loop 7 项通过。
- 统一全量沙箱首轮：后端 315 项通过、1 项既有 Windows symlink 条件跳过；Code Agent Demo 和依赖门通过，Vue 因沙箱拒绝写 `tsconfig.app.tsbuildinfo` 以 `EPERM` 退出 1。
- 统一全量受控重跑：相同离线脚本经批准在沙箱外退出 0；Vue 18 模块 production build、MCP TypeScript build 和 Docker Compose 配置门全部通过。
- 提交前通知竞态补丁后再次全量：后端 316 项通过、1 项既有 symlink 跳过，Code Agent Demo、依赖、Vue、MCP TypeScript 与 Compose 门继续通过。
- 普通 Runtime 上下文兼容性收口后最终再次全量，结果仍为后端 316 项通过、1 项既有 symlink 跳过，其余门全部通过。
- 最终恢复：审批/Store 42 项、M1 7 项、52 个稳定任务/66 个 Markdown 通过，无 ResourceWarning。
- 所有证据均为本地离线 E3；没有网络、密钥、Provider 或费用。

## 失败尝试与设计修正

- 两个最初的内联 LangGraph API 探针被 PowerShell 引号破坏并产生 SyntaxError；改用临时完整脚本执行后删除，最终结论由自动化测试固定。
- 一次读取不存在的 `agent/base.py` 和一次 Windows wildcard 搜索失败；随后按 `rg --files` 与真实路径继续。
- 首个运行时补丁因错误导入上下文被 `apply_patch` 整体拒绝；一个 `__all__` 小补丁落位错误，立即只读检查并修复，未进入测试。
- PATH 的 WindowsApps `python.exe` 无法启动；仓库 `.venv` 可用。一次 `py_compile` 又被沙箱拒绝写 pyc，后续统一使用 `.venv -B`，没有改系统配置。
- 首轮 40 项专项有 1 项跨 Coordinator 重复 resume 失败：后到者在赢家已提交 running 后报非法转换。修复为等待持久终态后 40/40，通过新增故障用例后最终 41/41。
- 初版从 `backend.app.agent` 顶层导出审批 Runtime，导致 M1 `python -S` 找不到 LangGraph。移除第三方模块顶层导出后 M1 7 项恢复通过。
- 提交前审查发现 waiting 通知已发出但 execute task 尚未退出时，立即 resume 会误共享旧 task。active task 增加 execute/resume 阶段标记，resume 等待旧 task 收尾后自动继续；新增通知窗口用例并重跑专项、定向和全量。
- 全量首轮因沙箱写权限失败；保留退出 1，经批准重跑相同脚本通过，没有改代码或依赖规避门禁。

## 警告与未验证范围

- `InMemorySaver`、ApprovalStore、私有参数、RunStore 和 EventStore 都只存在于当前进程。跨 Runtime/Coordinator 实例恢复不等于操作系统进程重启。
- 并发正常恢复和重复消费证明 handler 最多执行一次；进程在副作用发生后、terminal commit 结果未知前退出的情形尚未证明恰好一次，归 M10-T5/M11。
- 没有持久 ToolExecution、lease、恢复扫描、PostgreSQL、多进程事务、checkpoint/参数加密、容量或清理策略。
- 新 Runtime 只通过显式组合使用；默认 Container、旧 HTTP/SSE 和 Agents SDK 审批暂停未迁移，HTTP 审批端点属于 M12。
- 没有实现 M10-T3 动态重规划或 M10-T4 多 Agent，也没有真实 Provider 在线验证。
- 全量仍有 1 项既有 Code Agent Windows symlink 能力测试跳过；Starlette/httpx 弃用提示、notifier 负向日志和 Windows asyncio 调试输出不影响退出码。

## 未提交改动

M10-T2 代码、测试、ADR、规约、阶段说明和连续性记录仍在工作区，尚未创建本地实现提交。没有任务外改动，没有安装依赖，没有远程 Git 操作。提交时只包含本 handoff“本次修改文件”列出的 M10-T2 文件；提交后再追加恢复锚点记录固定新 HEAD。

## 下一条原子动作

开始 `M10-T3` 前，只读审阅实施计划 M10-T3、现有 graph state、失败分类、ToolResult/RunFailure 和计划节点。先固定动态计划 Schema、可重规划错误白名单、最大重规划次数与不应重试的权限/审批/副作用错误；不要提前实现 M10-T4 多 Agent，也不要为重规划自动重放副作用节点。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_approval_resume backend.tests.test_run_store_contract -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期审批/Store 共 42 项、M1 手写 Loop 7 项通过且无 ResourceWarning，连续性任务数保持 52；Markdown 数量以新增 ADR 与 handoff 后脚本实际输出为准。若一致，不要重做 M10-T2，直接进入 M10-T3 只读设计核对。没有用户新的单次授权，不得读取 Key 或执行真实模型。
