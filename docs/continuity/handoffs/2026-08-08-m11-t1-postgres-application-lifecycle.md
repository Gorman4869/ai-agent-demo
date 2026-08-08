# M11-T1 交接：PostgreSQL application lifecycle 与任务验收

- 日期：2026-08-08，Asia/Shanghai
- 已验收任务：`M11-T1 / verified`
- 当前任务：`M11-T2 / planned`
- 任务等级：A 类默认 composition、数据库生命周期、HTTP/命令 admission 与 async/sync I/O 边界；时间盒 2–4 小时
- 第十纵切实现提交：`be2c818`（`feat: compose postgres application lifecycle`）
- 工作区验证：`V-20260808-013`
- 连续性闭环：`V-20260808-014`
- 关联决策：`ADR-0022`、`ADR-0021`、`ADR-0020`、`ADR-0019`
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- `AI_AGENT_PERSISTENCE` 默认 `memory`；只有显式选择 `postgres` 且提供可解析的脱敏 DSN 才打开数据库。DSN 单独存在不启用 PostgreSQL，缺失或无效配置 fail closed，不回退内存。
- `ApplicationContainer.create()` 保持同步内存组合；`await ApplicationContainer.open()` 打开真实 `PostgresExecutionComposition`，并绑定 Run/Event Store、lease-aware Coordinator、Approval/Memory compatibility Store 与 async façade。
- FastAPI lifespan 延迟打开 PostgreSQL，启动顺序为 composition、MCP、admission；关闭顺序为完整 HTTP/command drain、composition、MCP。纯 ASGI middleware 持有 admission 直到 StreamingResponse body 结束。
- memory HTTP 与 application approval 只使用 async façade。默认内存模式使用本地 async wrapper；legacy Run HTTP/SSE 仍使用 `InMemoryRunService` 且不向 durable Store 双写，统一 API 留给 M12。
- M11-T1 的十个真实纵切已覆盖 migration、持久 Store/checkpointer、ToolExecution、lease/recovery、composition/quiesce、sync bridge 与默认 opt-in application lifecycle，任务更新为 `verified`。

## 验证摘要

- 修改前恢复：PostgreSQL 89 项、async bridge 9 项、quiesce+composition 18 项、M1 10 项和连续性 52 个稳定任务/90 个 Markdown 通过。
- 最终真实 PostgreSQL 完整集 91 项、受影响定向回归 98 项通过；两个 FastAPI lifespan 跨应用写入并删除同一 fact，Container Approval façade 实际 grant/consume。
- 最终完整门后端 463 项通过、1 项既有 Windows symlink 能力跳过；Code Agent、`pip check`、Vue、MCP TypeScript 和 Compose 配置均通过。M1 隔离 10 项通过。
- 实现提交后，Settings/lifecycle/Container/API 63 项和真实 PostgreSQL application 专项 2 项再次通过。
- 首轮完整门遇到一次 MCP E2E 5 秒启动抖动，单独 4 项立即通过；第二轮因沙箱拒绝写 Vue tsbuildinfo 退出。相同完整门在工作区写权限下通过，ASGI admission 复审后又完整通过；失败事实未删除。

## 修改文件

- 实现提交：`backend/.env.example`、`backend/app/application_lifecycle.py`、`backend/app/container.py`、`backend/app/main.py`、`backend/app/security/identity.py`、`backend/app/settings.py`、`backend/app/stores/__init__.py`、`backend/app/stores/async_facade.py` 及关联测试。
- 决策/规约：`docs/continuity/decisions/ADR-0022-postgres-application-lifecycle.md`、`BACKEND_CODING_STANDARDS.md`
- 连续性：`docs/implementation-plan.md`、`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff
- handoff 写入时：实现提交已固定；上述连续性文档等待本轮本地文档提交，不包含其他工作区改动。

## 未验证范围

- 旧 Run HTTP/SSE 没有迁移到 durable Coordinator；统一 Run、审批、取消、事件和断点续传 API 属于 M12。
- 显式同步 Approval/Memory compatibility 调用不受 bridge 或 application admission 追踪；绕过默认 async 路径的调用方必须自行停止再关闭。
- running PostgreSQL worker 无法硬取消，结果未知的有副作用写操作不得自动重试。跨 pool/外部系统事务与 exactly-once 不成立。
- Windows application host 仍须在创建 event loop 前选择 Selector policy；没有新增通用生产启动脚本，也没有硬进程终止证据。
- localhost trust/tmpfs PostgreSQL 不是生产鉴权、TLS、持久卷、备份、高可用、容量或跨主机证据。

## 下一条原子动作

进入 `M11-T2` 首个 A 类纵切，只审计并实现真实 pgvector 的最小闭环：

- 先核对现有 `PgVectorKnowledgeBase`、PostgreSQL image/extension、migration 与表/索引边界，并用新 ADR 固定维度、距离函数和 seed 所有权。
- 只实现真实 pgvector migration、最小插入/替换/删除/相似度检索及维度错误、事务回滚测试；不得把 extension import 或 Fake Connection 当完成证据。
- 默认离线、无 Key、费用 0；不得安装依赖、执行在线 Embedding、改生产 Compose、进入 M11-T3 或扩大到 M12 API。

## 恢复命令

```powershell
git status --short
git log -6 --oneline
docker exec ai-agent-demo-m11-postgres-1 pg_isready -U ai_agent -d ai_agent_test
$env:AI_AGENT_TEST_POSTGRES_DSN = "postgresql://ai_agent@127.0.0.1:55432/ai_agent_test?sslmode=disable"
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.postgres_store_integration -q
$testExit = $LASTEXITCODE
Remove-Item Env:\AI_AGENT_TEST_POSTGRES_DSN -ErrorAction SilentlyContinue
if ($testExit -ne 0) { exit $testExit }
.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_settings backend.tests.test_application_lifecycle backend.tests.test_container backend.tests.test_api -q
$env:AI_AGENT_TEST_POSTGRES_DSN = "postgresql://ai_agent@127.0.0.1:55432/ai_agent_test?sslmode=disable"
.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.postgres_store_integration.PostgresFastApiApplicationTest backend.tests.postgres_store_integration.PostgresApplicationContainerTest -q
$testExit = $LASTEXITCODE
Remove-Item Env:\AI_AGENT_TEST_POSTGRES_DSN -ErrorAction SilentlyContinue
if ($testExit -ne 0) { exit $testExit }
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 PostgreSQL 91 项、默认路径 63 项、真实 PostgreSQL application 专项 2 项、M1 10 项以及连续性 52 个稳定任务/92 个 Markdown 通过。若一致，不要重做 M11-T1；下一步只进入 M11-T2 的真实 pgvector 最小纵切。
