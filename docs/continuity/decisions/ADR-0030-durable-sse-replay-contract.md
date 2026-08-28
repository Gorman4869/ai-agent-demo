# ADR-0030：M12 持久事件 SSE 续传契约

- 状态：accepted
- 日期：2026-08-28
- 任务：`M12-T2`
- 依赖：`ADR-0003`、`ADR-0007`、`ADR-0029`

## 背景

M12-T1 已让 durable Run 在创建后异步执行，但 HTTP 只能读取快照。旧
`/api/sessions/{session_id}/runs/stream` 会等待 legacy Run 完成后回放，不可
用于 durable Run 的断线续传，也不能成为新的主链。

持久 `EventStore` 已提供 owner-scoped、递增 sequence 的 append-only 历史；
Coordinator 先提交 EventStore，再调用尽力而为的 notifier。SSE 必须以持久
历史为真相，不能把未持久化的内存消息直接交给客户端。

## 决策

### 1. 使用独立 durable SSE 路径与 sequence cursor

新增 `GET /api/durable/runs/{run_id}/events?after=<sequence>`。它使用与 durable
Run 查询相同的认证 Principal 或匿名 `X-Session-Token` 所有权规则；未拥有的
Run 与不存在的 Run 一律返回内容无关的 404。

`after` 是非负、排他的业务事件 sequence。响应依 sequence 升序发送所有
`sequence > after` 的已提交事件；每帧包含 SSE `id`、事件 type，以及含
`run_id`、`sequence`、`step`、`created_at` 和 `data` 的 JSON envelope。客户端
以最后收到的业务 sequence 重连，不依赖进程内连接状态。心跳为 SSE 注释帧，
不占用或伪造业务 sequence。

### 2. 持久 EventStore 优先，进程内 notifier 仅作低延迟唤醒

新的 in-process notifier 只维护当前连接的唤醒 signal，不缓存 event payload
或未界队列。每次被唤醒后 SSE 都重新从 EventStore 按 cursor 读取，因此：

- notifier 丢失、应用重启或跨进程事件不会丢历史，有限等待超时后仍会复查 Store；
- 慢消费者不会反压 Coordinator 或累积每连接事件队列；
- 事件必须先成功持久化，才可能触发 notifier；
- 断开 SSE 只取消该订阅，不取消或重放 Run/Tool 副作用。

默认内存 Container 与 opt-in PostgreSQL composition 都注入同一种 notifier；
PostgreSQL 没有依赖它来保证正确性，未来 M13 如需跨实例低延迟通知可替换为
数据库或消息系统 adapter，保持 EventStore replay 契约不变。

### 3. 终态在最后一条持久事件后关闭

当 cursor 已追上 Store 且 owned Run 为 `completed`、`failed` 或 `cancelled` 时，
SSE 正常结束。`waiting_approval` 不是终态，保持连接并发送心跳，直到新的
持久事件、客户端断开或真正终态。

## 后果

- legacy SSE 完全不修改、不双写；Vue 实时状态机、解析半包/多帧和刷新恢复仍由
  M12-T4/M12-T5 承接。
- 该纵切使用有限时长 Store fallback 轮询来覆盖 notifier 漏唤醒，不引入 Redis、
  PostgreSQL LISTEN/NOTIFY 或外部消息队列。
- SSE payload 只转发已经受 EventStore 有界 JSON 校验的 event data；认证和
  capability 仍不得进入 event payload、日志或 prompt。

## 未采用方案

- 直接复用 legacy `/runs/stream`：它的执行和回放语义不兼容 durable 主链。
- 只用进程内队列/广播：重启、重连和跨进程会丢事件，慢消费者还会无限积压。
- 只通过短周期轮询而不复用 notifier：能保持正确性，但会放弃现有“commit 后
  通知”的低延迟钩子，并在本地高频事件下造成不必要等待。
- 在本任务引入 Redis、消息队列或 PostgreSQL LISTEN/NOTIFY：超出 M12-T2 的
  最小可验证纵切，生产部署由 M13 决定。

## 验证依据

- `backend/tests/test_persistent_sse.py`
- `backend/tests/test_persistent_run_api.py`
- `V-20260828-009`
