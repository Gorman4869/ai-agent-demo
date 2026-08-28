# M12 durable Run API 迁移记录

本文面向旧 Vue 页面或其他 legacy API 调用方。它记录 M12 的实际迁移契约，不表示旧端点
已经删除。兼容边界由 [ADR-0033](continuity/decisions/ADR-0033-legacy-run-api-compatibility.md)
决定，动态工程状态只查看[连续性状态页](continuity/status.md)。

## 迁移结论

```text
旧 Agent UI：legacy Run POST SSE -> 等完整结果 -> 独立 Research 覆盖答案/引用
新 Agent UI：durable create -> 持久 SSE 增量 -> durable snapshot 给出同 Run 最终结果
```

Vue 主链已经迁移；旧端点继续保持隔离兼容。新功能只接入 durable API，不在 legacy
RunService 上增加取消、审批、持久 sequence、引用或 usage。

## 新旧契约对照

| 目的 | legacy 契约 | durable 契约 | 迁移注意 |
| --- | --- | --- | --- |
| 建立匿名会话 | `POST /api/sessions`，返回 `201` 和 session capability | 首次 `POST /api/durable/runs`，返回 `202`、Run、session 和 capability | 首次幂等键同时是 capability bootstrap；必须使用安全随机值 |
| 创建 Run | `POST /api/sessions/{id}/runs`，同步返回终态 | `POST /api/durable/runs`，body 可带 `session_id` | 必须发送 `Idempotency-Key`；接受 queued/running/waiting/terminal |
| 实时事件 | `POST .../runs/stream`，执行完成后回放、无持久 cursor | `GET /api/durable/runs/{id}/events?after=N` | 先创建再订阅；`after` 排他，SSE `id` 等于业务 sequence |
| 查询 Run | `GET /api/runs/{id}`，只有 completed/failed | `GET /api/durable/runs/{id}` | durable 快照含 citations、usage 和稳定 error，可在执行中读取 |
| 恢复会话 | `GET /api/sessions/{id}` 返回 session 元数据 | `GET /api/durable/sessions/{id}/runs` 返回 owned Run 列表 | durable 不创建无 Run 的空 session |
| 取消 | 无独立持久命令 | `POST /api/durable/runs/{id}/cancel` | 断开 SSE 不等于取消；终态不可重开 |
| 审批 | legacy 高风险工具测试链 | `POST /api/durable/runs/{id}/approvals/{approval_id}` | body 只提交 `approve/reject`；工具绑定来自服务端事件和 Store |
| RAG 答案 | `POST /api/research` 返回独立 evidence/critique/answer | 同 Run `rag.citations` 事件 + durable snapshot | Agent UI 不再第二次 Research；独立 Research 仍供 RAG 练习使用 |

## 行为差异不是 URL 差异

### 所有权与幂等

- 认证用户的 owner 只来自已验证 Principal。
- 匿名首个 durable Run 使用至少 32 字节编码长度的随机 `Idempotency-Key` 建立 owner；
  原值只回显给创建者，后续作为 `X-Session-Token` 发送。
- 同 owner、同幂等键、同 canonical request 是重放；同键改请求是内容无关的冲突。
- capability 不得进入 URL、`localStorage`、UI、日志、错误或事件 payload。

### 实时与恢复

- EventStore 的递增 sequence 是业务顺序；时间戳不是排序依据。
- 心跳是 SSE 注释，不消耗 sequence。
- 客户端只应用严格递增且 Run ID 一致的事件；重复帧忽略，缺口先停用增量状态并读取快照。
- SSE 提前结束时先查询权威快照，再从最后成功应用的 sequence 有界重连。
- 关闭标签页、组件卸载或网络断开只断开观察，不自动取消后台 Run。

### 最终结果与证据

- 中间输出可来自 `model.output.delta`，但终态 answer、citations、usage 和 error 以 durable
  snapshot 为准。
- citations 只投影同 Run 中已持久化、且真正入选 prompt 的公开 RAG 片段；快照查询不会
  重新检索当前知识库。
- usage 为 `null` 表示未知，不表示 0 Token 或零成本。
- `/api/research` 的结果属于另一次独立工作流，不能覆盖 durable Run 的 UI 结果。

## 前端迁移步骤

1. 在 `agentApi.ts` 集中实现 durable create、snapshot、SSE、cancel 和 approval。
2. 用 `crypto.randomUUID()` 为每个 create 生成新的 `Idempotency-Key`。
3. 首次响应保存 capability、Run ID、session ID、sequence 和待审批公开字段到版本化
   `sessionStorage`；不保存 prompt、答案、引用或工具参数。
4. 创建成功后订阅 `GET .../events?after=0`，按判别联合更新状态机。
5. 刷新时先查询 snapshot，再从保存的 sequence 续传；401/404 清理失效恢复记录。
6. 取消时调用服务端 `/cancel`；组件卸载只 Abort 当前 Fetch。
7. 审批时只提交路径 approval ID 和 decision，不提交工具、参数或摘要。
8. 删除终态后调用 `/api/research`、拼接第二份答案和重新检索引用的代码。

## 兼容层规则

- legacy 与 durable 不双写，不共享 Run ID，不在路由内部互相代理。
- `POST /api/research` 保留为独立 RAG/审核学习 API，不再是 Agent UI 主链。
- Stage 4 的旧 SSE 教程是历史基线；新增页面不得照搬其 `streamRun()` 入口。
- 兼容端点没有在 M12 增加 HTTP deprecation header 或删除日期，不能宣称外部调用方已收到
  弃用通知。
- 删除前必须满足 ADR-0033 的消费者、通知、回归和新决策门槛。

## 验证清单

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_api backend.tests.test_persistent_run_api backend.tests.test_persistent_sse backend.tests.test_durable_run_projection -v
npm.cmd --prefix frontend run test:unit
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run test:e2e
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/check-continuity.ps1
```

验收时同时检查：

- `test_legacy_run_api_shape_is_unchanged_and_does_not_dual_write` 仍通过；
- `frontend/src` 没有 `/api/research`、`/runs/stream` 或 legacy Run 调用；
- 浏览器 E2E 明确拒绝 legacy 请求，并证明断线、刷新和审批仍属于同一 Run；
- 所有命令的实际结果进入 verification log，不能用本页的计划命令代替证据。

## 本次未迁移的生产能力

M12 不证明 OIDC/HttpOnly session、capability 撤销、CSP、Nginx、多实例低延迟通知、跨浏览器
矩阵、生产容量、usage 账本或成本门。这些不能通过删除兼容端点获得，仍由 M13 的认证、
观测、CI 和部署任务分别承接。
