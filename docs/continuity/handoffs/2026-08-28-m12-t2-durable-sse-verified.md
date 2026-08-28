# M12-T2 交接：持久事件 SSE 与续传

- 日期：2026-08-28，Asia/Shanghai
- 已验收任务：`M12-T2 / verified`
- 下一任务：`M12-T3 / planned`
- 验证基线：`506c8ae`
- 验证记录：`V-20260828-009`
- 关联决策：`ADR-0003`、`ADR-0007`、`ADR-0029`、`ADR-0030`
- 任务等级：A 类（并发、持久化、身份与公共流式契约）
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本次结果

新增 `GET /api/durable/runs/{run_id}/events?after=<sequence>`。它复用 durable
Run 的 owner/capability 校验，以 EventStore 的递增业务 sequence 作为排他的
断线续传 cursor，并在 SSE `id` 与 JSON envelope 中传递 sequence。

Coordinator 注入 `InProcessEventNotifier` 后，仍坚持先持久化 EventStore 再唤醒
连接。notifier 只保存活动连接的 coalesced `asyncio.Event`，不保存 payload 或
无界队列；SSE 每次唤醒和有限超时复查都从 EventStore 取历史。慢消费者不会反压
Coordinator，连接断开只释放订阅，不取消 Run 或 Tool。

终态关闭前会再次查询 Store，防止“当前批次读取后终态已写入”导致最后一帧遗漏。
真实 PostgreSQL FastAPI lifespan 测试已验证重启后 `after=1` 只回放未读事件。
旧 legacy HTTP/SSE 没有修改或双写。

## 修改文件

- `backend/app/services/run_event_notifier.py`
- `backend/app/services/__init__.py`
- `backend/app/container.py`
- `backend/app/main.py`
- `backend/tests/test_persistent_sse.py`
- `backend/tests/postgres_store_integration.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/continuity/decisions/ADR-0030-durable-sse-replay-contract.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`

## 验证

- 专项 SSE 8 项通过。
- SSE、durable API、legacy API、Container、Coordinator、Store 合同共 133 项通过。
- 本机 integration PostgreSQL 的 FastAPI 重启回放 1 项通过。
- 没有执行在线模型、前端、浏览器、Nginx 或远程 Git。

## 下一条原子动作

开始 M12-T3 前，先只读审阅实施计划、ADR-0029/0030、Run/Event 的 RAG/usage
事件形状与 snapshot 边界。只聚合同一 durable Run 已持久化的引用和 usage；不要
提前进入 Vue SSE 解析、浏览器 E2E、生产消息总线或新的在线调用。
