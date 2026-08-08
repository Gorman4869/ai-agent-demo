# ADR-0017：RunCoordinator 前置租约保留与心跳生命周期

- 状态：accepted
- 日期：2026-08-08
- 任务：`M11-T1`
- 依赖：`ADR-0006`、`ADR-0007`、`ADR-0012`、`ADR-0016`

## 背景

`ADR-0016` 的普通 `acquire()` 只允许 running Run。若 Coordinator 先提交 `run.started` 再 acquire，进程可能在两步之间退出，留下没有 lease row 的 running Run；现有 scanner 只能扫描过期 lease，无法发现这种孤儿。反过来直接允许普通 executor 抢占 running Run，又会破坏结果未知时不自动重放副作用的结论。

审批恢复存在同类窗口：`run.resumed` 提交后到 acquire 之前退出，会留下没有可扫描执行凭证的 running Run。需要在不迁移默认 Container/HTTP、不合并 Approval 同步线程边界的前提下，固定显式 Coordinator 的最小安全顺序。

## 决策

### 1. 增加受限的 execution reservation

`RunLeaseStore` 增加 `reserve_execution()`，只接受服务端传入的精确前置状态：首次执行为 `queued`，审批恢复为 `waiting_approval`。Store 必须锁定 owned Run、验证状态且确认不存在任何 lease 后，创建 mode=`execution` 的 opaque token/version 0 租约。

既有 `acquire()` 继续只允许 running Run，普通 executor 仍不能覆盖 active 或 expired lease。reservation 复用 `0004_run_leases.sql`，不增加 migration；它只是让 execution lease 在生命周期提交前短暂存在。若进程在提交前退出，scanner 轮换 recovery token，`RunRecoveryService` 看到非 running Run 后只释放租约，不伪造失败，Run 仍可由后续明确请求重试。

### 2. 固定 start 与 resume 的顺序

显式注入 lease 的 Coordinator 使用以下顺序：

```text
reserve queued
  -> commit_start(run.started)
  -> heartbeat
  -> Runtime
  -> stop heartbeat
  -> commit_pause 或 commit_terminal
  -> release

reserve waiting_approval
  -> resolve approval
  -> commit_resume(run.resumed)
  -> heartbeat
  -> Runtime.resume
  -> stop heartbeat
  -> commit_pause 或 commit_terminal
  -> release
```

生命周期提交出现明确 CAS 冲突时释放本次 reservation 并读取 durable winner。StoreError、取消或连接结果未知发生在 start/resume 提交期间时，不主动释放；租约过期后 scanner 根据实际 Run 状态决定清理 queued/waiting reservation，或把 running Run fail closed。

### 3. heartbeat 丢失必须停止执行并保留恢复事实

每个 active execute/resume 拥有独立 lease session 和 heartbeat task。heartbeat 使用最新 token/version handle 串行续约；stop 会等待正在进行的 heartbeat 完成，避免 release 使用已知的旧 version。

heartbeat 返回 `run_lease_lost`、`store_unavailable` 或其他失败时，Coordinator 取消当前 Runtime task并设置协作取消信号。若 Store 已存在 terminal/waiting durable winner则返回赢家；否则原错误继续越界，Run 保持 running，不能伪造 completed、cancelled 或 failed，由 lease scanner 收敛。

### 4. pause、terminal 与 cancel 后再释放

Runtime 返回后先停止 heartbeat，再提交 pause/terminal，最后用最新 handle 释放。用户 cancel 先设置协作取消、停止 heartbeat，再由既有 Run/Event CAS 提交 cancelled，提交成功后释放。并发完成、取消或审批暂停仍由 durable lifecycle commit 决定唯一赢家。

Run 已 durable 进入 terminal/waiting 后，release 失败不能回滚已提交事实，也不能把成功改写为失败；记录稳定 `error_code` 后让陈旧 lease 过期，由 scanner 清理非 running Run。若 lifecycle commit 自身失败或结果未知，则保留 lease，不提前删除恢复凭据。

### 5. 组合边界保持显式

`RunCoordinator` 的 `run_lease_store` 仍为可选显式依赖；未注入时保留既有内存/Container 行为。当前不迁移默认 Container/HTTP，不增加 lifespan scanner，不处理 PostgreSQL Approval/Memory 同步调用的线程隔离，也不声称外部副作用 exactly-once。

## 后果

- running Run 在正常显式 Coordinator 路径上先有可扫描 execution lease，再发布 `run.started` 或 `run.resumed`，关闭“已 running 但从未有 lease row”的崩溃窗口。
- 两个 lease-aware Coordinator 由 reservation 单赢家和 durable lifecycle 状态共同仲裁，后到者只等待并读取赢家，不重复调用 Runtime。
- heartbeat 失败、start/resume 结果未知和 release 失败都保留稳定、可收敛的数据库事实，但在 scanner 实际运行前仍可能短暂看到 running 或陈旧 lease。
- 默认应用仍未调度 scanner，也未接入 PostgreSQL composition，因此本决策不是统一应用重启恢复或生产部署完成证据。

## 未采用方案

- `commit_start` 后再普通 acquire：存在不可扫描的无租约 running 窗口。
- 允许普通 executor 抢占过期 running lease：可能自动重放结果未知的副作用。
- 把 start/resume、lease、checkpoint 和 ToolExecution 强行放进一个大事务：现有 Protocol 与同步/异步 pool 不共享 Unit of Work，且仍不能包含外部副作用。
- heartbeat 失败后由 Coordinator直接提交 cancelled/failed：执行资格已经丢失，旧执行者无权制造新的 durable 终态。
- 本轮同时迁移默认 Container 或增加 lifespan scanner：会混入连接关闭、调度和 Approval/Memory async 边界，超出当前原子纵切。

## 验证依据

- `backend/tests/test_run_lease_store_contract.py`
- `backend/tests/test_run_coordinator.py`
- `backend/tests/postgres_store_integration.py`
- `V-20260808-002`
