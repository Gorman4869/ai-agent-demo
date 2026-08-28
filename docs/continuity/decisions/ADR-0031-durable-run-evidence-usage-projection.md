# ADR-0031：M12 Run 证据与 Usage 的事件投影

- 状态：accepted
- 日期：2026-08-28
- 任务：`M12-T3`
- 依赖：`ADR-0025`、`ADR-0026`、`ADR-0029`、`ADR-0030`

## 背景

默认 Run 在 Context 阶段已选择 RAG、Memory、最近消息、Skill 和系统约束；
Coordinator 也已持久化 Runtime progress、审批和终态。但 M12-T1 的 durable
snapshot 仍固定返回空 `citations` 和 `usage=null`，客户端无法确认回答实际使用了
哪些证据，也无法从同一 Run 的事件读取 SDK 已报告的 usage。

直接从当前 KnowledgeBase 再检索会让历史 Run 的证据随索引变化，直接返回
`prompt_context` 或所有 Context fragments 又会泄漏 owner-scoped Memory、最近消息
和内部策略。M12-T3 必须只投影已经为该 Run 持久化的公开事件。

## 决策

### 1. Context Runtime 只发出被选中 RAG fragment 的公开 citation 事件

同步和异步 ContextAwareRuntime 在完成 ContextAssembly 后，从**已入选**的
`ContextSource.RAG` fragments 生成可校验的 `rag.citations` RuntimeEvent。每项仅含
既有公开 citation 字段：`title`、`source`、`excerpt` 和有限 score；不保存 document
ID、query、prompt、Memory、recent messages、system policy 或 Skill 内容。

没有入选 RAG fragment 时不发 citation 事件。Context 失败时只发稳定
`context.failed` code，再由 Coordinator 写入同一 Run 的安全终态；不能把底层错误
或 source 内容带到事件。

### 2. durable snapshot 只读取同一 owner-scoped EventStore

`DurableRunResponse.citations` 从最新有效 `rag.citations` 事件投影，`usage` 从最新
有效、`scope=run` 的 `model.usage` 事件投影。读取按照 sequence 分页直到读完，绝不
重新检索、重新运行 Runtime，或从其他 Run/Session 汇总。

畸形、未知或不完整的 progress event 不让 HTTP 失败，也不猜测数值：无有效 citation
时返回空列表；无有效 usage 时返回 null。`estimated_cost_usd` 只有有限非负数才公开，
否则保持 null。M13 才负责持久 usage ledger、成本定价和追踪。

### 3. 保留现有 API 与后续边界

`/api/durable` 的 owner/capability 校验、SSE sequence 和 legacy API 隔离不变。独立
Research API 暂留兼容；Vue 何时停止调用它属于 M12-T4/T6。审批事件的精确 tool
binding 继续只由 Coordinator/ApprovalStore 处理，不从 citation 投影推断。

## 后果

- 回答、引用、usage 与终态可由同一 Run ID 的持久事件核验，重启后仍可读。
- 证据表示“实际进入本次 prompt 的 RAG 片段”，不是当前索引的重新搜索结果，也不是
  对回答事实正确性的保证。
- 默认离线 ManualRuntime 没有 `model.usage` 时快照仍为 null；不能将该 null 解释为
  零 token 或零成本。

## 未采用方案

- 查询快照时再调用 KnowledgeBase.search：历史会漂移，且不证明当时用于回答的证据。
- 直接解析或返回完整 prompt_context：会泄漏 Memory、最近对话和可信系统内容。
- 从所有 Context fragments 生成 citations：会把因预算淘汰的证据伪装成实际使用。
- 在 M12-T3 引入 provider 账本、价格表、Redis 或 Vue 状态机：分别由 M13 或 M12-T4+
  承接。

## 验证依据

- `backend/tests/test_durable_run_projection.py`
- `backend/tests/test_context_runtime.py`
- `backend/tests/test_async_context_runtime.py`
- `V-20260828-010`
