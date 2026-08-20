# M11-T5 第六纵切交接：长期事实 version CAS 与追加式审计

- 日期：2026-08-20
- 任务：`M11-T5 / in_progress`
- 验证基线：`7954c23`
- 实现提交：待本轮 Git 固定
- 主要证据：`V-20260820-005/006`、`ADR-0028`

## 已完成

- 新增冻结、repr-safe 的 `CorrectMemoryFact`、`DeleteMemoryFact`、`DeleteMemoryFactResult`、`MemoryFactAuditRecord` 和稳定 `memory_fact_conflict` / `memory_fact_not_found` 错误。事实从 version 0 开始，纠正继续要求批准且只改 value，删除按 owner + expected version 执行。
- 内存 Memory Store 用单一事实锁完成 CAS、tombstone 和审计追加；PostgreSQL 用 `SELECT FOR UPDATE` 和单一 sync-pool 事务提交事实状态与审计。删除清空 key/value，active `facts()` 不再返回 tombstone。
- migration 6 增加 version/deleted_at、事实 tombstone 约束和 `(fact_id, version)` 审计表；现存旧事实回填 created/version 0，普通 audit UPDATE/DELETE 由 trigger 拒绝。
- 兼容 `remember()`/`forget()` 继续服务现有 HTTP，同时写 created/deleted audit；HTTP、前端、Runtime 和默认长期事实写入策略没有修改。
- Context 纵切证明纠正后只注入新值，删除后不再注入；四个独立 PID 完成 create→correct→delete→audit，并只输出版本、动作和摘要有效性。

## 修改文件

- `backend/app/memory/__init__.py`
- `backend/app/memory/store.py`
- `backend/app/memory/postgres.py`
- `backend/app/stores/async_facade.py`
- `backend/app/stores/postgres_async.py`
- `backend/app/stores/postgres_fact_audit_probe.py`
- `backend/migrations/0006_memory_fact_version_audit.sql`
- `backend/tests/test_memory_store_contract.py`
- `backend/tests/test_context_collector.py`
- `backend/tests/postgres_store_integration.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/continuity/decisions/ADR-0028-versioned-memory-fact-audit.md`
- `docs/continuity/status.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-08-20-m11-t5-versioned-fact-audit.md`

## 验证快照

- Memory Store 与 Context collector 最终 26 项通过；扩大 Context/Memory/bridge/Runtime/Container/API/Coordinator 离线回归 156 项通过。
- 完整真实 PostgreSQL integration 109 项通过；四 PID fact audit probe 独立 1 项通过。不可达数据库负向用例的有界 timeout 日志为预期。
- 完整门后端 597 项通过、1 项既有 Windows symlink 能力跳过；受控 Code Agent、Python 依赖、Vue、MCP TypeScript 与 Compose 配置全部通过。
- M1 `python -S` 隔离 10 项通过；连续性和 `git diff --check` 见 `V-20260820-006`。

## 未验证与边界

- SHA-256 digest 不加密事实；低熵 value 可能被猜测。数据库 trigger 只阻止普通 UPDATE/DELETE，DB owner 可禁用 trigger 或 TRUNCATE，不能宣称外部防篡改账本。
- migration 6 只能回填迁移时仍存在的事实；此前被物理删除的历史无法恢复。当前纠正只允许改变 value，key/scope 不可变。
- async bridge 的 timeout/取消/连接断开仍可能 result-unknown。可以读取当前 version/audit 仲裁，但命令没有 mutation idempotency key，禁止自动重试。
- 既有 HTTP delete 仍是兼容入口，不要求客户端提交 expected version；新的 CAS correction/delete/audit 尚未暴露为公开 API。没有修改前端、在线摘要、Provider、Token/usage 或费用。
- 本地 PostgreSQL 使用 localhost trust 与 tmpfs，只是 integration 证据，不代表生产鉴权、加密、备份、WAL、防篡改或灾备。

## 失败与警告

- 单独启动四进程用例时，新 PowerShell 首次未配置 `AI_AGENT_TEST_POSTGRES_DSN`，因此 0 项执行、1 项跳过；补入仓库本地 trust/tmpfs DSN 后同一用例 1 项通过。跳过没有计入成功证据。
- 完整门只有既有 Starlette/httpx deprecation warning 与 Windows symlink 条件跳过；没有新增失败。
- 工作区文件存在 Git 的 LF→CRLF 提示，`git diff --check` 无 whitespace 错误。

## 下一条原子动作

只开始 M11-T5 第七纵切：在可信 owner 边界上为长期事实增加异步读取、version CAS correction/delete 与 audit HTTP API，保留既有 create/delete 兼容响应并固定 401/403/404/409 与内容脱敏；用默认内存和 opt-in PostgreSQL application lifespan 验证纠正后下一 Run 读取新值、删除后不再注入和跨 lifespan 恢复。不修改前端，不进入 M11-T6。

## 恢复命令

```powershell
git status --short
git log -5 --oneline
node --version
docker compose -f deploy/compose.integration.yaml ps
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_memory_store_contract backend.tests.test_context_collector -v
$env:AI_AGENT_TEST_POSTGRES_DSN='postgresql://ai_agent@127.0.0.1:55433/ai_agent_integration'
.\.venv\Scripts\python.exe -B -m unittest backend.tests.postgres_store_integration.PostgresMemoryFactAuditProcessTest -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 Node 至少为 18；当前验证版本为 22.16.0。若关键 26 项、四进程 1 项和连续性一致，不要重做 M11-T1–T4 或 M11-T5 前六纵切。
