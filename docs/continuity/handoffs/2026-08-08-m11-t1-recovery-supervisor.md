# M11-T1 交接：显式 recovery supervisor 调度生命周期

- 日期：2026-08-08，Asia/Shanghai
- 当前任务：`M11-T1 / in_progress`
- 任务等级：A 类并发、持久恢复、取消和后台任务生命周期；时间盒 2–4 小时
- 第六纵切实现提交：`e63d718`（`feat: schedule postgres run recovery`）
- 工作区验证：`V-20260808-005`
- 连续性闭环：`V-20260808-006`
- 关联决策：`ADR-0018`、`ADR-0017`、`ADR-0016`
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- 新增显式 `RunRecoverySupervisor`，每个实例只拥有一个命名后台 task；启动后立即执行首轮 `RunRecoveryService.scan_once()`，上一轮返回后才等待下一周期，同一实例不会重叠扫描。
- 生命周期固定为 created/running/closing/failed/closed。running 状态重复 start 幂等，closing/closed/failed 拒绝启动；close 取消并 await task，调用方取消 close 时继续传播 `CancelledError`。
- claim 阶段 `StoreError` 和单 Run `FAILED` 只记录稳定 error code，下一周期继续；非 Store 程序错误把 supervisor 置为 failed 并在 close 时重新抛出。
- scan limit 与 recovery TTL 在构造阶段按 lease Store 合同校验，非法配置不会延迟到后台 task。
- 真实 PostgreSQL supervisor 自动 claim 强制过期的 execution lease，把 running Run 提交为 `run_orphaned`，释放 recovery lease 后关闭；该用例没有手动调用 scanner。

## 验证摘要

- 修改前恢复：PostgreSQL 82 项、M1 10 项、连续性 52 个稳定任务/82 个 Markdown 通过。
- 最终 recovery/supervisor 单元集 14 项通过，覆盖无重叠、参数传递、重复 start、in-flight 取消清理、长周期关闭、调用方取消、claim/item Store 故障续跑、程序错误、关闭后拒绝重启和配置上限。
- 真实 PostgreSQL 完整集 83 项通过；不可达数据库负向 pool timeout 为预期输出。核心 Run/Store/Coordinator/recovery/LangGraph 154 项通过，M1 隔离 10 项通过。
- 提交 `e63d718` 后，14 项 supervisor/recovery 单元集和 PostgreSQL 自动恢复单例再次通过。
- 本轮未触发全量门：没有依赖、migration、公共 Store Protocol、默认 composition、HTTP 或跨前后端契约变化，也不是里程碑验收/发布门。第五纵切全量门证据继续引用 `V-20260808-002`/`003`。

## 失败尝试与复审修正

- 首轮长周期关闭测试错误等待第二次 scan，30 ms 内按设计不会发生；改为等待首轮完成后验证 close 中断 30 秒 interval，13 项通过。
- PostgreSQL 自动恢复单例首次只等待 Run `failed` 就关闭 supervisor，取消了终态提交之后仍在执行的 lease release，留下可收敛陈旧 lease 并触发 psycopg rollback 清理警告。用例改为等待终态与 lease 删除同时可见，证明完整自动恢复后通过；没有合并分离事务或放宽恢复边界。
- 聚焦复审发现 close 自身被取消可能误吞调用方 `CancelledError`、closing 期间 start 可能假成功，以及 limit/TTL 上限可能延迟到后台失败；三处均补合同并通过最终回归。
- 首次 `git add` 因沙箱拒绝 `.git/index.lock` 写入失败；获得本地 Git 写权限后只暂存三个实现/测试文件并创建 `e63d718`，没有修改源码行为或 Git 历史。

## 修改文件

- 实现提交：`backend/app/services/run_recovery_supervisor.py`、`backend/tests/test_run_recovery_supervisor.py`、`backend/tests/postgres_store_integration.py`
- 决策/规约：`docs/continuity/decisions/ADR-0018-explicit-run-recovery-supervisor.md`、`BACKEND_CODING_STANDARDS.md`
- 连续性：`docs/implementation-plan.md`、`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff

## 未验证范围

- supervisor 仍由调用方显式 start/close；默认 `ApplicationContainer`、`create_app()` 和 FastAPI lifespan 没有 PostgreSQL persistence、lease-aware Coordinator 或 scanner 调度。
- 没有用统一 composition 启动新应用进程并自动恢复旧进程 orphan；本轮真实 PostgreSQL E3 只在一个测试进程内证明调度链。
- shutdown 取消 in-flight scan 时，已提交的 ToolExecution/Run/Event 和陈旧 recovery lease 依赖下一次过期扫描继续收敛；没有证明任意驱动/网络中断点都立即清理。
- PostgreSQL Approval/Memory 仍是同步 pool；未验证 async 线程隔离、取消、超时、pool 耗尽或跨 pool 原子性，`KI-023` 保持 open。
- lease 与 supervisor 不能把外部副作用和数据库组成 exactly-once。本地 Compose 仍是 localhost trust/tmpfs 测试实例，不是生产部署证据。

## 下一条原子动作

继续 `M11-T1`，只设计并实现显式 PostgreSQL execution composition 生命周期：一个 owner 按 `PostgresPersistence.open/setup -> lease-aware RunCoordinator + RunRecoveryService/RunRecoverySupervisor -> supervisor.start` 启动，并固定 `supervisor.close -> persistence.close` 的关闭顺序；用 PID 不同的旧 holder 与新 composition 进程证明启动后自动收敛 orphan。

本原子步骤仍不迁移默认 Container/HTTP/FastAPI lifespan，不调用同步 PostgreSQL Approval/Memory，不新增部署配置，也不进入 M11-T2 pgvector。

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
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_run_recovery backend.tests.test_run_recovery_supervisor -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 PostgreSQL 83 项、recovery/supervisor 14 项、M1 10 项、连续性 52 个稳定任务/84 个 Markdown 通过。若一致，不要重做前六个纵切；下一步只进入显式 PostgreSQL execution composition 生命周期。
