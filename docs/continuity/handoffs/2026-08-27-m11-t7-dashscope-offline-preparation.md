# M11-T7 交接：DashScope 64 维在线冒烟离线准备

- 日期：2026-08-27
- 任务：`M11-T7 / blocked`
- 主要证据：`V-20260827-004`、`ADR-0025`
- 验证基线：`374514a`

## 已完成

- 百炼 `text-embedding-v4` 被实现为显式 `dashscope` Embedding Provider：必须同时具备 online switch、`DASHSCOPE_API_KEY`、百炼北京 Workspace `/compatible-mode/v1` endpoint、model、revision 和固定 64 维；默认仍为离线。
- 新 `DashScopePgVectorKnowledgeBase` 使用单独的 migration lock/history、`dashscope_knowledge_documents` 和 `dashscope_knowledge_chunks vector(64)`。三维 `knowledge_*` 表、M11-T6 固定评测和 OpenAI Adapter 不变。
- `backend.app.evals.dashscope_embedding_smoke` 默认拒绝执行；只有 `--authorized`、batch size 1、retry 0 才会运行。成功路径最多两次 Provider 请求，且始终尝试删除临时文档。
- 无 Key 定向 74 项与真实本地 pgvector 6 项通过。没有在线调用或费用。

## 修改文件

- 配置与 Provider：`backend/app/settings.py`、`backend/app/container.py`、`backend/app/knowledge/openai_embeddings.py`、`backend/.env.example`
- 隔离 Schema：`backend/app/knowledge/dashscope_pgvector.py`、`backend/dashscope_knowledge_migrations/0001_dashscope_online_knowledge.sql`、`backend/app/knowledge/pgvector_migrations.py`
- 在线入口与测试：`backend/app/evals/dashscope_embedding_smoke.py`、`backend/tests/test_dashscope_embeddings.py`、`backend/tests/test_dashscope_pgvector.py`、`backend/tests/pgvector_integration.py`
- 连续性：`ADR-0025`、implementation plan、status、verification log、本文件

## 恢复与唯一下一步

用户不得在聊天中粘贴 Key。用户只需在当前 Codex 本机环境配置：

```powershell
$env:DASHSCOPE_API_KEY = '<local key>'
$env:AI_AGENT_DASHSCOPE_BASE_URL = 'https://<workspace-id>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'
$env:AI_AGENT_ONLINE_ENABLED = 'true'
$env:AI_AGENT_EMBEDDING_PROVIDER = 'dashscope'
$env:AI_AGENT_EMBEDDING_MODEL = 'text-embedding-v4'
$env:AI_AGENT_EMBEDDING_REVISION = 'm11-t7-dashscope-2026-08-27'
$env:AI_AGENT_EMBEDDING_DIMENSIONS = '64'
$env:AI_AGENT_EMBEDDING_BATCH_SIZE = '1'
$env:AI_AGENT_EMBEDDING_MAX_RETRIES = '0'
$env:AI_AGENT_TEST_PGVECTOR_DSN = 'postgresql://ai_agent@127.0.0.1:55433/ai_agent_integration?sslmode=disable'
```

配置后，用户必须明确回复：

> 已配置百炼环境，允许执行一次 DashScope Embedding 冒烟测试。

收到授权后，只运行：

```powershell
./.venv/Scripts/python.exe -B -m backend.app.evals.dashscope_embedding_smoke --authorized
```

不要安装依赖、修改全局代理或自动重试。若失败，记录新的稳定错误码；若成功，记录返回的 model、维度、批次、usage、耗时和未知费用边界，再确认临时文档已删除。
