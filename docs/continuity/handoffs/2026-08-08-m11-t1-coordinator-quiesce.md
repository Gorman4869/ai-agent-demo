# M11-T1 交接：Coordinator admission stop 与 active quiesce

- 日期：2026-08-08，Asia/Shanghai
- 当前任务：`M11-T1 / in_progress`
- 任务等级：A 类并发 admission、取消、资源关闭和持久结果未知恢复；时间盒 2–4 小时
- 第八纵切实现提交：`2e94640`（`feat: quiesce postgres run execution`）
- 工作区验证：`V-20260808-009`
- 关联决策：`ADR-0020`、`ADR-0019`、`ADR-0018`、`ADR-0017`、`ADR-0016`
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- `RunCoordinator` 增加 accepting/quiescing/quiesced 生命周期；进入 quiescing 后在 active lock 内拒绝新 execute/resume，并发 quiesce 共享同一 drain task。
- 宽限期内 active Runtime 自然完成并正常 terminal/release；超时后内部 `coordinator_shutdown` 取消并 await task、停止 heartbeat、保留 running+lease，不提交用户取消终态。
- 调用方取消 quiesce 时，内部 drain 完成后才传播 `CancelledError`。composition close 现固定 Coordinator、supervisor、persistence 顺序，不再读取 Coordinator 私有 task。
- 真实 PostgreSQL 证明自然完成期间 pool 保持可用；timeout 后旧 composition 关闭，审计读到 running、仅 `run.started`、lease 保留，新 composition 自动恢复 `run_orphaned`。

## 验证摘要

- 修改前恢复：PostgreSQL 84 项、composition 9 项、M1 10 项和连续性 52 个稳定任务/86 个 Markdown 通过。
- 最终 quiesce+composition 单元 18 项、真实 PostgreSQL 完整集 86 项、核心共享路径 164 项、API/Container/SDK 68 项、M1 隔离 10 项通过。
- 真实 composition 专项 3 项在实现提交前后均通过；不可达数据库 pool timeout、lease release/notifier 行和 Starlette 弃用提示均为既有预期输出。
- 首轮调用方取消用例在 quiesce 协程启动前立即取消，6 项中 5 项通过；改为等待 `quiescing` 后取消，最终 6 项通过。生产路径未因该夹具观察点失败。
- 本切片没有触发全量门；第五纵切的完整门继续引用 `V-20260808-002`/`003`。

## 修改文件

- 实现提交：`backend/app/services/run_coordinator.py`、`backend/app/postgres_execution.py`、`backend/tests/test_run_coordinator_quiesce.py`、`backend/tests/test_postgres_execution.py`、`backend/tests/postgres_store_integration.py`
- 决策/规约：`docs/continuity/decisions/ADR-0020-run-coordinator-quiesce.md`、`BACKEND_CODING_STANDARDS.md`
- 连续性：`docs/implementation-plan.md`、`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff

## 未验证范围

- timeout 是自然完成宽限期，不是硬终止上限。非协作 Runtime 若吞掉 task cancellation，quiesce 会继续等待；没有线程、子进程、网络请求或外部工具硬停止证据。
- admission stop 只覆盖 execute/resume 和 active execution。默认 HTTP/命令入口没有迁移，显式用户 cancel 等其他 Store 命令仍须应用 owner 在 close 前停止。
- 无 lease Coordinator 可自然 drain，但 timeout 后 running Run 的自动恢复证据只适用于显式 lease-aware PostgreSQL composition。
- PostgreSQL Approval/Memory 仍是同步 pool，async 线程隔离、取消、超时、耗尽和 close 等待未验证，`KI-023` 保持 open。
- lease、ToolExecution、Run/Event 与外部副作用仍是可收敛分离边界，不是 exactly-once。本地 trust/tmpfs 容器不是生产部署、跨主机、高可用或容量证据。

## 下一条原子动作

继续 `M11-T1`，只设计并实现同步 PostgreSQL `ApprovalStore`/`MemoryStore` 的 async 线程隔离与生命周期边界：不阻塞 event loop，调用方取消/超时不复用结果未知写操作，sync pool 耗尽返回稳定错误，composition close 等待 in-flight worker 后再关闭 sync pool。

本步骤仍不迁移默认 Container/HTTP/FastAPI lifespan，不新增部署配置，不进入 M11-T2 pgvector。不得把 `asyncio.to_thread` 的调用方取消描述成底层数据库调用已被硬取消，也不得对结果未知的审批/记忆写入自动重试。

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
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_run_coordinator_quiesce backend.tests.test_postgres_execution -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 PostgreSQL 86 项、quiesce+composition 18 项、M1 10 项以及连续性 52 个稳定任务/88 个 Markdown 通过。若一致，不要重做前八个纵切；下一步只进入同步 PostgreSQL Approval/Memory async 隔离。
