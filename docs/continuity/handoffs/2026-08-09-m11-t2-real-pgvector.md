# M11-T2 交接：真实 pgvector 文档与检索闭环

- 日期：2026-08-09，Asia/Shanghai
- 已验收任务：`M11-T2 / verified`
- 当前任务：`M11-T3 / planned`
- 任务等级：A 类数据库 extension、版本化 schema、事务替换与启动副作用边界；时间盒 2–4 小时
- 实现提交：`7ebaa16`（`feat: add real pgvector knowledge store`）
- 工作区验证：`V-20260809-001`
- 连续性闭环：`V-20260809-002`
- 关联决策：`ADR-0023`、`ADR-0022`、`ADR-0001`
- Python/Node 依赖变化：无
- Docker image：用户明确授权后下载固定 `pgvector/pgvector:0.8.1-pg17`；后续 Compose 使用 `pull_policy: never`
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- 新增独立 `backend/knowledge_migrations` 与 checksum history/advisory lock，不让 M11-T1 的 Run Store migration 强制依赖 vector extension。
- 固定 `knowledge_documents`、外键级联 `knowledge_chunks`、`embedding vector(3)` 与 cosine HNSW；`PgVectorKnowledgeBase` 支持事务 replace、delete、search 和摘要 seed。
- FastAPI import、`create_app()` 与 lifespan 不再隐式写 Demo。固定 `/api/knowledge/demo-seed` 才显式执行 server-owned seed；文档编辑 API 仍不能覆盖保留 ID。
- 新增 localhost-only trust/tmpfs integration Compose。真实 pgvector 测试实际执行 migration、schema/index 检查、插入、替换、删除、相似度查询、同摘要不重写、维度错误与旧内容回滚。
- M11-T2 更新为 `verified`；`KI-006` 只降为 mitigated，Embedding Adapter 与固定检索指标仍由 M11-T3/M11-T6 承接。

## 验证摘要

- 提交后知识/PgVector/RAG/API/Container 55 项、真实 pgvector 4 项、M11-T1 PostgreSQL 91 项和 M1 `-S` 10 项通过。
- 完整离线门最终后端 470 项通过、1 项既有 Windows symlink 跳过；Code Agent、`pip check`、Vue、MCP TypeScript 与主 Compose 配置通过。
- 完整门首轮有一次既有 TypeScript MCP 5 秒 startup timeout；单独 E2E 4 项在 0.943 秒通过，同一门从头重跑退出 0。
- 提交前完整后端曾有一次 lease 时序用例失败；该用例单独通过，最终串行后端 470 项与 M11-T1 真实 PostgreSQL 91 项均通过。失败和最终结果都记录在 `V-20260809-001`。

## 修改文件

- 实现：`backend/app/knowledge/pgvector.py`、`pgvector_migrations.py`、`rag.py`、`__init__.py`、`backend/app/main.py`
- Schema/环境：`backend/knowledge_migrations/0001_pgvector_knowledge.sql`、`deploy/compose.integration.yaml`
- 测试：`backend/tests/pgvector_integration.py`、`test_pgvector.py`、`test_rag.py`、`test_api.py`、`test_container.py`
- 决策/规约：`docs/continuity/decisions/ADR-0023-pgvector-knowledge-schema-seed.md`、`BACKEND_CODING_STANDARDS.md`
- 连续性：`docs/implementation-plan.md`、`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff
- handoff 写入时：实现提交已固定；连续性文件等待本轮本地文档提交，不包含其他工作区改动。

## 未验证范围

- 三维 keyword Embedding 是确定性测试 fixture，不是 Provider Embedding；没有在线批处理、重试、缓存、usage、费用或模型质量证据。
- 相同 seed 不重写数据库，但当前会先计算确定性切片向量；没有证明 Provider 调用缓存。M11-T3 应明确批处理与缓存所有权。
- 没有不少于 50 条查询的 Recall@K、MRR 或回答依据正确率，`KI-006` 不能关闭。
- PgVector adapter 未接入默认 `ApplicationContainer`。integration Compose 不是主 Compose，也不是生产鉴权、TLS、持久卷、备份、高可用、容量或跨主机证据。

## 下一条原子动作

进入 `M11-T3` 首个原子纵切，只处理确定性离线 Embedding 的最小真实合同：

- 先审计现有模型 adapter、`EmbeddingModel`、`PgVectorKnowledgeBase` 与配置边界，用新 ADR 固定单条/批次接口、维度元数据、缓存键、重试分类和在线授权所有权。
- 首步实现确定性离线 Embedding、批次拆分、空输入和维度漂移关键测试；不要同时扩写完整教程或固定 50 条 RAG 评测集。
- 默认离线、无 Key、费用 0；没有用户新的明确授权，不读取 Key、不执行在线 Embedding、不安装依赖、不改主 Compose、不进入 M11-T4/M12/M13。

## 恢复命令

```powershell
git status --short
git log -6 --oneline
docker compose -f deploy/compose.integration.yaml up -d --wait --pull never
$env:AI_AGENT_TEST_PGVECTOR_DSN = "postgresql://ai_agent@127.0.0.1:55433/ai_agent_integration?sslmode=disable"
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.pgvector_integration -q
$testExit = $LASTEXITCODE
Remove-Item Env:\AI_AGENT_TEST_PGVECTOR_DSN -ErrorAction SilentlyContinue
if ($testExit -ne 0) { exit $testExit }
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_pgvector backend.tests.test_rag backend.tests.test_api backend.tests.test_container -q
$env:AI_AGENT_TEST_POSTGRES_DSN = "postgresql://ai_agent@127.0.0.1:55432/ai_agent_test?sslmode=disable"
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.postgres_store_integration -q
$testExit = $LASTEXITCODE
Remove-Item Env:\AI_AGENT_TEST_POSTGRES_DSN -ErrorAction SilentlyContinue
if ($testExit -ne 0) { exit $testExit }
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期真实 pgvector 4 项、知识/API 定向 55 项、M11-T1 PostgreSQL 91 项、M1 10 项，以及连续性 52 个稳定任务/94 个 Markdown 通过。若固定 image 不在本机，`--pull never` 应失败；未取得新的明确授权前不得下载。若恢复一致，不要重做 M11-T1/M11-T2，下一步只进入 M11-T3 离线 Embedding 纵切。
