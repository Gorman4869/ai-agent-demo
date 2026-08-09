# M11-T4 交接：可信 Runtime Context Identity

- 日期：2026-08-09，Asia/Shanghai
- 当前任务：`M11-T4 / in_progress`
- 内部步骤：第四离线纵切完成；默认 Container 接线与持久 source async 边界尚未完成
- 任务等级：A 类身份与跨模块共享 RuntimeRequest 合同；时间盒 2–4 小时
- 验证基线：`93abc08`（`feat: add context-aware runtime adapter`）
- 工作区验证：`V-20260809-014/015`
- 关联决策：`ADR-0026`、`ADR-0025`、`ADR-0010`、`ADR-0013`
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- Agent Runtime 层新增冻结、repr-safe `RuntimeContextIdentity(owner_id, session_id)`；它作为 RuntimeRequest 末尾可选字段保持旧直接调用兼容，并在与 checkpoint 共存时校验 owner 一致。
- RunCoordinator 的 execute 与 approval resume 共用路径只从当前 owned RunRecord 构造 identity，不从 input、tool arguments、execution principal、模型结果或 run ID 推导 scope。
- 新增具体 `RuntimeIdentityBindingFactory`，只映射受信 identity 与应用固定 system constraints；缺失身份经 ContextAwareRuntime 稳定失败且不调用 delegate。
- 已完成 `RunCoordinator -> ContextAwareRuntime -> ConversationMemory/Knowledge/Skill collector -> ContextAssembler -> AgentRuntime delegate` 的真实进程内纵切。

## 验证摘要

- 恢复第三纵切相关 108 项、M1 10 项和连续性 52/102 通过；HEAD `93abc08` 与上一 handoff 一致。
- 新增 7 个关键测试方法或等价覆盖；最终专项 57 项、共享相关回归 175 项和 M1 隔离 10 项通过。
- 因修改共享 RuntimeRequest 合同，完整离线门已执行：后端 542 项通过、1 项既有 Windows symlink 能力跳过；受控 Code Agent、依赖、Vue、MCP TypeScript 与 Compose 配置通过。
- 首次沙箱内完整门仅因 Vue 无法写 tsbuildinfo 返回 TS5033/EPERM；同一命令经授权在沙箱外退出 0。只有后者计为完整门成功。

## 修改文件

- 实现与导出：`backend/app/agent/runtime.py`、`backend/app/agent/__init__.py`、`backend/app/services/run_coordinator.py`、`backend/app/context/runtime.py`、`backend/app/context/__init__.py`
- 测试：`backend/tests/test_runtime_contract.py`、`backend/tests/test_run_coordinator.py`、`backend/tests/test_context_runtime.py`
- 决策、规约与计划：`docs/continuity/decisions/ADR-0026-trusted-runtime-context-identity.md`、`BACKEND_CODING_STANDARDS.md`、`docs/implementation-plan.md`
- 连续性：`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff
- 没有修改 Container、Store、数据库、依赖、Settings、前端、HTTP 或跨前后端接口。
- handoff 写入时上述文件均为本轮未提交改动，没有发现任务外改动。最终本地提交由结束时 `git log` 确认，下一份 verification/handoff 再记录新 HEAD。

## 复审修正与失败尝试

- 恢复窗口中的首次完整门进程句柄失效，无法取得退出码，因此未计入证据；确认没有 Python/pytest/node 测试子进程后重跑。
- 可追溯的首次完整门后端 542 项通过，但 Vue 因沙箱禁止写 `tsconfig.app.tsbuildinfo` 返回 EPERM；没有修改代码规避，按授权在沙箱外重跑同一命令后完整通过。
- 新增真实 Coordinator Context 纵切首次使用晚于既有固定 Coordinator clock 的 `created_at`，触发正确的时间倒退保护；修正测试 fixture 为过去时间，生产逻辑不变。
- 初始把任务等级口头标为 C；按 playbook 重新核对后更正为 A 类，因为这是身份与跨模块公共契约变化，外部依赖/授权门才属于 C 类。

## 未验证范围

- 默认 Container 尚未采用 ContextAwareRuntime，当前只证明显式组合；不能描述成默认 Agent 或统一 Run 主链。
- 同步 collector 仅使用进程内 Memory/Knowledge/Skill。不得把 PostgreSQL Memory/pgvector 同步调用放入 async Runtime；持久 source 仍需要适当 async 边界。
- ContextAwareRuntime 只有 `run()`；现有 approval resume 的身份传播由 Coordinator 对 resumable delegate 合同证明，Context 在 resume 时重新收集还是冻结尚未决定或验证。
- delegate 是确定性测试替身；没有真实模型回答质量、在线提示遵循、Provider Token/usage、费用或账单证据。
- `ceil(bytes / 4)` 仍只是离线预算估算；`KI-018` 保持 open。

## 下一条原子动作

继续 `M11-T4` 第五个纵切，只迁移默认进程内 Container Context composition：

- 先调整默认依赖构造顺序，让默认 Runtime 可获得同一 Container 的进程内 MemoryStore、KnowledgeBase、SkillContextBuilder 和应用 system constraints；用单一 ContextAwareRuntime 替换默认 SkillAwareRuntime 包装，不能叠加两个 prompt_context owner。
- 保持显式 caller-supplied Runtime mapping 完全不变；默认 Manual/LangGraph/SDK Runtime 的结果、事件、安全工具、离线设置与 repr 合同必须回归。
- 覆盖默认 Container→Coordinator→ContextAwareRuntime→真实进程内 source→delegate 的纵切、无匹配 Skill、已有 Context 失败、owner/session 隔离和应用 lifecycle。
- 本纵切不接 PostgreSQL/pgvector context source，不决定 M11-T5 写入语义，不运行在线 Provider，不扩大到 M11-T5/M11-T6。

## 恢复命令

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_runtime_contract backend.tests.test_context_runtime backend.tests.test_run_coordinator backend.tests.test_run_coordinator_quiesce backend.tests.test_skill_context backend.tests.test_langgraph_approval_resume backend.tests.test_langgraph_checkpointing backend.tests.test_langgraph_recovery_faults backend.tests.test_runtime_comparison backend.tests.test_framework_runtimes backend.tests.test_openai_agents_runtime backend.tests.test_container backend.tests.test_postgres_execution -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

本轮相关 175 项、M1 10 项和完整离线门已通过；连续性预期为 52 个稳定任务/104 个 Markdown。恢复一致后不要重做 M11-T1–T3 或 M11-T4 前四纵切，下一步只接默认进程内 Container Context runtime；未经新授权不安装依赖、不读取 Key、不执行在线/付费调用、不配置或推送远程 Git。
