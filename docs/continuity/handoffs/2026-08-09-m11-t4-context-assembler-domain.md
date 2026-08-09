# M11-T4 交接：有界 ContextAssembler 领域合同

- 日期：2026-08-09，Asia/Shanghai
- 当前任务：`M11-T4 / in_progress`
- 内部步骤：第一离线纵切完成；真实 source collector 与 Runtime 接线尚未完成
- 任务等级：B 类确定性离线领域合同；时间盒 30–90 分钟
- 验证基线：`02664b8`（`feat: add openai embedding adapter`）
- 工作区验证：`V-20260809-008/009`
- 关联决策：`ADR-0025`、`ADR-0010`、`ADR-0013`、`ADR-0024`
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- 新增标准库 `backend.app.context` 包，固定 system/recent/summary/memory/rag/skill 六种来源；trust 只能由 source 映射，调用方不能把 RAG、用户文本、Memory 或 Skill 提升为 system policy。
- `ContextFragment` 限制稳定 ID、16,000 UTF-8 字节内容、owner scope 与非负 ordinal；content/owner 隐藏 repr。Assembler 最多接受 128 条片段，先验证全部 scope 和重复 ID，再进行任何选择。
- recent/summary/memory 必须匹配 assembly owner，system/skill 只能全局，显式 owner-scoped RAG 也必须匹配；任一冲突稳定失败且不返回部分 prompt。
- 选择优先级固定为 system→memory→recent→summary→skill→rag，recent 从最新开始选；渲染顺序固定为 system→skill→summary→memory→recent→rag，recent 恢复时间正序。
- 每来源和总量按 `ceil(UTF-8 bytes / 4)` 估算。总量实际包含安全头部与完整 `context-assembly-v1` JSON；非 system 片段整条纳入或丢弃，system 放不下/不可用时 fail closed。
- 报告记录来源可用性、ID、trust、预算、选择/渲染顺序、纳入结果和原因，不含 content/owner；固定声明 Provider usage 不可用、费用未知。摘要不可用显式报告，空输入返回零成本 no-op。
- RAG JSON 逃逸 fixture 经实际 `json.loads()` 后仍是 `untrusted_evidence` content；非空输出也实际通过既有 `RuntimeRequest.prompt_context` 32 KB 校验。

## 验证摘要

- 恢复基线：上一 handoff 共享契约 160 项、真实 pgvector 4 项、M1 10 项和连续性 52/98 通过；Docker integration 容器 healthy。
- 新增 10 个关键测试方法或等价覆盖；首轮专项 10 项、首轮相关 40 项、最终 Context/Runtime/Skill/Memory/RAG/M10-T3/Container 88 项和 M1 隔离 10 项通过。
- 仅有既有 Starlette/httpx 弃用警告与 asyncio 慢任务诊断；没有失败或新增 skip。
- 没有修改共享 Runtime/Container/Store、依赖、数据库、构建或跨前后端接口，因此未触发完整全仓门；见 `V-20260809-008/009`。
- 没有读取 Key、访问在线模型、配置远程或产生费用。

## 修改文件

- 实现与导出：`backend/app/context/assembler.py`、`backend/app/context/__init__.py`
- 测试：`backend/tests/test_context_assembler.py`
- 决策与规约：`docs/continuity/decisions/ADR-0025-bounded-context-assembly.md`、`BACKEND_CODING_STANDARDS.md`
- 连续性：`docs/implementation-plan.md`、`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff
- 没有修改 RuntimeRequest、Runtime、Container、MemoryStore、KnowledgeBase、SkillBuilder、数据库、依赖、前端或 HTTP 契约。
- handoff 写入时上述文件均为本轮未提交改动，没有发现任务外改动。最终本地提交由结束时 `git log` 确认，下一份 verification/handoff 再记录新 HEAD。

## 漂移、失败尝试与复审修正

- 恢复时发现 status 顶部 M11-T3 第三纵切实现 hash 仍 pending，底部恢复入口仍指向 M11-T3 第二纵切；Git、`V-20260809-006/007` 和最新 handoff 证明当前 HEAD 为 `02664b8` 且任务是 M11-T4。已先登记 `KI-025`，修正动态 status 后由 `V-20260809-009` 的连续性、diff 与 Git 复核关闭。
- 两次按推测路径读取 ADR 失败：PowerShell 不接受传给 `rg` 的 Unix 风格 `*.md` 路径，ADR-0024 实际文件名也不同；均通过 `rg --files`/目录搜索定位，不是代码漂移。
- 新包目录不存在导致首个 `apply_patch` 未写入；沙箱内 `New-Item` 又被拒绝。获准只创建 `backend/app/context` 目录后，文件继续全部由 `apply_patch` 写入。
- 聚焦复审收紧伪造 Policy/budget 构造错误，增强 RAG JSON 结构逃逸 fixture，并把选择优先级、渲染顺序、system 来源不可用和 128 条上限纳入安全报告/测试。

## 未验证范围

- ContextAssembler 尚不查询真实 MemoryStore、KnowledgeBase 或 SkillBuilder，不生成摘要，也未接入默认 Runtime/Container；当前只有领域 E3，M11-T4 保持 `in_progress`。
- Memory 关键事实保留来自 fixture 与固定优先级，不证明 PostgreSQL fact 主链、纠正/删除后注入或真实长对话模型质量。
- RAG trust/JSON 隔离不证明在线模型永远抵抗提示注入；固定 Recall@K、MRR 和回答依据正确率仍由 M11-T6 完成。
- `ceil(bytes / 4)` 不是 Provider Token、模型窗口、usage 或费用；没有成本账本，`KI-018` 保持 open。
- 没有运行修改后真实数据库或完整构建门；本轮不涉及数据库和构建边界，恢复阶段 pgvector 4 项只证明基线一致。

## 下一条原子动作

继续 `M11-T4` 第二个离线纵切，只实现显式 Context source collector：

- 定义窄的 collector 输入与可注入 summary 协议；system 约束和 owner/session/query 只能由服务端调用方提供，不能从模型文本派生。
- 把真实 `MemoryStore.messages()`、`MemoryStore.facts()`、`KnowledgeBase.search()` 和 `SkillContextBuilder.build()` 结果映射为当前 `ContextFragment`，保留 owner、ordinal、citation/Skill 稳定 ID，不改这些 Store/Builder 协议。
- 摘要成功映射为 owner-scoped summary；摘要失败只标记 `ContextSource.SUMMARY` unavailable，不拼回无界历史、不暴露原始异常。
- 用离线内存 Store/RAG/Skill fixture 走通 collector→Assembler，覆盖跨 owner、空来源、检索注入和摘要失败；不接默认 Runtime/Container，不修改持久 Store，不进入 M11-T5/M11-T6。

## 恢复命令

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_context_assembler backend.tests.test_runtime_contract backend.tests.test_skill_context backend.tests.test_memory backend.tests.test_memory_store_contract backend.tests.test_rag backend.tests.test_research_workflow backend.tests.test_langgraph_replanning backend.tests.test_langgraph_checkpointing backend.tests.test_container -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

本轮相关定向 88 项、M1 10 项，以及连续性 52 个稳定任务/100 个 Markdown 已通过。恢复一致后不要重做 M11-T1–T3 或 M11-T4 第一纵切，下一步只实现 source collector；未经新授权不安装依赖、不读取 Key、不执行在线/付费调用、不配置或推送远程 Git。
