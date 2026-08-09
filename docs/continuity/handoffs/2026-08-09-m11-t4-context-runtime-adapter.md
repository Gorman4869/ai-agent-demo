# M11-T4 交接：显式 Context-aware Runtime adapter

- 日期：2026-08-09，Asia/Shanghai
- 当前任务：`M11-T4 / in_progress`
- 内部步骤：第三离线纵切完成；可信 RunRecord 身份传播与默认 Container 接线尚未完成
- 任务等级：B 类显式 Runtime adapter；时间盒 30–90 分钟
- 验证基线：`c0e0b11`（`feat: collect bounded context sources`）
- 工作区验证：`V-20260809-012/013`
- 关联决策：`ADR-0025`、`ADR-0010`、`ADR-0013`
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- 新增 `RuntimeContextBinding`、`RuntimeContextBindingFactory`、`PreparedContextRequest`、`prepare_context_request()` 与 `ContextAwareRuntime`，并从 `backend.app.context` 显式导出。
- 可信 factory 只提供 owner/session/system constraints；query 在 adapter 内固定取原 `RuntimeRequest.input_text`。模型结果、工具参数和已有 prompt_context 不能提供 owner、session 或 policy。
- adapter 实际执行同步 collector→Assembler。非空结果用冻结复制只写 `prompt_context`，保留 run/input/execution/checkpoint 对象；空上下文把原请求对象交给 delegate。
- 已有 prompt 在 factory/source 前 fail closed；非法绑定、跨 owner、collection/assembly 预期错误统一为稳定无内容 `context_unavailable`，delegate 不执行。factory 程序错误继续传播。
- delegate 的 emit/control、terminal result 与 approval pause 原样透传，正常路径只委托一次。

## 验证摘要

- 恢复第二纵切相关 98 项、M1 10 项和连续性 52/101 通过；HEAD `c0e0b11` 与上一 handoff 一致。
- 新增 10 个关键测试方法；adapter 专项 10 项、最终 Context adapter/collector/Assembler/Runtime/Skill/Memory/RAG/M10-T3/Container 108 项和 M1 隔离 10 项通过。
- 真实 ConversationMemory、InMemoryKnowledgeBase 与 SkillContextBuilder 经 collector/Assembler 进入 delegate 的 RuntimeRequest；summary unavailable、跨 owner、空上下文、字段身份、脱敏和 approval pause 均有离线证据。
- 仅有既有 Starlette/httpx 弃用警告与 asyncio 慢任务诊断；没有测试失败或新增 skip。
- 没有修改现有 RuntimeRequest/AgentRuntime/Store/Container 公共协议、依赖、数据库、构建或跨前后端接口，因此未触发完整全仓门；见 `V-20260809-012/013`。

## 修改文件

- 实现与导出：`backend/app/context/runtime.py`、`backend/app/context/__init__.py`
- 测试：`backend/tests/test_context_runtime.py`
- 规约与计划：`BACKEND_CODING_STANDARDS.md`、`docs/implementation-plan.md`
- 连续性：`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff
- 没有修改 RuntimeRequest、AgentRuntime、SkillAwareRuntime、Container、RunCoordinator、MemoryStore、KnowledgeBase、SkillContextBuilder、数据库、依赖、前端或 HTTP 契约。
- handoff 写入时上述文件均为本轮未提交改动，没有发现任务外改动。最终本地提交由结束时 `git log` 确认，下一份 verification/handoff 再记录新 HEAD。

## 复审修正与失败尝试

- 首次误用 `.venv` 的 `pytest` 命令，因该环境没有 pytest 退出 1；没有安装依赖，改用项目既有 `unittest` 后专项 10 项与相关 108 项通过。
- 探索时两次按推测文件名读取不存在的 Skill Runtime/ToolExecution 模块，随后用 `rg --files` 定位实际 `test_skill_context.py` 与 `tools/registry.py`；不是代码或记录漂移。
- 一次聚合 diff/config 复核因可选 pyproject/setup/tox 文件不存在而返回 1；拆分检查后 `git diff --check`、导入搜索和未跟踪文件复核均正常。
- 聚焦自审把默认 assembler 的真值分支改为显式 None 分支，并将 binding factory 接收原请求的测试收紧为对象身份；修正后专项 10 项通过。

## 未验证范围

- ContextAwareRuntime 仍由显式 factory 注入静态/调用方绑定；RunCoordinator 尚未从 RunRecord 把真实 owner/session 传播到 RuntimeRequest，默认 Container 尚未接线，M11-T4 保持 `in_progress`。
- 当前同步调用链只使用 ConversationMemory、InMemoryKnowledgeBase、SkillContextBuilder 和确定性 summary result；没有执行 PostgreSQL Memory/pgvector、在线摘要或 Provider。
- 同步 collector 不得直接用于事件循环上的 PostgreSQL/pgvector。后续默认组合必须先确定可信 identity 和 async source 边界，不能把本轮描述为持久主链证据。
- Fake delegate 只证明 AgentRuntime 边界、单次调用和 outcome 透传，不证明真实模型回答质量、在线提示遵循或审批 resume 时的上下文刷新策略。
- `ceil(bytes / 4)` 仍不是 Provider tokenizer、usage、模型窗口或费用；`KI-018` 保持 open。

## 下一条原子动作

继续 `M11-T4` 第四个纵切，只固定 RunCoordinator→RuntimeRequest 的可信 context identity：

- 在 Agent Runtime 层定义不依赖 context 包的冻结、repr-safe owner/session identity；RunCoordinator 只能从当前 `RunRecord.owner_id/session_id` 构造并写入 RuntimeRequest。
- Context binding factory 从该 identity 映射 RuntimeContextBinding；禁止从 input_text、tool arguments、execution principal 或 run ID 猜测 session。原有 request 字段、checkpoint owner 绑定和 approval resume 路径必须保持兼容。
- 覆盖 execute/resume、owner/session 身份、repr 脱敏、字段保留、伪造/缺失身份和既有 Runtime 回归。该共享 RuntimeRequest 合同变化需要按触发条件运行完整离线门并记录真实结果。
- 本纵切仍不接默认 Container、不堆叠 SkillAwareRuntime 与 ContextAwareRuntime、不进入 PostgreSQL context source、M11-T5 或 M11-T6。

## 恢复命令

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_context_runtime backend.tests.test_context_collector backend.tests.test_context_assembler backend.tests.test_runtime_contract backend.tests.test_skill_context backend.tests.test_memory backend.tests.test_memory_store_contract backend.tests.test_rag backend.tests.test_research_workflow backend.tests.test_langgraph_replanning backend.tests.test_langgraph_checkpointing backend.tests.test_container -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

本轮相关定向 108 项、M1 10 项，以及连续性 52 个稳定任务/102 个 Markdown 已通过。恢复一致后不要重做 M11-T1–T3 或 M11-T4 前三纵切，下一步只固定可信 Runtime context identity；未经新授权不安装依赖、不读取 Key、不执行在线/付费调用、不配置或推送远程 Git。
