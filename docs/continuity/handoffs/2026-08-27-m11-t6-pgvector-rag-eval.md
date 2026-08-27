# M11-T6 第二纵切交接：真实 pgvector 固定对照

- 日期：2026-08-27
- 任务：`M11-T6 / verified`
- 验证基线：`f0e4899`
- 实现提交：`0b4e1d9`（`feat: evaluate fixed RAG corpus with pgvector`）
- 主要证据：`V-20260820-011/012/013`、`V-20260827-001`、`ADR-0023`、`ADR-0024`、`ADR-0025`

## 已完成

- 保持 `m11-rag-v1` 的 10 篇文档、50 条查询、相关文档/依据词、`top_k=3`、阈值和 canonical SHA-256 摘要不变：`3581d5fe65fb35cde0315d46d8e88f9a811221e8ed7a3d1f9963243221291b2b`。
- 新增 `backend/app/evals/pgvector_rag_retrieval.py`：仅供固定课程评测使用的离线三维确定性主题 Embedding，以及真实 `PgVectorKnowledgeBase` runner/JSON CLI。它只识别有界课程词汇，不是通用语义或生产模型。
- 新增评测单元测试，并让现有真实 pgvector integration 直接执行 50 条固定评估。最终 sparse/pgvector 对照分别为 `1.0/1.0/1.0` 与 `0.98/0.946667/0.98`（Recall@3/MRR/依据正确率）。
- pgvector 报告没有阈值失败码，但仍保留 `memory-04` 的漏召回、未排名和依据缺失。没有通过修改 fixture、标注或阈值让结果通过。
- M11-T6 已 `verified`，`KI-006` 已关闭；M11 里程碑仍为 `in_progress`，因为 M11-T7 在线冒烟与 M11-T8 课程验收尚未开始。

## 修改文件

- `backend/app/evals/pgvector_rag_retrieval.py`
- `backend/tests/test_pgvector_rag_retrieval.py`
- `backend/tests/pgvector_integration.py`
- `docs/implementation-plan.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/handoffs/2026-08-27-m11-t6-pgvector-rag-eval.md`

## 验证快照

- `./.venv/Scripts/python.exe -X utf8 -B -m unittest backend.tests.test_pgvector_rag_retrieval -v`：2 项通过。
- 配置本地 `AI_AGENT_TEST_PGVECTOR_DSN=postgresql://ai_agent@127.0.0.1:55433/ai_agent_integration` 后，`backend.tests.pgvector_integration`：5 项通过。
- 同一 DSN 的 pgvector runner：50 条、Recall@3 `0.98`、MRR `0.946667`、依据正确率 `0.98`；阈值 `0.9/0.8/0.9` 通过，usage unavailable、费用 unknown。
- 本机 integration 容器来自 `deploy/compose.integration.yaml`，仅绑定 `127.0.0.1:55433` 且使用 tmpfs；它不是生产持久化、鉴权、容量或延迟证据。

## 失败与警告

- 首版评测词表只得到 `0.84/0.806667/0.84`，且真实 pgvector 集成测试按预期失败。根因是同一概念的换说法未被有界词表识别，以及 `Context` 跨主题词造成误召回；只增加课程概念锚点后达到阈值。
- 最终仍有 1 个 `memory-04` 漏召回。报告保留稳定失败码；阈值通过不等于每条查询都完美。
- 运行测试前曾有沙箱执行器辅助错误；切换后 Docker、本机 PostgreSQL 与 Python 集成测试均可执行。当前测试结果证明的是本机环境，而非外部服务可用性。

## 下一条原子动作

不要自动进入 M11-T7。只有用户提供 API Key、启用明确在线开关并作单次授权时，才运行独立在线 Embedding 冒烟，记录模型/维度/批次/耗时/usage/成本并避免敏感输入写入日志。否则保持离线默认，不改前端、不进入 M12。

## 恢复命令

```powershell
git status --short
docker compose -f deploy/compose.integration.yaml ps
./.venv/Scripts/python.exe -X utf8 -B -m unittest backend.tests.test_rag_retrieval_eval -q
./.venv/Scripts/python.exe -X utf8 -B -m unittest backend.tests.test_pgvector_rag_retrieval -q
```

真实 PostgreSQL 测试只在本机 integration 容器 healthy 且显式提供测试 DSN 时运行；恢复时先检查 health，不能把未配置 DSN 的 skip 记录为成功。
