# ADR-0018：显式 Run recovery supervisor 调度生命周期

- 状态：accepted
- 日期：2026-08-08
- 任务：`M11-T1`
- 依赖：`ADR-0016`、`ADR-0017`

## 背景

`ADR-0016` 已固定过期 lease 的多进程 claim 和 `RunRecoveryService.scan_once()` 收敛规则，`ADR-0017` 已让显式 Coordinator 在 start/resume 前 reservation 并在执行期 heartbeat。但是恢复仍只能由调用方手动触发；若直接在 Container 或 FastAPI lifespan 中临时创建 fire-and-forget task，会缺少单实例所有权、重叠扫描、取消、关闭和错误后的后续周期语义。

scanner 调度不能重新实现 ToolExecution、Run/Event 或 lease 的恢复顺序。后台轮次还必须区分可诊断的 Store 故障与程序错误：数据库短暂不可用应让下一周期继续，未知代码异常则不能被无限循环静默吞掉。

## 决策

### 1. supervisor 只调度既有恢复服务

新增显式 `RunRecoverySupervisor`，构造时接收既有 `RunRecoveryService`。每个实例只创建一个命名后台 task；首轮 scan 在 task 启动后立即执行，之后每轮必须等待前一轮完整返回，再等待固定周期。

supervisor 不调用 `claim_expired()`、不遍历工具、不提交 Run 终态，也不持有数据库连接。所有恢复规则继续唯一属于 `RunRecoveryService` 和 Store adapters，因此同一实例不存在重叠 scan 或第二套恢复业务逻辑。

### 2. 固定不可重启的生命周期状态

生命周期固定为：

```text
created -> running -> closing -> closed
                   -> failed
created -----------------------> closed
```

- `start()` 在 running 时幂等；created 以外的其他状态拒绝启动。
- `close()` 在 created/closed 时幂等；running 先进入 closing，关闭期间的新 start 稳定拒绝。
- 一个已 closed 或 failed 的实例不重启；新的应用生命周期必须构造新 supervisor 和新 persistence owner。

### 3. close 取消并等待唯一后台 task

`close()` 取消并 await supervisor 拥有的 task，确保 interval wait 或 in-flight scan 不作为孤立任务遗留。`RunRecoveryService` 的 `CancelledError` 继续传播，不生成伪造的 Run 结果；扫描协程的 `finally` 清理会在 close 返回前完成。

如果调用方取消正在等待的 close，调用方的 `CancelledError` 不能被当成后台 task 的正常取消而吞掉。扫描取消点已经提交的 ToolExecution/Run/Event 与仍存在的 recovery lease 继续遵循 `ADR-0016` 的分离事务收敛规则；本决策不承诺 shutdown 能回滚已提交事实或立即删除所有 lease。

### 4. Store 故障续跑，程序错误可见

- `scan_once()` 在 claim 阶段抛出的 `StoreError` 只记录稳定 error code，不记录原始异常文本，等待下一周期继续。
- `RunRecoveryService` 返回的单 Run `FAILED` 结果同样不终止 supervisor；下一轮在 recovery lease 再次过期后继续收敛。
- 非 `StoreError` 的异常把 supervisor 置为 failed，并在 close await task 时重新抛出；不得用宽泛异常处理让程序错误变成永久空转。

构造阶段固定 scan limit 为 1–100，recovery TTL 为大于 0 且不超过 1 天，与既有 lease Store 合同一致。非法配置不得延迟到后台 task 才失败。

### 5. composition 保持显式

本纵切不修改默认 `ApplicationContainer`、`create_app()` 或 FastAPI lifespan。调用方必须显式 start/close supervisor，并保证先停止 supervisor、再关闭它使用的 PostgreSQL persistence。

本决策也不处理 PostgreSQL Approval/Memory 同步 pool 的 async 线程边界，不新增部署配置，不进入 M11-T2。真实 PostgreSQL 集成只证明本地 E3 的自动调度恢复，不证明生产守护进程、跨主机高可用或外部副作用 exactly-once。

## 后果

- recovery scanner 有可测试的单 task、无重叠、错误续跑和关闭语义，可被后续显式 PostgreSQL composition 复用。
- 数据库短暂不可用不会永久停止恢复循环，程序错误也不会被误分类为可重试 Store 故障。
- 取消 in-flight scan 可能留下已经部分收敛的 ToolExecution/Run 或陈旧 recovery lease；下一应用生命周期仍须启动 supervisor 让其继续收敛。
- 默认应用尚未拥有 supervisor，不能把本 ADR 描述为 lifespan、统一进程重启恢复或生产部署已完成。

## 未采用方案

- `asyncio.create_task(scan_once())` 固定频率并发触发：慢扫描会重叠，增加同一进程内无意义的数据库竞争。
- 在 supervisor 中复制 claim 和恢复状态机：形成第二真相源，容易偏离 `ADR-0016` 的结果未知和工具先收敛规则。
- 捕获所有异常后继续：程序错误会永久静默空转，后台 task 看似 running 但不再可信。
- close 只设置布尔标记、不 await task：应用可能先关闭连接池，仍运行的 scan 随后访问已关闭 persistence。
- 本轮直接接入默认 FastAPI lifespan：会混入 persistence composition、HTTP 迁移和 Approval/Memory async 边界，超出当前原子纵切。

## 验证依据

- `backend/app/services/run_recovery_supervisor.py`
- `backend/tests/test_run_recovery_supervisor.py`
- `backend/tests/postgres_store_integration.py`
- `V-20260808-005`
