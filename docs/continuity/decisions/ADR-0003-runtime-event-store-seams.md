# ADR-0003：先建立异步 Runtime、持久事件和 Store 协议

- 状态：accepted
- 日期：2026-07-16
- 决策者：用户与当前实现协作者

## 背景

当前 `InMemoryRunService` 同时承担会话、Run 存储、执行和观测，只保存事件类型；模型和手写 Loop 为同步接口。如果直接在现有 SSE 上接真实流，M12 持久化和断线恢复会再次重写。

## 决策

M8 先建立：

- 统一异步 `AgentRuntime` 协议。
- 独立 `StoredRunEvent`，包含 Run ID、递增序号、类型、数据和时间。
- `RunStore`、`EventStore`、`ApprovalStore`、`MemoryStore` 等 Protocol。
- `RunCoordinator` 只编排 Runtime、Store、Observer 和控制信号。
- 事件必须先持久化，再由 SSE 传输。

现有同步 Loop 通过 `ManualRuntime` 包装，不直接改造成 SDK 实现。

## 后果

- M8 的改动比只接一个 SDK 示例略多。
- M10–M12 可以复用同一事件、状态和持久化边界，降低后续返工。
- 内存和 PostgreSQL Store 必须运行同一套契约测试。
