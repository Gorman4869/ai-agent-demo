# M11-T3 交接：确定性离线 Embedding 与批次纵切

- 日期：2026-08-09，Asia/Shanghai
- 当前任务：`M11-T3 / in_progress`
- 内部步骤：第一离线纵切完成；缓存、重试和在线 Adapter 未完成
- 任务等级：B 类普通离线 Adapter 与确定性批次功能；时间盒 30–90 分钟
- 验证基线：`9b77bfd`（`docs: anchor M11-T2 pgvector retrieval`）
- 工作区验证：`V-20260809-003`
- 关联决策：`ADR-0024`、`ADR-0023`、`ADR-0005`
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- 新增冻结 `EmbeddingMetadata`，固定 provider/model/revision/dimensions；控制字符、异常长度、非正整数维度在构造期拒绝。
- 新增 `EmbeddingProvider`/`EmbeddingModel`、通用 `BatchingEmbeddingModel` 与标准库 `DeterministicEmbeddingProvider`。单条复用批次路径，空批 no-op，空文本在 Provider 前拒绝。
- Batching Model 按固定 batch size 拆分并保持顺序；部分返回、metadata 变化、维度漂移、非数字和非有限值使用稳定无内容错误 fail closed。
- `PgVectorKnowledgeBase` 对全部文档切片执行一次 Model batch，查询执行单元素 batch；完整向量在打开 connection/transaction 前校验，因此部分 Embedding 失败不改写数据库。
- ADR-0024 已固定未来缓存键、暂时性错误重试和在线 composition 授权所有权，但本轮没有实现这些后续能力。

## 验证摘要

- 恢复基线：真实 pgvector 4 项、知识/API 55 项、M11-T1 PostgreSQL 91 项、M1 10 项、连续性 52 个任务/94 个 Markdown 通过。
- 首轮 Embedding/PgVector 22 项通过；聚焦自审补非整数 metadata/batch size、DEL 控制字符和稳定非数字向量错误。
- 最终 Embedding/PgVector/RAG/API/Container 定向 67 项、真实 pgvector 4 项、M1 `-S` 10 项通过。仅有既有 Starlette/httpx 弃用警告。
- 新增 12 个关键测试方法或等价覆盖，覆盖正常批次、`2/2/1` 拆分、顺序、空批/空文本、部分返回、metadata/维度漂移、非法值和数据库零调用。
- 没有触发完整全仓门：无依赖、锁文件、构建配置、Settings、migration、跨前后端接口或多个里程碑共享核心契约变化。

## 修改文件

- 实现：`backend/app/knowledge/embeddings.py`、`backend/app/knowledge/pgvector.py`、`backend/app/knowledge/__init__.py`
- 测试：`backend/tests/test_embeddings.py`、`backend/tests/test_pgvector.py`、`backend/tests/pgvector_integration.py`
- 决策/规约：`docs/continuity/decisions/ADR-0024-embedding-batching-boundary.md`、`BACKEND_CODING_STANDARDS.md`
- 连续性：`docs/implementation-plan.md`、`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff
- handoff 写入时：上述文件均为本轮未提交改动；没有其他工作区改动。最终本地提交由结束时 `git log` 确认，下一份 verification/handoff 再记录新 HEAD。

## 失败尝试与复审修正

- 恢复时按推测文件名读取 ADR-0005 失败；随后用 `rg --files` 找到实际文件名，未发现文档漂移。
- 初版类型标注未在运行时阻止 float/bool dimensions 或 batch size；聚焦自审改为构造期正整数校验。
- 初版 PgVector 直接传播 `float()` 的非数字转换信息；聚焦自审改为稳定 `embedding values must be numeric`，不回显原值。

## 未验证范围

- 没有缓存 Store、缓存命中、失败不缓存或版本化 key 实现；ADR 只是后续合同。
- 没有暂时性错误分类、按批次 retry、timeout、退避或耗尽证据。
- 没有在线 SDK Adapter、Embedding Settings、Client 构造、Key 读取、Provider usage/费用或真实在线结果。
- 三维 SHA-256 token-hash 只证明确定性工程路径，不证明语义质量、Provider tokenizer、Recall@K、MRR 或回答依据正确率；`KI-006` 保持 mitigated。
- integration Compose 仍是 localhost trust/tmpfs 测试环境，不是生产部署证据。

## 下一条原子动作

继续 `M11-T3` 第二个 B 类离线纵切，只实现版本化内存缓存和按批次暂时性错误重试 wrapper：

- 缓存键按 ADR-0024 使用 metadata namespace 与规范化文本 digest；只缓存完整、维度已验证的成功向量，原文不进入 key/日志/错误。
- Retry 只接受显式 `RetryableEmbeddingError`，按 Provider batch 计数；输入、协议、维度、metadata、认证/策略类错误不重试。覆盖首次暂时失败后成功、耗尽、不可重试和失败不缓存。
- 保持默认离线、无 Key、费用 0；不要在同一纵切实现在线 SDK Adapter、Settings、真实调用、持久缓存或 M11-T4。

## 恢复命令

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_embeddings backend.tests.test_pgvector backend.tests.test_rag backend.tests.test_api backend.tests.test_container -q
docker compose -f deploy/compose.integration.yaml up -d --wait --pull never
$env:AI_AGENT_TEST_PGVECTOR_DSN = "postgresql://ai_agent@127.0.0.1:55433/ai_agent_integration?sslmode=disable"
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.pgvector_integration -q
$testExit = $LASTEXITCODE
Remove-Item Env:\AI_AGENT_TEST_PGVECTOR_DSN -ErrorAction SilentlyContinue
if ($testExit -ne 0) { exit $testExit }
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期知识/API 67 项、真实 pgvector 4 项、M1 10 项，以及连续性 52 个稳定任务/96 个 Markdown 通过。Compose 使用 `--pull never`；若固定 image 不在本机，未获新授权前不得下载。恢复一致后不要重做第一纵切，下一步只实现缓存与暂时性重试 wrapper。
