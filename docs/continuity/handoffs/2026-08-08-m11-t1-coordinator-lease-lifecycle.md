# M11-T1 交接：显式 RunCoordinator lease 生命周期

- 日期：2026-08-08，Asia/Shanghai
- 当前任务：`M11-T1 / in_progress`
- 任务等级：A 类并发、持久化、取消和公共 Store 契约；时间盒 2–4 小时
- 第五纵切实现提交：`003c7be`（`feat: coordinate runs with postgres leases`）
- 恢复/漂移：`V-20260808-001`
- 工作区验证：`V-20260808-002`
- 提交后恢复：`V-20260808-003`
- 连续性闭环：`V-20260808-004`
- 关联决策：`ADR-0017`、`ADR-0016`
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- `RunLeaseStore.reserve_execution()` 只接受 owned `queued` 或 `waiting_approval` 的精确前置状态；既有 `acquire()` 继续只允许 running。内存与 PostgreSQL 适配器运行同一新增合同，migration 不变。
- 显式注入 lease 的 Coordinator 先 reservation，再提交 `run.started`/`run.resumed`，随后启动串行 heartbeat。Runtime 结束时先停止 heartbeat，再 durable pause/terminal，最后 release；cancel 同样先停 heartbeat、提交 cancelled，再 release。
- heartbeat `run_lease_lost` 或 `store_unavailable` 会取消 Runtime 并保留 running Run，不由失去执行权的旧 Coordinator 伪造终态。若已有 terminal/waiting durable winner 则读取赢家。
- start/resume 提交结果未知时保留 reservation；scanner 可根据实际状态清理 queued/waiting lease，或把 running Run 收敛为 `run_orphaned`。durable 状态提交后的 release 失败不回滚状态，陈旧 lease 等待 scanner。
- 真实 PostgreSQL Coordinator 证明 heartbeat version 推进和 terminal release；数据库强制过期后 Coordinator fail closed，现有 `RunRecoveryService` 随后完成 `run_orphaned`。

## 验证摘要

- PostgreSQL 完整集：82 项通过，包含 13 项共享 lease 合同和 2 项真实 Coordinator 纵切；不可达数据库负向用例的 pool timeout 为预期输出。
- 核心 Run/Store/Coordinator/LangGraph：134 项通过；API/Container/OpenAI SDK/framework runtime：68 项通过。
- 公共 Store 契约触发完整门：后端 410 项通过、1 项既有 Windows symlink 跳过；Code Agent、依赖、Vue、MCP TypeScript 和 Compose 配置通过。
- M1 在禁用 `site-packages` 后当前 10 项通过；`beefc1a` 比旧 handoff 新增 3 项学习者用例，已由 `KI-024`/`V-20260808-001` 登记，不是 M11 回归。
- 完整门沙箱首轮在 Vue `tsconfig.app.tsbuildinfo` 以 `TS5033`/`EPERM` 失败；同一脚本获工作区构建权限后退出 0。两次事实均保留。

## 失败尝试与复审修正

- `py_compile` 尝试写 `__pycache__` 被拒绝；不落盘 `compile()` syntax-ok。没有为测试修改权限或源码行为。
- PostgreSQL lease-lost 夹具首次只回拨 `expires_at`，正确触发 migration 的时间顺序 CHECK；改为保持 acquired < heartbeat < expires 的三个过期时间点后 15 项通过，没有放宽数据库约束。
- 新增双 Coordinator 用例发现 lease-aware 后到者在 Run 已 running 时沿用旧非法转换；修正为只在显式 lease 模式等待 durable winner，未注入 lease 的旧语义不变。
- 聚焦复审发现 cancel 两次 CAS 冲突后的尾部分支可能漏 release；已在读到 terminal 时补 release，并重跑定向与完整门。

## 修改文件

- 代码：`backend/app/services/run_coordinator.py`、`backend/app/stores/run_lease.py`、`backend/app/stores/memory.py`、`backend/app/stores/postgres_run_lease.py`
- 测试：`backend/tests/test_run_coordinator.py`、`backend/tests/test_run_lease_store_contract.py`、`backend/tests/postgres_store_integration.py`
- 决策/规约：`docs/continuity/decisions/ADR-0017-coordinator-run-lease-lifecycle.md`、`BACKEND_CODING_STANDARDS.md`
- 连续性：`docs/implementation-plan.md`、`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff

## 未验证范围

- 默认 Container/HTTP 未注入 PostgreSQL persistence 或 lease-aware Coordinator；没有应用 lifespan scanner、统一应用进程重启或定时恢复调度。
- PostgreSQL Approval/Memory 仍是同步 pool；未验证 async 线程隔离、取消、超时、pool 耗尽或跨 pool 原子性，`KI-023` 保持 open。
- lease 不能把外部副作用与数据库组成 exactly-once；running ToolExecution 结果未知仍只能 terminal unknown。
- 本地 Compose 是 localhost trust/tmpfs 测试实例，不是生产鉴权、TLS、持久卷、备份、高可用、跨主机或容量证据。

## 下一条原子动作

继续 `M11-T1`，只设计并实现显式 `RunRecoverySupervisor`（名称可按现有风格调整）：固定单进程 start/close、禁止同一 supervisor 重叠 scan、周期等待、取消/关闭清理，以及一轮 StoreError 后下一周期仍可收敛。使用现有 `RunRecoveryService`，不要重复实现恢复规则。

本原子步骤仍不迁移默认 Container/HTTP，不处理同步 Approval/Memory async 边界，不增加生产部署配置，也不进入 M11-T2 pgvector。

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
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 PostgreSQL 82 项、M1 10 项、连续性 52 个稳定任务/82 个 Markdown 通过。若一致，不要重做前五个纵切；下一步只进入显式 scanner 调度生命周期。
