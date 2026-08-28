# ADR-0029：M12 持久 Run HTTP 所有权与幂等创建

- 状态：accepted
- 日期：2026-08-28
- 任务：`M12-T1`
- 依赖：`ADR-0006`、`ADR-0007`、`ADR-0012`、`ADR-0022`、`ADR-0026`

## 背景

M11 已让默认 Container 提供 durable RunStore、EventStore、Coordinator 与 application admission，但 HTTP 仍调用进程内 `InMemoryRunService`。直接替换旧路径会改变 M1–M10 的响应与 SSE 行为，也会把旧记录双写到两条链。

M12-T1 需要单独提供创建、查询、会话列表、取消和审批 API。API 既要保持 RunStore 的 `(owner_id, idempotency_key_digest)` 语义，也要让匿名请求在应用重启后仍能以 capability 读取自己创建的 Run；原始 capability、幂等键和工具参数不得保存或出现在日志。

## 决策

### 1. 使用独立 durable 路径，不迁移旧接口

M12-T1 新增 `/api/durable/runs`、`/api/durable/sessions/{session_id}/runs`、Run 查询、取消和审批子路由。创建先写入 RunStore，成功创建者才在后台调用 application-owned `RunCommands.execute()`；重放只返回既有快照，不再次调度 Runtime。

旧 `/api/sessions/.../runs`、`/api/runs/{id}` 和旧 SSE 不修改，也不向 durable Store 双写。M12-T2 之后才为 durable 路径增加持久事件 SSE，M12-T6 再决定兼容层的替代时间点。

### 2. 将匿名初次幂等键作为 capability bootstrap

认证请求的 owner 只来自 `Principal.principal_id`。匿名初次创建要求没有空白或控制字符、编码长度至少 32 字节的 `Idempotency-Key`；客户端应使用密码学随机值。其 SHA-256 仅以 `anonymous-capability-v1-<digest>` 形式进入 durable owner 字段，原始值不会写入 Run、Event、日志或错误。

初次匿名请求以该 capability 派生稳定 owner 和 session ID，因此同一请求在响应丢失后仍能凭相同 `Idempotency-Key` 命中同一个 Run。首次 `202` 响应只向该调用者回显 capability；后续请求把它放在 `X-Session-Token`，并使用独立的 `Idempotency-Key` 创建同一 session 的下一 Run。长度下限是接口防呆，不是 entropy 证明；前端必须使用安全随机源生成值。

这个最小纵切不新增空 session 表：首个 durable Run 是 session 所有权锚点。客户端提供 `session_id` 时，服务端必须先以 owner scope 在 RunStore 找到已有记录，否则统一返回内容无关的 404。这样不会让任意 client-selected session ID 进入 Context/Memory 路径。

### 3. 查询快照与审批绑定保持 server-owned

查询响应固定含状态、答案、引用、usage 和安全错误形状。M12-T1 尚未把 RAG/usage 聚合进主 Run，故 citations 为空、usage 为 `null`；M12-T3 只可从同一 Run 的持久事件/结果填充它们。

审批 HTTP 只接受路径中的 approval ID 和 `approve`/`reject`。它从 owned `run.waiting_approval` 事件读取 tool call ID、tool name 和 arguments digest，再交给 Coordinator；Coordinator 仍调用 ApprovalStore 的完整绑定校验及单次决议。客户端不得提交或覆盖这些字段。取消仍由 Coordinator 进行版本化 terminal commit，终态 Run 不会重开。

## 后果

- 默认 memory 与 opt-in PostgreSQL composition 都通过已有 Container RunStore/EventStore/Coordinator 提供同一 HTTP 行为。
- API 可在 Runtime 执行期间立刻返回 `202` 和稳定 Run ID；SSE、实时事件、断线续传和 Vue 状态机仍属 M12-T2 至 T5。
- 认证 owner、匿名 capability、会话列表、幂等冲突、取消和审批都不依赖 legacy RunService。
- 当前 capability 没有过期、撤销、速率限制或独立 session 生命周期；这些生产控制不在 M12-T1 范围。

## 未采用方案

- 直接复用或改写旧 `/api/sessions` / `/api/runs`：会破坏兼容响应并造成 durable/legacy 双写风险。
- 相信 body 中的 owner、role、tool、arguments digest 或 approval binding：会让客户端绕过可信身份和精确审批。
- 新增无 Run 的内存 session registry：重启后会丢失 capability 所有权，和 durable API 目标冲突。
- 在 M12-T1 先做 SSE、Vue、RAG/usage 聚合、持久 capability 撤销或生产 OIDC：这些分别由 M12-T2 至 T5 或 M13 承接。

## 验证依据

- `backend/tests/test_persistent_run_api.py`
- `backend/tests/test_api.py`
- `V-20260828-007`
