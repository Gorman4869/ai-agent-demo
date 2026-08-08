# ADR-0021：PostgreSQL 同步 Store 的 async bridge 与 owned worker 生命周期

- 状态：accepted
- 日期：2026-08-08
- 任务：`M11-T1`
- 依赖：`ADR-0014`、`ADR-0019`、`ADR-0020`

## 背景

`ADR-0014` 为兼容既有 `ToolRegistry`、审批 Runtime 和记忆 API，保留了同步 `ApprovalStore`/`MemoryStore` Protocol，并由 `PostgresPersistence` 管理独立的同步连接池。若在 FastAPI、Coordinator 或其他 async 主链直接调用 PostgreSQL 同步适配器，数据库等待会阻塞事件循环。

简单使用 `asyncio.to_thread()` 仍没有解决所有权：调用方 timeout 或取消不会终止已运行线程；若 persistence 随后关闭 pool，后台 worker 可能访问已关闭资源。排队写操作也不能在调用方已超时后无条件开始，更不能自动重试结果未知的审批或记忆写入。

## 决策

### 1. 保留同步 Protocol，新增显式 async façade

既有 `PostgresApprovalStore` 和 `PostgresMemoryStore` 继续满足同步公共合同，不修改默认 Container 或现有调用方。`PostgresPersistence` 额外暴露 `async_approval_store` 与 `async_memory_store`；它们的方法镜像现有业务语义，但把同步调用统一交给一个 `PostgresSyncStoreBridge`。

审批参数在 event-loop 线程提交前通过既有有界复制函数脱离调用方引用，避免排队期间被外部可变 Mapping 改写。Message 与字符串继续使用现有不可变领域值。

### 2. 一个有界线程池对应一个共享同步连接池

bridge 使用专用 `ThreadPoolExecutor`，worker 数默认与同步 PostgreSQL pool 的 `max_size` 一致。Approval 与 Memory façade 共用同一个 bridge，因此共享 admission、并发上限和 in-flight 所有权，不为每个 Store 创建独立线程池。

同步适配器保留自己的 `PoolTimeout -> StoreUnavailableError` 映射。bridge 不捕获并重分类正常 Store/业务异常，不输出 DSN、参数、结果或原始数据库异常。

### 3. timeout 区分未开始与已运行

每次 submission 同时保留 concurrent future 和 event-loop future。调用方 timeout 时先尝试取消 concurrent future：

- 若仍在队列中，取消成功，操作不会随后开始；抛出 `store_operation_timeout` 且 `result_unknown=false`。
- 若已经运行，不能硬取消线程；抛出相同稳定错误但 `result_unknown=true`，worker 继续受 bridge 追踪，其最终结果只被安全消费，不返回给已离开的调用方。

调用方取消遵循相同的 queued-cancel 尝试；若 worker 已运行，只传播 `CancelledError` 并继续追踪。bridge 不自动重试、不复用无人接收的结果，也不把 Python task 取消描述成 PostgreSQL statement 已取消。

### 4. bridge 先 quiesce，再关闭两类 pool

bridge 生命周期为：

```text
accepting -> quiescing -> quiesced
                    \-> failed
```

close 在锁内停止 admission，之后的新 async Store 调用返回稳定 `store_not_accepting`。多个 close 共享同一 drain；调用方取消 close 时，owned drain 完成后才传播取消。drain 等待所有已提交 worker，再关闭专用 executor。

`PostgresPersistence.close()` 固定顺序：

```text
sync Store bridge.close
  -> sync connection pool.close
  -> async connection pool.close
```

同步 pool close 失败时仍尝试关闭 async pool，并保持原错误可见。`PostgresExecutionComposition` 已在 `ADR-0020` 中固定 Coordinator、supervisor、persistence 顺序，因此通过 async façade 提交的 in-flight Store 调用也会在 pool 关闭前完成。

### 5. 同步 pool open 也属于 owned worker

同步 pool 的 `open(wait=True)` 仍需在线程中执行。调用方取消 `PostgresPersistence.open()` 时，先等待该 open worker 完成，再关闭同步和异步 pool；不允许 open 与 close 在两个后台线程中无所有权竞态。

### 6. 默认应用迁移保持后续原子步骤

本纵切只提供并验证显式 async 边界，不修改 `ApplicationContainer`、`create_app()`、FastAPI lifespan、HTTP 路由或默认内存配置。保留的直接同步 adapters 也不受 bridge in-flight 追踪；其调用方必须在 persistence close 前自行停止。

因此 `KI-023` 只能更新为 `mitigated`。只有默认 async 主链实际使用 façade，并固定 HTTP/命令 admission 与 lifespan 关闭顺序后才能关闭。

## 后果

- PostgreSQL Approval/Memory 可以从 async 代码调用而不阻塞事件循环，且共享同步 pool 不会在 bridge worker 仍运行时被关闭。
- queued timeout 能阻止尚未开始的写操作；running timeout 明确暴露结果未知，避免把软取消误写成硬取消或安全重试。
- async façade 是新增显式 API，既有同步 Protocol、内存适配器、默认 Container 和 M1 隔离路径不变。
- 专用 executor 和同步连接池仍只提供单进程并发边界，不是查询级取消、分布式事务、跨 pool 原子性、external exactly-once 或生产容量证据。

## 未采用方案

- 在 async 路由直接调用同步 PostgreSQL Store：会阻塞事件循环并违反 `KI-023` 的退出条件。
- 每个方法裸用 `asyncio.to_thread()`：没有统一 admission、并发上限、in-flight 追踪或 pool 关闭所有权。
- timeout 后取消 asyncio future 并立即关闭 pool：不能终止已运行线程，可能让 worker 访问关闭中的连接池。
- timeout 后自动重试审批 resolve/consume、消息 append 或 fact 写入：首次结果可能已提交，会扩大重复副作用。
- 将全部同步 Protocol 改为 async：会一次性改写 ToolRegistry、审批 Runtime、HTTP 和记忆调用面，超出本原子纵切。
- 本轮同时迁移默认 FastAPI lifespan：会混入配置、HTTP admission、默认 Runtime 和完整回归门，留给下一条原子纵切。

## 验证依据

- `backend/app/stores/postgres_async.py`
- `backend/app/stores/postgres.py`
- `backend/tests/test_postgres_async_stores.py`
- `backend/tests/postgres_store_integration.py`
- `V-20260808-011`
