# M11-T5 原子回合发布第五纵切交接

- 时间：2026-08-20 10:08，Asia/Shanghai
- 当前任务：`M11-T5 / in_progress`
- 验证基线：`8fe9ef8`
- 第四纵切实现提交：`8fe9ef8`
- 第五纵切实现提交：待本轮 Git 固定
- 证据：`V-20260820-003/004`
- 设计：`ADR-0027`
- 任务等级：A 类 persistence/migration/concurrency 边界；2–4 小时时间盒

## 已完成

- 新增冻结、repr-safe 的 `PublishTurn`/`PublishTurnResult` 与稳定 `memory_turn_conflict`。Run ID 作为幂等键，版本化 digest 绑定隐藏 session 与 plain user/assistant；相同 binding replay 不重复，改变 binding fail closed。
- 同步/异步 Memory Store 暴露同一 command。内存实现用锁原子维护消息窗口与只含 session/digest 的账本；PostgreSQL migration 5 在一个 sync-pool 事务中维护 publication ledger、两个 sequence、两条消息与窗口裁剪。
- `RunCoordinator` 主 Run 不再串行 append。新 completed terminal 在通知前发布；读取到既有 completed Run 时不调用 Runtime，只重放同一 command，因此能补写 terminal 后缺口。
- 内存/PostgreSQL 共同合同覆盖 replay、conflict、并发、窗口和输入拒绝。真实 PostgreSQL trigger 证明 assistant 失败不留下 user、ledger 或 sequence；retry 可成功。
- 两个 PID 的真实探针证明：进程 A 只留下 completed Run/零消息，进程 B 以新 composition replay 两次后恰好两条消息且 Runtime 零调用。

## 修改文件

- `backend/app/memory/__init__.py`
- `backend/app/memory/store.py`
- `backend/app/memory/postgres.py`
- `backend/app/services/run_coordinator.py`
- `backend/app/stores/async_facade.py`
- `backend/app/stores/postgres_async.py`
- `backend/app/stores/postgres_state_probe.py`
- `backend/app/stores/postgres_turn_replay_probe.py`
- `backend/migrations/0005_conversation_turn_publications.sql`
- `backend/tests/test_memory_store_contract.py`
- `backend/tests/test_postgres_async_stores.py`
- `backend/tests/test_run_coordinator.py`
- `backend/tests/postgres_store_integration.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/continuity/decisions/ADR-0027-atomic-conversation-turn-publication.md`
- `docs/continuity/status.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-08-20-m11-t5-atomic-turn-publication.md`

## 验证快照

- 恢复基线：第四纵切关键 76 项、连续性 52/109 通过；Node 22.16.0。
- 最终离线关键集合 95 项；真实 PostgreSQL 定向 19 项；独立跨进程 replay 1 项。
- 完整真实 PostgreSQL integration 99 项通过。
- 完整离线门：后端 591 项通过、1 项既有 Windows symlink 能力跳过；Code Agent、依赖、Vue、MCP TypeScript 与 Compose 配置全部通过。
- M1 `python -S` 隔离 10 项通过；`git diff --check` 通过。

## 未验证与边界

- Run/Event terminal 与 Memory turn 分属 async/sync pool，不共享事务；不能宣称跨 Store 或外部 exactly-once。
- terminal 缺口只在后续 execute/resume 时修复，没有后台 scanner；publication ledger 尚无生产归档/GC，不能在 Run 仍可能 replay 时删除。
- 短期窗口仍按 message 条数裁剪；极小奇数窗口可只保留回合尾部，这不改变两条消息的原子插入事实。
- 尚未实现 approved long-term fact correction/delete、version CAS、append-only audit、在线摘要、Provider 或 RAG 固定评测。
- 本地 PostgreSQL 使用 trust、localhost 和 tmpfs，只是课程 integration 证据；未读取 Key、产生费用、安装依赖、配置 remote 或执行 push。

## 失败尝试

- `compileall` 因沙箱拒绝写既有 `__pycache__` 返回 1；同一模块随后由 unittest 导入并执行，没有把环境失败伪报为代码通过。
- 首轮真实 PostgreSQL 18 项中 1 项旧损坏 migration fixture 硬编码 version 5，与新 migration 5 冲突；fixture 改为根据实际 migration 数量生成下一版本后，定向 19 项和完整 99 项均通过。
- 首轮实现让内存账本保存完整 command 且缺少统一锁；聚焦复审后改为只保存 session/digest 并锁住消息窗口/账本，再完成全部最终验证。

## 下一条原子动作

只开始 M11-T5 第六纵切：为 approved long-term fact 增加 version CAS correction/delete 与 append-only audit，先定义内存/PostgreSQL 共同 Store 合同、稳定冲突语义和 migration，再用真实 PostgreSQL 验证并发版本冲突、审计不可变与重启读取。保持 PublishTurn、Context 读取、默认 Container、HTTP 和前端不变；不提前进入 M11-T6。

## 恢复命令

```powershell
git status --short
git log -5 --oneline
node --version
docker compose -f deploy/compose.integration.yaml ps
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_memory_store_contract backend.tests.test_postgres_async_stores backend.tests.test_run_coordinator -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.postgres_store_integration.PostgresMemoryTurnReplayProcessTest -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 Node 至少为 18；当前验证版本为 22.16.0。恢复后先确认本地 integration PostgreSQL 仍 healthy；若关键集合、跨进程 probe 和连续性一致，不要重做 M11-T1–T4 或 M11-T5 前五纵切。
