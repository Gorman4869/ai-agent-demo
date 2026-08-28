# M12-T1 交接：PostgreSQL durable API 验证闭环

- 日期：2026-08-28，Asia/Shanghai
- 已验收任务：`M12-T1 / verified`
- 下一任务：`M12-T2 / planned`
- 验证基线：实现提交 `2cce750`
- 验证记录：`V-20260828-007`、`V-20260828-008`
- 关联决策：`ADR-0029`
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本次结果

截图中的 `ai-agent-demo-integration-postgres-1` 容器确实处于运行状态。此前验证误用了旧 M11 容器名，随后又沿用不存在的 `ai_agent_test` 库名；只读查询确认 integration 容器实际库为 `ai_agent_integration`。

使用 `postgresql://ai_agent@127.0.0.1:55433/ai_agent_integration?sslmode=disable` 后，`PostgresFastApiApplicationTest.test_durable_run_api_replays_and_reads_after_application_restart` 通过。它覆盖默认 PostgreSQL Container/FastAPI lifespan 下的 durable Run 创建、同幂等键重放、查询、关闭与新 application 的 owner-scoped session list。

M12-T1 现为 `verified`。旧 HTTP/SSE 仍隔离且不双写；M12-T2 尚未开始。

## 失败尝试

- `ai-agent-demo-m11-postgres-1` 是旧容器名，不能判断当前 integration stack 状态。
- `ai_agent_test` 不存在于运行中的 integration 容器；该 DSN 失败是测试命令目标错误，不是 API、数据库容器或应用配置失败。

## 下一条原子动作

开始 M12-T2 前，只读审阅实施计划 M12-T2、`EventStore.list_for_run(after_sequence)`、现有 notifier 和 legacy SSE。先固定 `after`、心跳、终态关闭和通知失败重放语义，再实现真实持久 SSE；不得提前进入 Vue、M12-T3 或新的在线调用。
