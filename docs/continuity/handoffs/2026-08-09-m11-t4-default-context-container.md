# M11-T4 交接：默认内存 Container Context 验收

- 日期：2026-08-09，Asia/Shanghai
- 完成任务：`M11-T4 / verified`
- 当前任务：`M11-T5 / planned`
- 内部步骤：M11-T4 第五离线纵切与任务验收完成；持久 Context/read-write 由 M11-T5 承接
- 任务等级：A 类默认 composition 与跨模块行为迁移；时间盒 2–4 小时
- 验证基线：`c7971d6`（`feat: bind trusted runtime context identity`）
- 工作区验证：`V-20260809-016/017`
- 关联决策：`ADR-0010`、`ADR-0025`、`ADR-0026`；本轮按既有决策实施，没有新增 ADR
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- 默认内存 `ApplicationContainer.create()` 先解析同一 MemoryStore/KnowledgeBase，再共享一个 SkillContextBuilder、ContextSourceCollector、RuntimeIdentityBindingFactory 和固定应用 system constraint。
- 内建 Manual/LangGraph/SDK Runtime 只包一层 ContextAwareRuntime，不再叠加 SkillAwareRuntime；显式 caller-supplied Runtime mapping 原对象保留。
- 默认 PostgreSQL `ApplicationContainer.open()` 仍保留 SkillAwareRuntime，没有把同步 PostgreSQL Memory 或 pgvector 接入 async Context path。
- 默认 Container→Coordinator→ContextAwareRuntime→system/Skill/approved Memory/recent/RAG→ManualRuntime 的真实离线纵切已执行；默认 LangGraph 工具结果与事件也通过。
- M11-T4 的长历史、关键 fact、预算、summary unavailable、RAG trust、可信身份、不同用户隔离、可解释报告和默认内存主链验收满足，任务更新为 verified。

## 验证摘要

- 恢复第四纵切相关 175 项、M1 10 项和连续性 52/104 通过；HEAD `c7971d6` 与上一 handoff 一致。
- 新增 5 个关键测试方法并收紧既有 Container 覆盖；最终 Container 专项 22 项、相关回归 244 项和 M1 隔离 10 项通过。
- 完整离线门最终后端 547 项通过、1 项既有 Windows symlink 能力跳过；Code Agent、依赖、Vue、MCP TypeScript 与 Compose 配置通过。
- 首次沙箱内完整门仅因 Vue tsbuildinfo 写入 TS5033/EPERM 退出 1；同一命令经授权在沙箱外退出 0，只有后者计为完整门成功。

## 修改文件

- 实现：`backend/app/container.py`
- 测试：`backend/tests/test_container.py`
- 规约与计划：`BACKEND_CODING_STANDARDS.md`、`docs/implementation-plan.md`
- 连续性：`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff
- 没有修改 Context/Runtime/Store 公共协议、数据库、Settings、依赖、前端、HTTP 或跨前后端接口。
- handoff 写入时上述文件均为本轮未提交改动，没有发现任务外改动。最终本地提交由结束时 `git log` 确认，下一份 verification/handoff 再记录新 HEAD。

## 聚焦复审与失败尝试

- 读取关联 ADR 时两次按推测文件名定位失败，随后用 `rg --files` 找到实际 ADR-0010/0013/0024 文件；另一次 `rg` 包含不存在的可选目录而退出 1。均为只读路径错误，不是代码/记录漂移。
- 首次完整门后端 547 项通过，但 Vue 因沙箱禁止写 `tsconfig.app.tsbuildinfo` 返回 EPERM；没有改代码绕过，按授权在沙箱外重跑同一命令后完整通过。
- 聚焦复审确认只修改 memory create path；PostgreSQL open 不接同步 source，显式 Runtime 不包装。测试中的真实 Manual Loop 引用改为模块级别名并补默认 LangGraph 工具纵切，修正后 Container 22 项与相关 244 项通过。
- 没有业务测试失败、依赖安装、数据库操作、在线调用或范围扩张。

## 未验证范围

- PostgreSQL Memory/pgvector 尚未进入 Context；M11-T5 需先使用现有 AsyncMemoryStore 设计可取消、有界的 async source，不能直接复用同步 collector。
- 当前主 Context 只读取已有 in-memory message/fact；Run 本身没有写入用户/assistant 消息，也没有纠正/删除后的 Run、版本冲突或审计语义。
- 默认 SDK Runtime 只完成离线延迟构造和既有 MockTransport/协议回归，没有真实 Provider、模型质量、Token/usage、费用或账单证据。
- Context summary 仍显式 unavailable；固定 RAG 指标、线上 Embedding 冒烟、统一 durable HTTP/UI 和生产部署分别属于 M11-T6/M11-T7/M12/M13。

## 下一条原子动作

开始 `M11-T5` 第一个离线纵切，只固定 async Context Memory 读取边界：

- 设计并实现一个不扩宽现有同步 MemoryStore 的异步 source seam，复用 `AsyncMemoryStore.messages()`/`facts()`；Context query、Knowledge 与 Skill 的同步内存部分保持可测试，PostgreSQL 同步适配器不得在事件循环调用。
- 先覆盖 AsyncLocalMemoryStore 的真实 Context 读取、owner/session 隔离、source 错误、取消与 timeout；若需要改变 ContextAwareRuntime/collector 公共协议，新增 ADR 并按共享契约触发风险回归。
- 默认 memory Container 行为保持；默认 PostgreSQL Container 只有在 async seam 验证后才接 Context。显式 Runtime mapping 继续不包装。
- 本原子不写入 Run 消息、不实现纠正/删除、版本冲突/审计、不运行真实 PostgreSQL/在线 Provider，也不进入 M11-T6。

## 恢复命令

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_container backend.tests.test_context_runtime backend.tests.test_context_collector backend.tests.test_context_assembler backend.tests.test_skill_context backend.tests.test_runtime_contract backend.tests.test_runtime_comparison backend.tests.test_framework_runtimes backend.tests.test_openai_agents_runtime backend.tests.test_run_coordinator backend.tests.test_run_coordinator_quiesce backend.tests.test_application_lifecycle backend.tests.test_api backend.tests.test_mcp_client_lifecycle backend.tests.test_memory backend.tests.test_memory_store_contract backend.tests.test_rag backend.tests.test_research_workflow backend.tests.test_settings backend.tests.test_postgres_execution -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

本轮相关 244 项、M1 10 项和完整离线门已通过；连续性预期为 52 个稳定任务/105 个 Markdown。恢复一致后不要重做 M11-T1–T4，下一步只固定 async Context Memory 读取边界；未经新授权不安装依赖、不读取 Key、不执行在线/付费调用、不运行真实数据库、不配置或推送远程 Git。
