# ADR-0015：PostgreSQL ToolExecution 幂等与结果仲裁

- 状态：accepted
- 日期：2026-08-03
- 任务：`M11-T1`
- 依赖：`ADR-0006`、`ADR-0012`、`ADR-0014`

## 背景

M10 已证明审批 grant 消费后 checkpoint 写失败时不能自动重放副作用，但当时没有持久 ToolExecution。M11-T1 前两个纵切已经持久化 Run/Event/checkpoint 与审批私有状态；进程在工具 claim 后退出，或数据库完成结果提交后进程未收到确认时，仍需要一个独立于 checkpoint 和 Run Event 的权威记录判断“可以执行、已有结果或结果未知”。

ToolExecution 领域对象已经只保存参数/结果摘要和有界安全摘要，并定义 pending、waiting_approval、running、completed、failed、cancelled、unknown 状态。缺少的是内存/PostgreSQL 共同 Store、owner 绑定、幂等作用域、CAS 和跨进程故障证据。

## 决策

### 1. 新增独立 async Store，不迁移默认主链

新增 async `ToolExecutionStore`，由现有 Run 的 owner 关系授权，不在 ToolExecution 表重复保存 owner。内存实现绑定同一 `InMemoryRunStore`；PostgreSQL 实现与 Run/Event 使用同一异步 pool，`PostgresPersistence` 统一生命周期。

本纵切只提供持久仲裁能力和显式 probe，不把 Store 注入默认 Container、ToolRegistry、M10 Runtime 或 HTTP。主链接线必须同时处理 Approval 同步 pool、Runtime 取消和 Run/Event 跨域一致性，不能在本原子步骤隐式完成。

### 2. 固定创建与幂等作用域

新 ToolExecution 必须属于 owner 可见且处于 running 的 Run，并以 pending/version 0 创建。数据库固定每个 `(run_id, tool_call_id)` 只有一个记录。

只要调用方提供幂等键，其摘要作用域固定为 `(run_id, tool_name, idempotency_key_digest)`；副作用执行必须提供该键。同作用域、同参数摘要和同 side-effect 标记返回既有记录，即使候选 execution ID、call ID 或 attempt 不同；调用方必须采用返回的权威记录。同作用域改参数或改变 side-effect 语义使用稳定 `idempotency_conflict`，原始 key 和参数不保存、不输出。

没有幂等键时，同一个 call 的相同创建请求可以 replay；同 ID/call 改绑定使用稳定 `tool_execution_conflict`。Run 进入终态后不能创建新执行，但既有幂等记录仍可读取和 replay。

### 3. claim 与结算都使用版本 CAS

pending/waiting_approval 到 running 是 claim；running 到 completed/failed/cancelled/unknown 是结算。每次转换锁定记录并检查 `expected_version`，并发 claim 或并发结算只有一个赢家，其他调用收到 `concurrent_write`。

completed 只保存结果摘要、规范 JSON 的 SHA-256 和有界安全摘要，不保存原始结果。失败、取消和 unknown 只保存稳定错误码与可选公开消息。所有终态不可再次转换。

### 4. running 恢复必须 fail closed

恢复读取 completed/failed/cancelled/unknown 时直接采用既有终态，不再次执行 handler。恢复读取 pending 时仍可通过 CAS claim；读取 running 表示副作用可能已经发生但结果未确认，只能显式结算为 unknown，不能自动重放。

`unknown` 是终态，不是隐式重试队列。后续人工或业务补偿必须使用新的、显式授权的业务动作，不能把原执行改回 running。

### 5. PostgreSQL 约束和故障证据

`0003_tool_execution_store.sql` 用外键、唯一约束、partial unique index、状态/version、时间和 outcome CHECK 固定领域不变量。创建锁所属 Run 行，转换锁 ToolExecution 行；驱动、pool 和触发器失败只越界为稳定 StoreError，不回退内存。

真实数据库测试必须覆盖共同合同、并发 CAS、settlement 触发器回滚和独立进程恢复。一个 probe 在 terminal commit 已完成后立即以非零码退出且不发送完成确认，后续进程必须读到 completed 并幂等 replay；另一个遗留 running 记录必须转为 unknown 且终态不可重开。

## 后果

- ToolExecution 成为 checkpoint、审批 grant 和 Run Event 之外的权威副作用仲裁记录。
- 本地 PostgreSQL 可以区分“已确认完成”和“已 claim 但结果未知”，避免因进程重启盲目重放。
- CAS 和唯一约束提供单次持久结算，不宣称外部系统副作用与数据库提交之间的分布式 exactly-once。
- lease、heartbeat、自动恢复扫描、业务补偿、默认主链接线和跨 pool/跨外部系统事务仍未实现，M11-T1 保持 `in_progress`。

## 未采用方案

- 对 running 记录自动重试 handler：副作用可能已经发生，会制造重复写入。
- 把原始幂等键、参数或结果写入 ToolExecution：扩大敏感面且违反既有领域契约。
- 只依赖 checkpoint 或 approval grant：两者不能证明外部工具结果是否已经提交。
- 在本纵切直接迁移默认 Container：会同时引入同步 Approval pool 的线程/取消边界和跨 Store 一致性，超出原子范围。
- 用 lease 过期把 running 自动改回 pending：lease 与恢复扫描是下一条独立加固，不应改变本纵切的 fail-closed 语义。

## 验证依据

- `backend/tests/test_tool_execution_store_contract.py`
- `backend/tests/postgres_store_integration.py`
- `backend/app/stores/postgres_tool_execution_probe.py`
- `V-20260803-003`
