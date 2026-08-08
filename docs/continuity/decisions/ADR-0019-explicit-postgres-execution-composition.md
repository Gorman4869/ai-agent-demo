# ADR-0019：显式 PostgreSQL execution composition 生命周期

- 状态：accepted
- 日期：2026-08-08
- 任务：`M11-T1`
- 依赖：`ADR-0016`、`ADR-0017`、`ADR-0018`

## 背景

`ADR-0017` 已让显式 `RunCoordinator` 在执行前 reservation、执行中 heartbeat、终态后 release，`ADR-0018` 已提供单 task 的 `RunRecoverySupervisor`。但是调用方仍需自行拼装 `PostgresPersistence`、Coordinator、恢复服务和 supervisor，容易出现 migration/checkpointer 尚未 setup 就开始执行、scanner 未启动，或 persistence 先于 scanner 关闭等顺序错误。

本纵切需要一个仍然显式、但真实可运行的 composition owner。它必须证明新应用进程能够仅通过自己的启动生命周期自动收敛旧进程遗留的 orphan，而不是由测试直接调用 scanner。

## 决策

### 1. 一个 owner 构造完整 PostgreSQL 执行链

新增 `PostgresExecutionComposition.open()`，固定启动顺序：

```text
PostgresPersistence.open
  -> persistence.setup
  -> lease-aware RunCoordinator
  -> RunRecoveryService
  -> RunRecoverySupervisor
  -> supervisor.start
```

Coordinator、恢复服务和 supervisor 必须共享同一个 `PostgresPersistence` 提供的 Run、Event、ToolExecution 与 lease adapters。调用方只提供可信 Runtime 映射、可选 notifier 和有界执行/lease/recovery 参数。

### 2. 启动全有或全无，关闭顺序固定

composition 对外暴露前必须完成 setup 和 supervisor start。setup、配置校验或 start 失败时，若 supervisor 已构造则先 close supervisor，再 close persistence，并重新抛出原始启动错误。

可见生命周期为 starting/running/closing/closed/failed。running composition 的关闭顺序固定为：

```text
supervisor.close -> persistence.close
```

重复 close 幂等；关闭失败保持 failed，调用方取消 close 时继续传播 `CancelledError`。关闭逻辑即使 supervisor 失败也必须尝试关闭 persistence。

### 3. 跨进程证据必须经过 composition

真实 PostgreSQL probe 的旧 holder 进程使用 composition 创建 Run 并由其 Coordinator 开始执行，然后以退出码 17 异常终止。等待 lease 过期后，PID 不同的新进程只启动一个新 composition；它的 supervisor 必须自动把 Run 提交为非重试 `run_orphaned`、写入唯一 `run.failed` 事件并释放 lease。

probe 只能输出阶段、PID 和布尔审计结果，不输出 DSN、输入、幂等键、lease token 或异常原文。

### 4. active Run drain 保持显式边界

本 composition 拥有 scanner 和 PostgreSQL pools 的关闭，不在本纵切改写 `RunCoordinator` 的 active execution/cancel 语义。调用方在 close 前必须停止接收新 execute/resume，并等待已启动的 Coordinator 操作结束；否则活跃 Runtime 或 heartbeat 仍可能访问即将关闭的 pool。

为默认应用接线前，必须另行固定 admission stop、active execution quiesce/drain 和超时后的 fail-closed 行为。本 ADR 不把“关闭 scanner 和 pool”描述成“任意活跃 Run 均已安全关停”。

### 5. 默认应用与同步 Store 仍不迁移

本纵切不修改 `ApplicationContainer`、`create_app()`、FastAPI lifespan 或 HTTP；也不在 async 主链调用同步 PostgreSQL Approval/Memory adapters，不新增部署配置，不进入 M11-T2。

因此它是本地真实 PostgreSQL E3 的显式 composition 证据，不是默认应用、生产部署、跨主机高可用或外部副作用 exactly-once 证据。

## 后果

- migration/checkpointer setup、lease-aware Coordinator、自动恢复 scanner 和 pool 关闭由一个可测试 owner 固定，不再依赖调用方临时拼装顺序。
- setup/start 失败不会遗留已打开的 pool 或已构造的 supervisor；正常关闭不会让 scanner 在 pool 关闭后继续运行。
- 不同 PID 的旧执行者与新 composition 已形成真实应用级恢复纵切，但默认 Container 仍没有使用它。
- active Coordinator 操作的 admission stop 和 drain 成为下一条必须解决的生命周期边界，不能被隐式取消或忽略。

## 未采用方案

- 直接在默认 FastAPI lifespan 中创建 persistence 和 scanner：会混入 HTTP、默认 Runtime、同步 Approval/Memory async 边界与活跃请求关闭语义。
- 只提供一个返回多个对象的 helper：没有单一 close owner，仍允许 persistence 先于 supervisor 关闭。
- composition.close 隐式调用现有用户 cancel：会把应用 shutdown 伪装成 `cancelled_by_user`，改变领域语义。
- close 直接取消 Coordinator 私有 task：会依赖内部实现并绕过明确的 lease/result-unknown 合同。
- 复用同一进程手动调用 `scan_once()` 作为恢复证据：不能证明新 composition 启动后自动调度，也不能证明数据库跨进程仲裁。

## 验证依据

- `backend/app/postgres_execution.py`
- `backend/app/postgres_execution_probe.py`
- `backend/tests/test_postgres_execution.py`
- `backend/tests/postgres_store_integration.py`
- `V-20260808-007`
