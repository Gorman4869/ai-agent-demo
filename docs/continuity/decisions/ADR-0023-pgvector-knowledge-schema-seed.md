# ADR-0023：pgvector 知识 Schema 与显式幂等 Seed

- 状态：accepted
- 日期：2026-08-08
- 任务：`M11-T2`
- 依赖：`ADR-0001`、`ADR-0022`

## 背景

现有 `PgVectorKnowledgeBase` 已有参数化写入与 cosine 查询形状，但 `initialize_schema()` 在运行时拼接 `CREATE EXTENSION/TABLE`，只有 Fake Connection 单测。默认 FastAPI 还会在 `create_app()` 或 lifespan 启动时隐式写入 Demo 文档，`/api/knowledge/demo-seed` 实际只返回启动时的结果。

M11-T2 要求真实 pgvector migration、文档/切片表、维度、索引、增删改和相似度检索证据，同时不能破坏 M11-T1 已验收的 vanilla PostgreSQL Run Store 恢复路径，也不能提前进入 M11-T3 在线 Embedding 或 M13 生产部署。

## 决策

### 1. Knowledge migration 使用独立命名空间

pgvector Schema 位于 `backend/knowledge_migrations/`，使用独立 advisory lock 和 `knowledge_schema_migrations` 校验和表。`PgVectorKnowledgeBase.initialize_schema()` 只显式执行该版本化 migration，不再动态生成 DDL。

M11-T1 的 `backend/migrations/` 与 `app_schema_migrations` 保持不变。这样默认 Run/Event/Approval/Memory persistence 仍可在 vanilla PostgreSQL 上恢复；只有显式 pgvector 集成测试或显式 knowledge adapter 才要求 `vector` extension。

### 2. M11-T2 固定三维课程向量与 cosine 索引

首个真实纵切固定 `vector(3)`，用于确定性、无网络、无 Key 的课程 Embedding。检索使用 cosine distance `<=>`，Schema 建立 `hnsw (... vector_cosine_ops)` 索引；排序继续以 distance、document ID、chunk index 固定并列结果。

默认表为 `knowledge_documents` 与 `knowledge_chunks`。文档表保存 title、source、内容摘要、chunk count 和更新时间；切片表通过外键级联删除，只保存 excerpt 与 embedding。未来若 M11-T3/M11-T7 选择其他维度，必须新增版本化 Schema 决策或独立表，不能静默把不匹配向量写入本表。

### 3. Replace、delete 与 seed 都是显式事务

`add()` 在一个事务中 upsert 文档、删除旧切片并插入新切片；任一切片失败时旧文档和旧切片全部保留。`delete()` 删除文档并依赖外键级联切片，返回是否实际删除。

`seed()` 是单独的显式命令。它先按 document ID 获取 transaction advisory lock，再比较由 title、source 和规范化切片生成的 SHA-256 摘要；摘要相同直接返回已有 chunk count，不重算数据库记录。并发相同 seed 因此只产生一份权威内容。

### 4. Demo seed 不再属于应用启动

FastAPI 模块 import、`create_app()` 和 lifespan 均不写 knowledge Store。只有调用 `/api/knowledge/demo-seed` 才执行 server-owned `DEMO_COURSE_DOCUMENT` 的 `seed()`；任意文档写 API仍不能覆盖该保留 ID。

该端点不接收文档内容、路径、维度或身份参数，只触发固定课程数据，因此本任务保留现有公开访问形状。M12 统一 Run API、M11-T3 Embedding 与 M13 生产 seed/部署策略不在本决策内。

### 5. 容器只用于本地集成

新增 `deploy/compose.integration.yaml`，固定 pgvector/PostgreSQL image、localhost 端口与 tmpfs 数据目录。它不修改主 `deploy/compose.yaml`，不提供生产鉴权、TLS、持久卷、备份、高可用或容量声明。

## 后果

- Fake Connection 继续覆盖 SQL 参数、事务和适配器映射，但不能作为 M11-T2 完成证据。
- 真实验收必须在 vector extension 可用的 PostgreSQL 中执行 migration、CRUD、seed、相似度查询、维度错误和事务回滚。
- 本机没有已缓存的 pgvector image；下载 image 属于新增外部依赖，必须取得用户明确授权后才能执行。
- 默认内存 KnowledgeBase 保持离线，并实现同一 `seed/delete` 领域合同。

## 未采用方案

- 把 pgvector migration 追加到 M11-T1 `app_schema_migrations`：会让已验收的 Run Store 强制依赖 vector extension，并破坏 vanilla PostgreSQL 恢复边界。
- 启动时自动 seed：隐藏数据库写副作用，重复启动也无法区分配置与数据初始化。
- 使用无维度 `vector` 列：不能为本任务提供固定维度和普通 ANN 索引合同。
- 把在线 Provider Embedding 纳入本纵切：属于 M11-T3/M11-T7，且需要新的 Key 与费用授权。
