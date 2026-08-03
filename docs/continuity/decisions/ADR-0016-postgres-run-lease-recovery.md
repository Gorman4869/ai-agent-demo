# ADR-0016：PostgreSQL Run 租约与过期恢复扫描

- 状态：accepted
- 日期：2026-08-03
- 任务：`M11-T1`
- 依赖：`ADR-0006`、`ADR-0012`、`ADR-0014`、`ADR-0015`

## 背景

M11-T1 前三个纵切已经持久化 Run/Event/checkpoint、Approval/Memory 和 ToolExecution 仲裁。ToolExecution 能区分 completed 与结果未知，却没有办法判断一个 running Run 是否仍有执行者；进程在 start 或 tool claim 后退出会永久留下 running 记录，也没有多进程安全的 scanner 领用规则。

租约过期不能直接把 running ToolExecution 改回 pending。外部副作用可能已发生，自动重放会违反 `ADR-0015` 的 fail-closed 结论。租约 token 还是服务端执行凭证，不能由客户端提供、明文持久化或进入日志与 probe 输出。

## 决策

### 1. 单 Run、服务端生成的版本化租约

新增 async `RunLeaseStore`、内存参考实现、`0004_run_leases.sql` 和 PostgreSQL 适配器。每个 Run 最多一条租约；只有 owner 可见且处于 running 的 Run 可以获得 execution lease。

Store 使用加密安全随机源生成 opaque token，只在进程内 `RunLease` handle 中持有原值，字符串形式和 `safe_summary()` 均不暴露。数据库只保存 SHA-256 摘要。调用方不能传入 token 创建或替换租约。

### 2. PostgreSQL 数据库时钟是过期权威

PostgreSQL acquire、heartbeat、release 和 scan 都使用 `clock_timestamp()`，不使用应用进程时钟判断过期。这样多个进程的本地时钟偏差不会决定租约所有权；内存适配器的可注入时钟只用于共同合同和离线参考实现。

heartbeat 必须同时匹配 Run、owner、token 摘要、version、running 状态和未过期条件，然后 version 加一并从数据库当前时间延长。release 同样要求精确 token/version 且尚未过期。旧 handle、过期 handle 或已被 scanner 轮换的 handle统一返回稳定 `run_lease_lost`，不能复活执行权。

### 3. 过期租约只能由 recovery scanner 领用

普通 acquire 不覆盖现有租约，即使它已经过期。`claim_expired()` 按 `(expires_at, run_id)` 排序，用 `FOR UPDATE SKIP LOCKED` 有界领用，轮换新 token、递增 version，并把 mode 改为 recovery。恢复进程再次退出后，其 recovery lease 也只能在下一次过期后被其他 scanner 重新领用。

### 4. orphan 恢复先收敛工具，再终结 Run

显式 `RunRecoveryService.scan_once()` 处理 scanner 已领用的记录：

1. terminal Run 只清理陈旧租约，不改写终态；waiting approval 等非 running Run 只释放租约，不伪造失败。
2. running ToolExecution 转为 terminal `unknown`，不能调用 handler；pending 或 waiting approval ToolExecution 转为 `cancelled`；既有 terminal 记录保持不变。
3. 工具记录收敛后，用既有 `TerminalCommit` 把仍为 running 的 Run 原子提交为 `failed + run.failed`，稳定失败码为 `run_orphaned`、`retryable=false`。
4. Run 终态提交成功后释放 recovery lease。Store 故障不释放租约，等待下一次过期扫描继续收敛；取消直接传播，不伪造结果。

### 5. 不宣称跨 Store 事务或 exactly-once

ToolExecution 结算、Run/Event 终态和 lease 释放是多个数据库事务。顺序选择“工具先终态、Run 后终态”，使进程在中间退出时下一次 scanner 可跳过已终态工具并继续提交 Run；真实触发器故障测试固定该收敛行为。

租约只能仲裁数据库中的执行资格，不能让外部副作用与数据库提交组成分布式 exactly-once。Runtime 仍必须使用持久 ToolExecution 幂等与结果未知规则。当前纵切不把 lease 注入默认 Container/Coordinator，不增加后台调度，不处理同步 Approval/Memory 的 async 线程边界，也不进入 M11-T2。

## 后果

- 多个 PostgreSQL scanner 对同一过期租约只有一个领用者，旧执行者不能 heartbeat、release 或重新 acquire。
- orphaned running Run 和非终态工具有稳定、可重放、不会自动重复副作用的 fail-closed 结论。
- scanner 在部分 Store 提交后退出仍可通过 lease 再过期收敛，但收敛期间允许观察到“工具已终态、Run 仍 running”的短暂状态。
- 默认应用还没有 acquire/heartbeat/release 或定时 scan，因此本 ADR 证明的是显式持久化纵切，不是统一主链重启恢复或生产调度能力。

## 未采用方案

- 过期后允许普通 executor 抢占：旧 side effect 结果未知，会形成盲重放。
- 保存明文 token 或让客户端提供 token：扩大凭证泄漏和伪造面。
- 使用应用进程时间判断 PostgreSQL 过期：多进程时钟偏差会破坏一致仲裁。
- 一个大事务同时结算所有工具、Run/Event 和 lease：现有 Store Protocol 不共享 Unit of Work，且仍无法包含外部副作用；强行耦合会扩大 M11-T1 迁移面。
- scanner 自动重新执行 read-only 或 side-effect 工具：本纵切没有持久 Runtime 重调度协议，结果未知统一 fail closed。
- 在本纵切增加后台任务和默认 Container 接线：会同时引入 lifespan、取消、关闭和同步 pool 线程边界，超出当前原子动作。

## 验证依据

- `backend/tests/test_run_lease_store_contract.py`
- `backend/tests/test_run_recovery.py`
- `backend/tests/postgres_store_integration.py`
- `backend/app/stores/postgres_recovery_probe.py`
