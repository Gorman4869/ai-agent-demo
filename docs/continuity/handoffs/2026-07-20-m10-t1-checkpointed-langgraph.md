# M10-T1 交接：版本化 LangGraph Checkpoint 纵切

- 日期：2026-07-20，Asia/Shanghai
- 完成任务：`M10-T1`
- 完成状态：`verified`
- 下一任务：`M10-T2 / planned`
- 验证基线 HEAD：`c4d4efe`
- M10-T1 实现提交：`b6dfa0b`
- 验证记录：`V-20260720-011`、`V-20260720-012`
- 关联决策：`ADR-0011`
- 分支：`main`
- 任务等级：A 类共享 Runtime/Coordinator 契约变更，时间盒 2–4 小时
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 新增 `RuntimeCheckpointContext`，由 Coordinator 使用持久 Run 的可信 owner/run 派生版本化 owner scope 与 thread 摘要；原始 owner 不进入 Runtime 请求上下文，错 Run 绑定在构造时拒绝。
2. 新增独立 `CheckpointedLangGraphRuntime`，持有共享 `InMemorySaver` 并编译真实 `StateGraph`，不改写现有简单 `LangGraphRuntime`。
3. 固定 `state_version=1`、owner scope、invocation count 和标准化 RuntimeResult state；请求、Skill prompt、事件 sink、控制信号和 delegate 只走瞬时 `context_schema`。
4. 执行前校验已有 checkpoint；未知版本、错 owner、损坏 state 和存储不可用返回稳定失败。当前迁移边界是拒绝所有非当前版本，不做隐式升级。
5. 把 side-effect-free `advance` 与 delegate 拆成两个节点。delegate 节点失败时前一 superstep 保留，可由同 thread 下一次调用恢复；普通异常不泄漏原文，也不触发自动重试。
6. `StoreError` 与外层取消维持既有传播语义。新模块保持显式导入，`backend.app.agent` 顶层和 M1 `python -S` 路径不依赖 LangGraph。
7. 新增 10 项关键测试，覆盖稳定线程、跨 Runtime 恢复、用户隔离、缺失 thread、节点失败、版本/作用域拒绝、敏感上下文不入 checkpoint、真实 LangGraph 工具链和 Coordinator 注入。
8. 补充 `ADR-0011`、后端编码规约第 19 节、阶段 10 的已验证纵切说明，并把 `KI-004` 从 open 降为 mitigated；没有提前实现 interrupt/resume。

## 本次修改文件

- `backend/app/agent/runtime.py`
- `backend/app/agent/checkpoint_runtime.py`
- `backend/app/agent/__init__.py`
- `backend/app/services/run_coordinator.py`
- `backend/tests/test_langgraph_checkpointing.py`
- `backend/tests/test_skill_context.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/stages/10-durable-langgraph.md`
- `docs/continuity/decisions/ADR-0011-versioned-langgraph-checkpoint-context.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/handoffs/2026-07-20-m10-t1-checkpointed-langgraph.md`

## 实际验证

- handoff 恢复：M9 TypeScript build、40 项聚焦、固定 Skill 评测 2/2 与 52 个稳定任务/62 个 Markdown 通过，代码和记录无漂移。
- 新增专项：10 项全部通过，真实执行外层 checkpoint graph 的 `ainvoke()`，再由现有 LangGraph Runtime 完成 Mock tool loop；不是 import 或对象构造证据。
- 定向回归：Checkpoint、Runtime、Coordinator、三 Runtime 对照、Skill、框架与 Container 共 73 项通过，无 ResourceWarning。
- M1 隔离：禁用 `site-packages` 后手写 Loop 7 项和 Demo 都通过，证明新模块没有进入标准库学习路径的顶层导入。
- 全量沙箱首轮：后端 304 项中 303 项通过、1 项既有 Windows symlink 能力跳过；Code Agent Demo 与 `pip check` 通过，Vue 因 `tsbuildinfo` 写权限 `EPERM` 使脚本退出 1。
- 全量受控重跑：同一离线脚本经批准在沙箱外退出 0；后端结果一致，Vue、MCP TypeScript 与 Compose 配置门全部通过。

## 失败尝试与设计修正

- 首次大补丁因猜错 `run_coordinator.py` 导入上下文而整体未落盘；确认工作区仍干净后拆成小补丁，没有覆盖既有修改。
- 首次测试命令通过 PATH 命中 WindowsApps `python.exe`，报“指定的登录会话不存在”；改用仓库 `.venv` 后通过，没有修改全局 PATH。
- 首个 LangGraph 探针设置 `checkpoint_ns="m10"`，顶层 `aget_state()` 报 `Subgraph m10 not found`；实现改为只使用服务端派生 `thread_id`。
- 一个早期 context 探针把 secret 同时写入 answer，不能证明 secret 来源；判为无效证据，改用固定安全 answer 后确认 context 未进入 checkpoint。
- 无 entrypoint 的只读图探针报 `Graph must have an entrypoint`；没有把该失败当成 API 结论，最终由有完整图结构的自动化测试取代。
- 初版计划把 checkpoint Runtime 从 `backend.app.agent` 顶层导出；审查既有 M1 隔离门后撤销该导出并实际重跑 `python -S`。
- 初版 checkpoint context 暂存原始 owner；diff 审查后改为只保存 owner/thread 摘要，并重跑相关测试。
- 全量首轮因沙箱拒绝 Vue build info 写入而失败；保留退出 1，获批后重跑相同完整脚本通过，没有改代码、依赖或系统策略。

## 警告与未验证范围

- `InMemorySaver` 只证明同一进程、共享对象、跨 invocation 恢复；进程退出后状态丢失。没有 PostgreSQL、进程重启、多进程一致性、加密、容量或清理策略证据。
- 没有实现 interrupt、`Command(resume=...)`、审批请求、拒绝/过期/篡改/重复 resume 或副作用恰好一次；`KI-004` 只是 mitigated。
- 没有验证同一 thread 的跨进程并发写。单进程内仍由 Coordinator singleflight 避免重复执行；checkpoint 结果未知时 Runtime 不自动重试副作用 delegate。
- 新 checkpoint Runtime 只可通过显式组合使用，尚未成为 Container 默认 Runtime。现有三 Runtime 对照和旧 API 未迁移。
- 全量仍跳过 1 项既有 Code Agent Windows symlink 能力测试；Starlette/httpx 弃用提示、notifier 负向日志和 asyncio 调试诊断不影响退出码，没有安装提示中的依赖。
- 没有读取 Key、执行真实模型、访问网络或产生费用；真实 Provider 行为不属于本任务证据。

## 未提交改动

M10-T1 代码、测试、ADR、阶段说明和首轮连续性记录已提交为 `b6dfa0b`。提交后只修改 verification、status 与本 handoff 以固定实现提交和恢复证据；这些记录由后续本地文档提交闭环。没有任务外改动，也没有远程 Git 操作。

## 下一条原子动作

开始 `M10-T2` 前，只读审阅实施计划 M10-T2、现有 ToolApproval/ToolExecution/RuntimeResult/Coordinator 契约和已安装 LangGraph `interrupt()`、`Command(resume=...)` 公共 API。先固定服务端审批记录、resume payload、拒绝/过期/篡改/重复消费和 M10 内存恢复与 M11 进程重启的证据边界；不要提前实现 M10-T3 重规划。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_checkpointing backend.tests.test_skill_context -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 Checkpoint/Skill 共 20 项、M1 手写 Loop 7 项通过且无 ResourceWarning，连续性任务数保持 52；Markdown 数量以新增 ADR 与 handoff 后的脚本实际输出为准。若一致，不要重做 M10-T1，直接进入 M10-T2 只读设计核对。没有用户新的单次授权，不得读取 Key 或执行真实模型。
