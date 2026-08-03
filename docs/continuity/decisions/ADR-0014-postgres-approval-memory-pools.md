# ADR-0014：PostgreSQL Approval/Memory 同步契约与双连接池

- 状态：accepted
- 日期：2026-08-03
- 任务：`M11-T1`
- 依赖：`ADR-0006`、`ADR-0011`、`ADR-0012`

## 背景

M11-T1 首个纵切已经用一个 `AsyncConnectionPool` 承载 async Run/Event Store 与官方 `AsyncPostgresSaver`。现有审批和记忆边界不同：`ToolRegistry.execute()`、`InMemoryApprovalStore`、`ConversationMemory` 以及当前记忆 API 都是同步契约。为了只新增 PostgreSQL 适配器而把整个工具执行和 HTTP 记忆链改成 async，会扩大公共迁移面，并提前影响默认 Container。

审批私有参数又必须在进程退出后恢复，不能写入 checkpoint、Run Event、公开对象或日志。审批决议与单次 grant 生成、grant 并发消费和消息窗口裁剪也需要真实数据库事务，不能用进程内锁冒充。

## 决策

### 1. 抽取现有同步 Protocol

新增同步 `ApprovalStore` 与 `MemoryStore` Protocol；既有 `InMemoryApprovalStore` 和 `ConversationMemory` 继续满足原调用方式。`ToolExecutionContext`、审批 Runtime、Container 与 `create_app()` 依赖 Protocol，不依赖具体内存类。

本任务不把 `ToolRegistry.execute()` 或记忆 HTTP API 改成 async。PostgreSQL 适配器调用仍是同步 I/O，因此在接入默认异步主链前必须由后续 composition 任务明确选择线程隔离和取消边界。

### 2. 一个生命周期管理两类连接池

`PostgresPersistence` 使用同一 DSN 管理：

- 一个 `AsyncConnectionPool`：RunStore、EventStore、migration 与 `AsyncPostgresSaver`；
- 一个共享 `ConnectionPool`：PostgreSQL ApprovalStore 与 MemoryStore。

两个池一起打开、一起关闭，使用相同 `dict_row`、autocommit 和禁用 prepared statement 配置。每个多语句操作仍显式开启事务。两类池之间没有共同连接，不能宣称 Run/Event/checkpoint 与 Approval/Memory 跨池原子提交。

### 3. 审批状态与私有参数分离

`tool_approval_requests` 保存服务端绑定、决议状态和有界私有参数；`tool_approval_grants` 只保存精确绑定、过期和消费时间。私有参数最多 64,000 UTF-8 字节，公开请求仍只有 SHA-256 摘要。

审批 resolve 锁定 request row，在同一事务内写决议并生成或替换精确 grant。consume 锁定 grant row，只有一个并发调用能写入 `consumed_at`。数据库错误只越界为稳定 Store 错误，不回退内存，也不输出参数或 DSN。

### 4. 消息窗口与长期事实分别持久化

每个 session 使用计数器行分配消息序号；追加消息与删除窗口外旧消息在同一事务内完成。长期事实只有显式 approved 才能创建，读取和删除按 owner 隔离，顺序由数据库 ordinal 固定。

### 5. 当前组合边界保持显式

本纵切通过显式 PostgreSQL persistence 和独立进程 probe 验证，不迁移默认 Container、HTTP 路由或 M10 审批 Runtime 到数据库。ToolExecution 结果仲裁、lease/recovery scanning 和 pgvector 仍按既有计划后续完成。

## 后果

- 内存与 PostgreSQL Approval/Memory 运行同一合同，现有调用方无需因适配器而改写 API。
- 审批私有参数、决议、单次消费、消息和事实可跨 Python 进程恢复。
- 同步 PostgreSQL 调用可能阻塞 async event loop；默认主链迁移前必须选择显式线程边界，不能直接注入后宣称生产就绪。
- Approval 与 Run/Event 分属不同连接池；跨域一致性仍依赖后续 ToolExecution/恢复仲裁，当前不提供 exactly-once。
- 数据库字段为本地课程级明文存储；本任务没有提供应用层加密、TLS、备份或生产密钥管理证据。

## 未采用方案

- 把全部工具、审批、记忆和 HTTP API 改成 async：超出本原子纵切，扩大默认主链与兼容面。
- 在同步方法内调用 `asyncio.run()` 使用异步池：运行中的 event loop 不允许，且会破坏取消与生命周期所有权。
- 把私有参数写入 LangGraph checkpoint 或 Run Event：扩大敏感面并违反 `ADR-0012`。
- 继续使用进程内 Approval/Memory，同时只持久化公开摘要：进程重启后无法安全恢复批准调用和用户纠正，不能满足 M11-T1。

## 验证依据

- `backend/tests/test_approval_store_contract.py`
- `backend/tests/test_memory_store_contract.py`
- `backend/tests/postgres_store_integration.py`
- `backend/app/stores/postgres_state_probe.py`
