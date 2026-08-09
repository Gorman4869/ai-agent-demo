# M11-T3 交接：版本化内存缓存与批次暂时性重试

- 日期：2026-08-09，Asia/Shanghai
- 当前任务：`M11-T3 / in_progress`
- 内部步骤：第二离线纵切完成；在线 SDK Adapter/Settings 尚未完成
- 任务等级：B 类普通离线缓存与确定性 retry wrapper；时间盒 30–90 分钟
- 验证基线：`31479b8`（`feat: batch deterministic embeddings`）
- 工作区验证：`V-20260809-004/005`
- 关联决策：`ADR-0024`、`ADR-0023`、`ADR-0005`
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- 新增 `build_embedding_cache_key()`：规范化文本先做 SHA-256，metadata namespace 与 key version 再进入 canonical payload；公开 key 固定为 `embedding:v1:<sha256>`，原文 key 被拒绝。
- 新增线程安全且容量有界的 `InMemoryEmbeddingCache`。它复制向量、按 LRU 淘汰，只提供当前进程内命中，不宣称持久或跨进程一致性。
- `BatchingEmbeddingModel` 可选注入缓存：规范化重复输入只形成一个 miss，命中仍校验维度/有限值，所有 miss 批次成功后才写新缓存。后批失败或 retry 耗尽不写已成功前缀。
- 新增 `RetryableEmbeddingError`、`EmbeddingRetryExhaustedError` 与 `RetryingEmbeddingProvider`。wrapper 快照同一批次，只捕获显式暂时性错误，严格执行 `max_retries + 1` 次上限；协议、维度和 metadata 错误不重试。
- Batching Model 在 Provider 返回后立即复核 metadata，最终批次内发生的漂移也会 fail closed。
- PgVector、RAG、API、Container 和 M1 隔离接口未改；真实 pgvector 4 项继续通过。

## 验证摘要

- 恢复基线：知识/API 67 项、真实 pgvector 4 项、M1 10 项和连续性 52 个任务/96 个 Markdown 通过。
- 新增 11 个关键测试方法；Embedding 专项 21 项、最终 Embedding/PgVector/RAG/API/Container 78 项、真实 pgvector 4 项和 M1 10 项通过。
- 仅有既有 Starlette/httpx 弃用警告；没有新增测试 skip。
- 没有触发完整全仓门：无依赖、锁文件、Settings、migration、构建配置、跨前后端接口或多里程碑共享核心契约变化。
- 本 handoff 创建后连续性 52 个任务/97 个 Markdown 通过，`git diff --check` 退出 0；见 `V-20260809-005`。

## 修改文件

- 实现与导出：`backend/app/knowledge/embeddings.py`、`backend/app/knowledge/__init__.py`
- 测试：`backend/tests/test_embeddings.py`
- 后端规约：`BACKEND_CODING_STANDARDS.md`
- 连续性：`docs/implementation-plan.md`、`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff
- 没有修改 ADR、Settings、Container、数据库 migration、Compose、依赖或前端。
- handoff 写入时：上述文件均为本轮未提交改动；没有其他工作区改动。最终本地提交由结束时 `git log` 确认，下一份 verification/handoff 再记录新 HEAD。

## 失败尝试与复审修正

- 恢复时按推测文件名读取 ADR-0005 失败；随后用 `rg --files` 找到实际文件名，未发现文档漂移。
- 沙箱内启动 Compose 因 Docker config/named pipe 权限退出 1；使用用户已授权的本机 Docker 权限重跑同一 `--pull never` 命令后容器 healthy，没有下载镜像。
- 首次测试补丁插入在既有测试类中段，导致三个原测试方法归属到新类；在运行专项前检查文件结构并恢复正确类边界，没有丢失测试行为。
- 聚焦自审把 retry 输入改为不可变 batch 快照，并把“失败不缓存”用例收紧为第二批暂时性错误耗尽；同时让 cache key 格式校验引用同一版本常量。

## 未验证范围

- 没有显式在线 SDK Adapter、embedding-specific Settings/composition、Key 读取、Client 构造、Provider usage/费用或真实网络结果。
- 没有 Provider timeout、sleep/backoff 或并发请求限流；retry 只用于显式暂时性只读 Embedding batch，不能继承到工具、数据库或副作用。
- 内存缓存没有持久化、跨进程共享、TTL、外部失效协议或容量压测；进程退出即丢失。
- 三维 SHA-256 token-hash 只证明确定性工程路径，不证明语义质量、Provider tokenizer、Recall@K、MRR 或回答依据正确率；`KI-006` 保持 mitigated。
- integration Compose 仍是 localhost trust/tmpfs 测试环境，不是生产部署证据。

## 下一条原子动作

继续 `M11-T3` 第三个离线纵切，只实现显式在线 SDK Adapter 与 embedding-specific Settings/composition 的离线 fail-closed 构造合同：

- 先核对仓库已锁定 SDK 的公开 Embedding API 与现有 ADR-0005 Settings 风格；Adapter 接收显式 client/config，不自行读取环境或创建全局默认 client。
- 只有全局 `online=true` 与 embedding-specific provider/model/Key/预算同时合法时才允许 composition 注入；仅存在 Key、chat model 或 Provider 不启用 Embedding。
- 默认测试只使用离线 fake client 执行公开 Adapter 映射，覆盖缺配置、认证/配额/暂时性错误分类、维度/usage 边界和敏感信息不外泄。
- 不安装依赖、不读取真实 Key、不访问网络、不执行付费调用；真实 E4 仍需用户新的单次授权并由 M11-T7 记录。

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

预期知识/API 78 项、真实 pgvector 4 项、M1 10 项，以及连续性 52 个稳定任务/97 个 Markdown 通过。Compose 必须使用 `--pull never`；若固定 image 不在本机，未获新授权前不得下载。恢复一致后不要重做 M11-T2 或 M11-T3 前两个纵切，下一步只进入在线 Adapter/Settings 的离线 fail-closed 构造测试。
