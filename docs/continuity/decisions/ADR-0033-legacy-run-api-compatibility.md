# ADR-0033：M12 legacy Run 与 Research API 兼容边界

- 状态：accepted
- 日期：2026-08-28
- 任务：`M12-T6`
- 依赖：`ADR-0029`、`ADR-0030`、`ADR-0031`、`ADR-0032`

## 背景

M12-T1 至 T5 已提供独立的 `/api/durable` Run 创建、快照、持久事件 SSE、取消、
审批、同 Run 引用与 usage 投影，以及只消费这条主链的 Vue 状态机。仓库同时保留三类
较早契约：同步 legacy Run、完成后回放的 POST SSE，以及独立 Research 工作流。

这些契约的响应形状、所有权和执行时序不同。直接把旧路径改写为 durable 代理会让既有
调用方在没有迁移的情况下收到 `202`、多状态 Run、持久 cursor 或新的 capability 规则；
同时向两条 Store 双写又会产生两个不一致的 Run。M12-T6 必须明确“主链已替代”与“端点
已删除”不是同一件事。

## 决策

### 1. Vue 的 legacy 双链主流程被取代

Vue 生产源码只允许使用 `/api/durable`：创建 Run、读取快照、按 sequence 订阅 SSE、
取消和审批。完成后再调用 `/api/research` 覆盖答案/引用，以及使用
`POST /api/sessions/{session_id}/runs/stream` 的旧 UI 编排，标记为 `superseded`。

这里的 `superseded` 只描述前端主流程，不表示对应 HTTP 端点已经删除、返回弃用头，
或允许清理其测试。

### 2. legacy HTTP 端点继续作为隔离兼容层

以下端点在本 ADR 后仍保留现有响应和测试：

- `POST /api/sessions`
- `GET /api/sessions/{session_id}`
- `POST /api/sessions/{session_id}/runs`
- `POST /api/sessions/{session_id}/runs/stream`
- `GET /api/runs/{run_id}`
- `POST /api/research`

legacy Run 继续只访问 `run_service`，durable Run 只访问 RunStore、EventStore 与
RunCommands；两边不得双写、共享 ID 或在路由内部静默互相代理。独立 Research API 继续
服务 Stage 3 的 RAG/审核实验和明确的直接调用方，但不能再作为 Agent UI 的最终答案来源。

### 3. 新调用方只采用 durable 契约

新页面和业务集成不得继续扩展 legacy Run。它们使用：

- `POST /api/durable/runs` 创建或幂等重放；
- `GET /api/durable/runs/{run_id}` 读取权威快照；
- `GET /api/durable/runs/{run_id}/events?after=<sequence>` 实时观察和续传；
- `/cancel` 与 `/approvals/{approval_id}` 执行服务端绑定命令；
- `GET /api/durable/sessions/{session_id}/runs` 恢复会话 Run 列表。

迁移调用方必须显式处理 `202`、`Idempotency-Key`、匿名 capability、非终态、sequence、
断线恢复、取消和审批，不能只替换 URL。

### 4. 删除端点需要新的、可验证的迁移决策

M12 不设置一个没有调用数据支持的删除日期。未来删除任一兼容端点前，至少需要：

1. 列出仓库内外已知消费者和迁移负责人；
2. 提供可观察的弃用通知或版本策略；
3. 证明消费者已改用 durable 契约且没有双链覆盖；
4. 运行新旧契约、前端和文档回归；
5. 新增取代本 ADR 的决策，并把具体端点状态标记为 `superseded`。

没有这些证据时，兼容测试是保护边界，不是待删除的冗余测试。

## 后果

- Vue 的答案、引用、usage、工具、审批和终态可继续由一个 durable Run 核验。
- Stage 3/4 的旧练习仍可运行，但必须标明它们是历史学习链，不代表当前 Agent UI 架构。
- 后端暂时承担两套隔离契约的维护成本；这是避免无通知破坏调用方的明确取舍。
- 本任务不增加弃用 header、版本路由、遥测、生产认证或外部消费者清单；这些需要实际
  产品和部署上下文，不能由课程仓库猜测。

## 未采用方案

- **立即删除旧端点**：仓库测试通过不能证明仓库外没有消费者。
- **让旧路径代理 durable 路径**：状态、状态码、认证、时序和响应结构均不兼容。
- **legacy 与 durable 双写**：会产生两个权威 Run，并扩大结果未知与恢复冲突。
- **删除独立 Research API**：它仍是 RAG/审核教学接口；被替代的是 Agent UI 的双链使用。
- **把永久兼容当承诺**：保留没有期限，但仍允许未来在有迁移证据时通过新 ADR 删除。

## 验证依据

- `backend/tests/test_api.py`
- `backend/tests/test_persistent_run_api.py`
- `backend/tests/test_persistent_sse.py`
- `frontend/tests/unit/agentApi.spec.ts`
- `frontend/tests/unit/useAgentDesk.spec.ts`
- `frontend/tests/e2e/durable-run.spec.ts`
- `docs/m12-api-migration.md`
