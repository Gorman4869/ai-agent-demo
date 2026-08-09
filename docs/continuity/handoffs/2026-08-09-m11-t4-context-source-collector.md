# M11-T4 交接：显式 Context source collector

- 日期：2026-08-09，Asia/Shanghai
- 当前任务：`M11-T4 / in_progress`
- 内部步骤：第二离线纵切完成；显式 Runtime request adapter 与默认 Container 接线尚未完成
- 任务等级：B 类确定性 source adapter；时间盒 30–90 分钟
- 验证基线：`9b052c2`（`feat: add bounded context assembler`）
- 工作区验证：`V-20260809-010/011`
- 关联决策：`ADR-0025`、`ADR-0010`、`ADR-0013`
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- 新增 `ContextCollectionInput`、`ContextSystemConstraint`、`ContextSummaryResult`、`ContextSummarizer`、`CollectedContext` 与 `ContextSourceCollector`，并从 `backend.app.context` 显式导出。
- Collector 实际调用现有同步 `MemoryStore.messages()`/`facts()`、`KnowledgeBase.search()` 与 `SkillContextBuilder.build()`；不修改这些协议，也不读取环境、Key 或默认 Container。
- fact owner 在查询 Knowledge/Skill 前逐条校验；任一跨 owner fact 以稳定无内容 `context_owner_mismatch` 失败，既不返回部分 fragments，也不继续下游查询。
- message/fact/citation/Skill 生成来源前缀加版本化 SHA-256 的安全 ID；recent ordinal 保留 Store 顺序，RAG ordinal 保留检索排名，owner/session/query/content 不进入 repr 或预算报告。
- summary 使用显式结果协议表达成功、无摘要或 unavailable，没有隐式模型调用；unavailable 只进入 Assembler 来源可用性，不拼回 Store 窗口外历史。
- `CollectedContext.assemble()` 固定使用收集时 owner 调用既有 Assembler，避免调用方把已收集片段重新绑定其他 owner。

## 验证摘要

- 恢复第一纵切相关 88 项、M1 10 项和连续性 52/100 通过；HEAD `9b052c2` 与上一 handoff 一致。
- 新增 10 个关键测试方法或等价覆盖；collector 专项 10 项、最终 Context collector/Assembler/Runtime/Skill/Memory/RAG/M10-T3/Container 98 项和 M1 隔离 10 项通过。
- 真实 `ConversationMemory`→collector→Assembler 长历史用例保留 approved fact 和最新两条 recent；真实 `InMemoryKnowledgeBase` 检索的注入文本仍是 `untrusted_evidence`；真实 `SkillContextBuilder` 结果进入 Skill fragment。
- 仅有既有 Starlette/httpx 弃用警告与 asyncio 慢任务诊断；没有失败或新增 skip。
- 没有修改既有 Store/Runtime/Container、依赖、数据库、构建或跨前后端接口，因此未触发完整全仓门；见 `V-20260809-010/011`。

## 修改文件

- 实现与导出：`backend/app/context/collector.py`、`backend/app/context/__init__.py`
- 测试：`backend/tests/test_context_collector.py`
- 规约与计划：`BACKEND_CODING_STANDARDS.md`、`docs/implementation-plan.md`
- 连续性：`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff
- 没有修改 ContextAssembler、RuntimeRequest、Runtime、Container、MemoryStore、KnowledgeBase、SkillContextBuilder、数据库、依赖、前端或 HTTP 契约。
- handoff 写入时上述文件均为本轮未提交改动，没有发现任务外改动。最终本地提交由结束时 `git log` 确认，下一份 verification/handoff 再记录新 HEAD。

## 复审修正与失败尝试

- 首轮 10 项专项和 98 项相关回归均通过，没有测试命令失败。
- 聚焦自审发现 `_load_memory()`/`_load_knowledge()` 对 `TypeError` 的捕获覆盖了依赖方法调用，可能把实现程序错误误报为来源格式错误；已把捕获缩到返回 iterable 转换，并补内部 `TypeError` 继续传播的等价覆盖。
- 恢复时动态 status 的第一纵切 hash 仍为 pending，但上一 handoff 明确要求由下一份 verification/handoff 记录；Git、`V-20260809-008/009` 和当前代码一致，本轮正常回填 `9b052c2`，没有新增 known issue。

## 未验证范围

- Collector 尚未构造新的 RuntimeRequest、执行 AgentRuntime 或接入默认 Container；M11-T4 保持 `in_progress`。
- 当前同步调用链只使用 ConversationMemory、InMemoryKnowledgeBase、SkillContextBuilder 和确定性 summary result fixture；没有执行 PostgreSQL Memory/pgvector、在线摘要或 Provider。
- MemoryStore message 没有 owner 字段；collector 只能信任 server-provided session→owner 绑定，不能把当前证据描述为应用身份主链已验证。Fact owner 已逐条校验。
- RAG JSON/trust 隔离不证明在线模型永远抵抗提示注入；Recall@K、MRR 和依据正确率仍由 M11-T6 完成。
- `ceil(bytes / 4)` 仍不是 Provider tokenizer、usage、模型窗口或费用；`KI-018` 保持 open。

## 下一条原子动作

继续 `M11-T4` 第三个离线纵切，只实现显式 Context-aware Runtime request adapter：

- 定义窄的 trusted input factory，从原 RuntimeRequest 和服务端绑定的 owner/session/system constraints 构造 ContextCollectionInput；模型、工具参数和已有 prompt_context 不能提供 owner、session 或 policy。
- 执行 collector→Assembler 后用 `dataclasses.replace()` 或同等冻结复制生成新 RuntimeRequest，保持 run_id、input_text、execution_context、checkpoint_context 等字段对象不变，只写入组装后的 prompt_context。
- 原请求已有 prompt_context 时 fail closed，避免与旧 SkillAwareRuntime 双重注入；collection/assembly/summary 失败映射为稳定无内容 Runtime failure，delegate 不得执行。
- 用显式 Fake delegate 验证正常、空上下文、跨 owner、summary unavailable、已有 prompt_context 冲突、执行上下文保留和 delegate 单次调用；不接默认 Container，不删除 SkillAwareRuntime，不进入 M11-T5/M11-T6。

## 恢复命令

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_context_collector backend.tests.test_context_assembler backend.tests.test_runtime_contract backend.tests.test_skill_context backend.tests.test_memory backend.tests.test_memory_store_contract backend.tests.test_rag backend.tests.test_research_workflow backend.tests.test_langgraph_replanning backend.tests.test_langgraph_checkpointing backend.tests.test_container -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

本轮相关定向 98 项、M1 10 项，以及连续性 52 个稳定任务/101 个 Markdown 已通过。恢复一致后不要重做 M11-T1–T3 或 M11-T4 前两纵切，下一步只实现显式 Runtime request adapter；未经新授权不安装依赖、不读取 Key、不执行在线/付费调用、不配置或推送远程 Git。
