# ADR-0020：RunCoordinator admission stop 与 active execution quiesce

- 状态：accepted
- 日期：2026-08-08
- 任务：`M11-T1`
- 依赖：`ADR-0016`、`ADR-0017`、`ADR-0018`、`ADR-0019`

## 背景

`ADR-0019` 已用一个显式 composition 固定 PostgreSQL persistence、lease-aware Coordinator 和 recovery supervisor 的启动/关闭顺序，但 close 前仍要求调用方自行停止新 Run 并等待 active execution。若遗漏此前置条件，composition 可能先关闭 pool，仍运行的 Runtime 或 heartbeat 随后访问已关闭连接。

应用 shutdown 也不能直接调用现有 `cancel()`：该方法代表用户取消并提交 `cancelled_by_user`。进程关闭不是用户业务指令；若强制停止时外部副作用或数据库提交结果未知，旧执行者必须放弃执行资格并保留 lease，交给下一 lifecycle 的 scanner 收敛。

## 决策

### 1. Coordinator 拥有不可重启的 admission 状态

`RunCoordinator` 增加以下显式状态：

```text
accepting -> quiescing -> quiesced
```

`execute()` 与 `resume_approval()` 必须在既有 `_active_lock` 内检查状态并登记 active task。进入 quiescing 后，新的首次执行、重复 waiter 和审批 resume 均以稳定 `coordinator_not_accepting` 拒绝；quiesced 不可重新开放，新的应用 lifecycle 必须构造新 Coordinator。

多个并发 `quiesce()` 调用共享第一个调用建立的 drain task。后到调用方的不同 timeout 不改变已经开始的关闭策略。

### 2. timeout 是自然完成宽限期

`quiesce(timeout_ms)` 先等待状态切换时已经登记的 active task 自然完成。自然完成路径继续按既有规则停止 heartbeat、提交 pause/terminal 并 release lease；quiesce 在这些任务全部结束前不得返回。

timeout 必须是正整数毫秒。它表示自然完成宽限期，不是整个进程的硬终止上限。宽限期后仍 active 的任务由 Coordinator 统一标记内部原因 `coordinator_shutdown` 并取消协程，再 await Runtime、heartbeat 和 task finally 清理。若 Runtime 非协作地吞掉 task cancellation，quiesce 可以超过宽限期；本决策不伪造 Python 线程或外部进程硬停止能力。

### 3. shutdown 超时保留结果未知事实

内部 shutdown 原因不得进入 `_cancellation_result()`，不得提交 `run.cancelled`、`cancelled_by_user` 或普通 `run_cancelled`。取消到达 Runtime、progress emit、pause/terminal commit 前后任一 await 时，`_drive_running` 都调用 lease session `abandon()`：停止并等待 heartbeat，但不 release execution lease，也不伪造 Run 终态。

因此超时后的 durable Run 保持 running，事件最多保留已提交边界，lease 等待数据库时钟过期。下一 composition 的 supervisor 按 `ADR-0016` 把结果未知工具和 Run 收敛为 `run_orphaned`。如果用户取消或 deadline 已先取得 CancellationToken，既有用户/超时语义继续优先，不由 shutdown 改写。

### 4. 调用方取消 quiesce 仍完成清理

`quiesce()` 用独立 task 拥有状态切换与 drain。调用方取消等待时，先 await 该 task 完成，再传播调用方的 `CancelledError`；不能让取消变成 pool 提前关闭的捷径。

`PostgresExecutionComposition.close()` 固定执行：

```text
coordinator.quiesce
  -> recovery_supervisor.close
  -> persistence.close
```

quiesce 已完成后，即使 supervisor close 失败仍可安全尝试关闭 persistence。若 quiesce 出现非取消程序错误，composition 停止 supervisor 但不关闭可能仍被 active work 使用的 persistence，并进入 failed。

### 5. 默认应用和其他命令仍保持边界

本纵切只关闭 execute/resume admission 并拥有 active execution task。现有 `cancel()` 仍代表显式用户命令；调用方在 composition close 前仍须停止 HTTP/命令入口，避免新的非执行 Store 操作与 pool 关闭竞态。

本轮不迁移默认 `ApplicationContainer`、`create_app()`、FastAPI lifespan 或 HTTP，不处理同步 PostgreSQL Approval/Memory 的 async 线程隔离，不新增部署配置，不进入 M11-T2。无 lease Coordinator 可以自然 drain，但 timeout 后可恢复的 E3 证据只适用于显式 lease-aware PostgreSQL composition。

## 后果

- composition 不再要求外部代码读取或等待 Coordinator 私有 task，pool 关闭前 Runtime 和 heartbeat 已停止。
- 自然完成保留正常 terminal/release；shutdown timeout 保留 running+lease，由新 composition 自动恢复，不伪造成用户取消。
- 调用方取消、并发 quiesce 和关闭顺序有稳定自动化合同。
- 默认 HTTP 命令入口、同步 Approval/Memory async 边界和非协作 Runtime 的进程级硬终止仍未解决。

## 未采用方案

- composition 直接读取或取消 `RunCoordinator._active`：跨越所有权边界，后续 Coordinator 内部调整会破坏 shutdown。
- 对每个 active Run 调用 `cancel()`：会把应用关闭伪装成用户取消并错误提交终态。
- timeout 后 release lease：外部副作用或 lifecycle commit 可能结果未知，释放会丢失 scanner 的恢复凭据。
- timeout 后立即关闭 pool、不 await task：Runtime/heartbeat finally 仍可能访问已关闭连接。
- 永久等待自然完成：一个阻塞 Runtime 会让应用永远无法进入恢复边界。
- 本轮同时接入 FastAPI lifespan：会混入 HTTP admission、同步 Store 线程隔离和默认配置迁移，超出当前原子纵切。

## 验证依据

- `backend/app/services/run_coordinator.py`
- `backend/app/postgres_execution.py`
- `backend/tests/test_run_coordinator_quiesce.py`
- `backend/tests/test_postgres_execution.py`
- `backend/tests/postgres_store_integration.py`
- `V-20260808-009`
