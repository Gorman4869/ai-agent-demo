# M11-T6 第一纵切交接：固定 RAG 数据集、指标与 sparse 基线

- 日期：2026-08-20
- 任务：`M11-T6 / in_progress`
- 验证基线：`f441615`
- 实现提交：`07ec390`
- 主要证据：`V-20260820-011/012/013`、`ADR-0023`、`ADR-0024`、`ADR-0025`

## 已完成

- 新增严格 `rag-retrieval-dataset-v1` fixture；`m11-rag-v1` 固定 10 篇课程文档、50 条唯一查询、相关文档与依据词、`top_k=3`，并在报告记录跨 JSON 格式和 checkout 换行稳定的 canonical-JSON SHA-256 内容摘要。
- sparse 与 pgvector 的 Recall@K/MRR/依据正确率阈值同时冻结为 0.9/0.8/0.9。loader 校验最少 50 条、唯一 ID、相关文档存在、依据词确实由相关内容支持和所有大小边界。
- 通用 evaluator 真实调用 `KnowledgeBase.search()`，计算宏 Recall@K、首相关 MRR 和 relevant-excerpt-only 依据正确率。无结果、漏召回、未排名、依据缺失和未配置文档均使用稳定失败码。
- 报告不输出 query、依据词、excerpt、title、source 或未配置返回 ID；本地延迟明确不是生产延迟，Provider usage unavailable、费用 unknown。CLI 低于任一阈值退出 1。
- 真实 sparse baseline 50 条 Recall@3/MRR/依据正确率为 1.0/1.0/1.0，当前 dataset digest 为 `3581d5fe65fb35cde0315d46d8e88f9a811221e8ed7a3d1f9963243221291b2b`。

## 修改文件

- `backend/app/evals/fixtures/rag_retrieval_v1.json`
- `backend/app/evals/rag_retrieval.py`
- `backend/tests/test_rag_retrieval_eval.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-08-20-m11-t6-rag-eval-foundation.md`

## 验证快照

- 新专项最终 12 项通过；Knowledge/Embedding/pgvector/Context/eval 扩大回归 78 项通过。
- sparse CLI 50 条通过，三项指标均为 1.0；最终没有 `runpy` warning。
- M1 `python -S` 隔离 10 项、连续性 52/115 和 `git diff --check` 通过。
- 没有运行全仓构建门，因为本纵切只新增显式 eval 模块/fixture/tests，不改依赖、公共 API、Store、Runtime、Container、数据库或前端。

## 未验证与边界

- 尚未用真实 pgvector 运行同一 50 条数据和冻结阈值，因此没有 sparse/pgvector 对照结论，也不能关闭 `KI-006`。
- sparse 1.0 只代表这个小型固定课程集；不证明开放域语义质量、在线 Embedding、模型回答正确率、Provider tokenizer/usage、费用、生产延迟或容量。
- 依据正确率当前严格定义为：所有标注依据词都出现在已检索的相关文档 excerpt 中。它评估可用于回答的依据，不生成答案，也不是模型级忠实度评测。
- 下一纵切不得通过增添无关文本、降低阈值或静默改 query/annotation 让 pgvector 通过。若 fixture 确有错误，必须升 dataset version、记录新旧 digest 并解释原因。

## 失败与警告

- 首次 sparse CLI 因将可执行模块导出到 `evals.__init__` 出现 `runpy` warning；删除无必要导出后最终 CLI 干净通过。
- 沙箱内创建 fixture 目录被拒绝，经授权只在项目内创建成功；一次执行器 ACL 辅助进程失败发生在 Python 启动前，同一专项立即复跑通过。
- 文档存在既有 LF→CRLF 提示，`git diff --check` 无 whitespace 错误。

## 下一条原子动作

只开始 M11-T6 第二纵切：构造显式 eval-only 三维确定性语义 Embedding，使用现有 `PgVectorKnowledgeBase`、integration pgvector 和完全相同的 `m11-rag-v1` canonical 内容摘要/top_k/阈值运行 50 条查询；与 sparse 报告比较 Recall@3、MRR、依据正确率、本地延迟和失败码。若未达阈值，保留失败并修复检索/Embedding 合同，不改 fixture 粉饰结果。不进入 M11-T7、前端或在线 Provider。

## 恢复命令

```powershell
git status --short
git log -5 --oneline
node --version
.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_rag_retrieval_eval -q
.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.rag_retrieval
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
docker compose -f deploy/compose.integration.yaml ps
```

预期专项 12 项、sparse 50 条和连续性 52/115 通过；dataset version 必须仍为 `m11-rag-v1`，canonical digest 必须仍为 `3581d5fe65fb35cde0315d46d8e88f9a811221e8ed7a3d1f9963243221291b2b`。若一致，不要重做 M11-T1–T5 或第一纵切，直接进入真实 pgvector 对照。
