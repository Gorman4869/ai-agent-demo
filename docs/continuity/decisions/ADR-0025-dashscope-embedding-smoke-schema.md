# ADR-0025：DashScope 在线 Embedding 使用隔离 64 维 Schema

- 状态：accepted
- 日期：2026-08-27
- 任务：`M11-T7`
- 依赖：`ADR-0023`、`ADR-0024`

## 背景

M11-T7 的首次 OpenAI 在线尝试在实际 Provider 返回
`embedding_provider_quota_or_rate_limited` 后未完成写入/查询。学习者选择阿里云百炼
`text-embedding-v4` 作为替代的真实 Embedding Provider。

已验收 M11-T6 的 `knowledge_chunks.embedding` 是固定 `vector(3)`：它保存离线课程
评测向量和冻结的 50 条评测结果。DashScope `text-embedding-v4` 的最小可选维度为 64，
不能修改既有三维表或把 64 维向量压缩为三维来伪造真实 Provider 证据。

## 决策

1. 新增仅用于 M11-T7 DashScope 冒烟的 `dashscope_knowledge_documents` 与
   `dashscope_knowledge_chunks`，后者固定 `vector(64)`、cosine HNSW，并使用独立 migration
   history/lock。原 `knowledge_*` 三维评测表保持不变。
2. `AI_AGENT_EMBEDDING_PROVIDER=dashscope` 只能使用 `text-embedding-v4`、64 维、显式
   revision、`DASHSCOPE_API_KEY`、全局 online switch，以及受限为百炼北京 Workspace
   OpenAI-compatible `/compatible-mode/v1` endpoint 的 `AI_AGENT_DASHSCOPE_BASE_URL`。
   这不是任意第三方中转地址配置。
3. 请求仍经现有 OpenAI SDK 的公开 `embeddings.create()` 形状发送；领域 metadata 明确记录
   provider 为 `dashscope`，并沿用稳定、无原始文本的错误与 usage 合同。
4. 在线 CLI 只有显式 `--authorized`、`batch_size=1`、`max_retries=0` 时运行。它只写一篇
   非敏感合成文档、查询一次并在 finally 删除；最多两次 Provider 请求。费用未知时保持
   `null/unknown`，不估算为零。

## 后果

- 原 M11-T6 评测、三维 migration、默认离线 RAG 与 OpenAI Adapter 维持可复现结果。
- 新增真实百炼 E4 证据前，DashScope 实现最多为离线 E3；不会把 MockTransport 或本地
  pgvector 误称为在线兼容。
- 这不是通用多 Provider 框架、任意 base URL、生产知识库、成本账本或批量导入设计；后续
  Provider 与维度需要各自的稳定决策。
