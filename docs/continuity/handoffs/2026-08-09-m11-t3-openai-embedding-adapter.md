# M11-T3 交接：显式 OpenAI Embedding Adapter 与离线验收

- 日期：2026-08-09，Asia/Shanghai
- 已验收任务：`M11-T3 / verified`
- 下一任务：`M11-T4 / planned`
- 任务等级：A 类共享 Settings/composition 与 secret gate；时间盒 2–4 小时
- 验证基线：`813c412`（`feat: cache and retry embeddings`）
- 工作区验证：`V-20260809-006/007`
- 关联决策：`ADR-0024`、`ADR-0023`、`ADR-0005`
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- 新增 `OpenAIEmbeddingProvider`，使用仓库已锁定 SDK 的公开 `client.embeddings.create()` API；显式接收 client factory、model、revision、dimensions 和 usage sink，不读取环境或创建全局 client。
- 按响应 index 恢复输入顺序；缺失、重复或越界索引、非法 usage、错误维度和值都 fail closed。空 Provider batch 返回空 tuple，不创建 SDK client。
- 新增按 batch 延迟创建并关闭的 OpenAI Client Factory，固定 SDK `max_retries=0` 和请求 timeout。共享 `RetryingEmbeddingProvider` 是唯一重试所有者；连接/服务端暂时性错误可重试，认证、权限、配额/限流、请求和协议错误不重试。
- 新增 `EmbeddingSettings` 与环境示例：默认 offline；只有全局 online、embedding provider/model/revision 和共享 SecretStr Key 全部合法时允许在线 composition。安全摘要与 Container repr 不暴露标签原值或秘密。
- `ApplicationContainer` 默认组装确定性离线 Embedding Model，也允许显式注入；在线配置只组装延迟 Client Factory，构造阶段不会创建 SDK client 或网络请求。
- 新增 12 个关键测试方法或等价覆盖，使用真实 OpenAI SDK + `httpx.MockTransport` 执行请求/响应协议、usage、错误分类、重试、缓存、资源关闭和秘密边界。MockTransport 不是在线 Provider 证据。

## 验证摘要

- 恢复基线：知识/API 78 项、真实 pgvector 4 项、M1 10 项和连续性 52 个任务/97 个 Markdown 通过。
- 最终聚焦 67 项、共享契约定向 160 项、真实 pgvector 4 项和 M1 隔离 10 项通过。
- 共享 Settings/Container 变化触发完整离线门：后端 505 项通过、1 项既有 Windows symlink 能力跳过；Code Agent、依赖、Vue、MCP TypeScript 与 Compose 配置通过。
- 首次完整门仅因沙箱阻止写 Vue `tsconfig.app.tsbuildinfo` 报 `TS5033/EPERM`；同一命令在获准环境退出 0。只有既有 Starlette/httpx 弃用警告。
- 没有读取真实 Key、访问网络 Provider 或产生费用；完整命令和失败事实见 `V-20260809-006`。

## 修改文件

- Adapter 与领域导出：`backend/app/knowledge/openai_embeddings.py`、`backend/app/knowledge/embeddings.py`、`backend/app/knowledge/__init__.py`
- 配置与 composition：`backend/app/settings.py`、`backend/app/container.py`、`backend/.env.example`
- 测试：`backend/tests/test_openai_embeddings.py`、`backend/tests/test_settings.py`、`backend/tests/test_container.py`
- 后端规约：`BACKEND_CODING_STANDARDS.md`
- 连续性：`docs/implementation-plan.md`、`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff
- 没有修改 ADR、数据库 migration、Compose、依赖/锁文件、前端或 HTTP 契约。
- handoff 写入时上述文件均为本轮未提交改动，没有发现任务外改动。最终本地提交由结束时 `git log` 确认，下一份 verification/handoff 再记录新 HEAD。

## 失败尝试与复审修正

- 仓库根目录没有 `.env.example`；用 `rg --files` 定位到实际 `backend/.env.example` 后更新，不是仓库漂移。
- 沙箱内 Docker 状态检查无法读取用户 Docker config/named pipe；同一 `--pull never` 命令在获准权限下容器 healthy，没有下载镜像。
- 首次完整门后端 505 项已经通过，但 Vue 因沙箱禁止写 `tsconfig.app.tsbuildinfo` 退出 1；获准重跑同一完整脚本后所有阶段通过。
- 聚焦复审发现直接调用 Provider 的空 batch 仍会进入 SDK；已补空批零 Client 保护和回归，最终聚焦 67 项通过。

## 未验证范围

- 没有真实在线 Embedding、Provider 模型/维度可用性、真实 tokenizer/usage/账单或费用证据。M11-T7 必须取得新的单次明确授权后才能执行在线 E4。
- usage 只有注入 sink 的单批 token 计数，没有版本化定价、费用计算、持久账本或跨批预算强制。
- 内存缓存没有持久化、跨进程共享、TTL、失效协议或容量压测；retry 没有 sleep/backoff 或并发限流，不得复用于副作用。
- 三维离线 Provider、SDK MockTransport 和真实 pgvector CRUD 不证明语义质量或固定 RAG 指标；`KI-006` 保持 mitigated，由 M11-T6 固定评测集关闭。
- integration Compose 仍是 localhost trust/tmpfs 测试环境，不是生产部署证据。

## 下一条原子动作

开始 `M11-T4` 第一个离线纵切，只固定 ContextAssembler 的最小领域合同：

- 先定义有界上下文片段及 `system/recent/summary/memory/rag/skill` 来源标记，不接真实模型。
- 固定服务器拥有的确定性优先级、每来源预算、总预算和可解释预算报告；超预算 fail closed，不静默丢弃高优先级系统约束。
- 用最小纵切证明系统约束和一条关键事实可在裁剪后保留，并覆盖空输入、恶意检索指令隔离、不同用户来源隔离和摘要失败边界。
- 不实现 M11-T5 的持久记忆写入/纠正 API，不创建 M11-T6 的 50 条评测集，不读取 Key、不执行网络或付费调用。

## 恢复命令

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_openai_embeddings backend.tests.test_embeddings backend.tests.test_pgvector backend.tests.test_rag backend.tests.test_settings backend.tests.test_container backend.tests.test_application_lifecycle backend.tests.test_api backend.tests.test_openai_agents_runtime backend.tests.test_online_smoke -q
docker compose -f deploy/compose.integration.yaml up -d --wait --pull never
$env:AI_AGENT_TEST_PGVECTOR_DSN = "postgresql://ai_agent@127.0.0.1:55433/ai_agent_integration?sslmode=disable"
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.pgvector_integration -q
$testExit = $LASTEXITCODE
Remove-Item Env:\AI_AGENT_TEST_PGVECTOR_DSN -ErrorAction SilentlyContinue
if ($testExit -ne 0) { exit $testExit }
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期共享契约定向 160 项、真实 pgvector 4 项、M1 10 项，以及连续性 52 个稳定任务/98 个 Markdown 通过。Compose 必须使用 `--pull never`；若固定 image 不在本机，未获新授权前不得下载。恢复一致后不要重做 M11-T1–T3，下一步只进入 M11-T4 第一个离线纵切。
