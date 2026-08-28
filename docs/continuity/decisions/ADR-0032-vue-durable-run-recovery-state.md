# ADR-0032：Vue durable Run 刷新恢复与 capability 边界

- 状态：accepted
- 日期：2026-08-28
- 任务：`M12-T4`
- 依赖：`ADR-0029`、`ADR-0030`、`ADR-0031`

## 背景

M12-T1–T3 已提供匿名 capability、durable snapshot、持久 SSE sequence、引用和
usage 投影。旧 Vue 仍先调用 legacy `streamRun()`，流结束后再调用独立
`research()` 覆盖答案和引用，无法证明 UI 中的答案与证据属于同一 Run。

匿名 durable API 的后续查询必须发送 `X-Session-Token`。如果 capability 只存在
JavaScript 内存，页面刷新后即使保存了 Run ID 和 sequence 也无法查询 snapshot 或
续传事件；如果写入长期 `localStorage`，凭证暴露窗口又超过“当前标签页刷新恢复”的
需求。

## 决策

### 1. Vue 只消费 durable Run 主链

`agentApi.ts` 统一提供 durable create、snapshot、cancel、approval 与事件流请求。
新 Run 使用 `crypto.randomUUID()` 生成 `Idempotency-Key`；首个匿名键作为 capability
bootstrap，后续同 session Run 使用新的幂等键并通过 `X-Session-Token` 证明 owner。

删除 Vue 在流结束后调用 `/api/research` 的双链。最终 answer、citations、usage、error
均以同一 Run snapshot 为准；SSE 只负责实时进度和已持久化的中间投影。

### 2. 使用当前标签页的版本化恢复记录

仅在 `sessionStorage` 保存 `ai-agent-demo:durable-run:v1`，字段限于：

- capability、Run ID、Session ID；
- 最后已经成功应用的 EventStore sequence 与服务端 Run status；
- 待审批的 approval ID、工具名和过期时间。

不保存 prompt、回答、引用内容、事件 payload、工具参数、arguments digest、Memory、
API Key 或静态 Bearer Token；不使用 `localStorage`，也不输出 capability 到 UI、日志
或错误。`sessionStorage` 仍可被同源 XSS 读取，因此这只是教学应用的标签页级恢复
方案，不是生产会话安全结论；HttpOnly cookie、OIDC、撤销和 CSP 留给 M13。

恢复时先用 capability 查询 snapshot，再从已保存 sequence 的下一条事件续传。
401/404 会删除失效记录；存储不可用只显示恢复能力警告，不能取消或改写已经创建的
服务端 Run。

### 3. 用判别联合收窄稳定业务事件

前端 `AgentEvent` 只为已评审的 lifecycle、tool、approval、RAG、usage 和输出事件提供
判别分支；未知事件保留稳定事件名并只用于时间线展示。解析器校验 SSE ID 与 payload
sequence 一致、Run envelope、关键字段、有限分数和 usage 加总；状态机只按严格递增
sequence 应用事件，重复帧不产生重复 UI 副作用，序号缺口停止应用不完整状态。

Fetch 流用于发送 `X-Session-Token`，不改用无法附加该 header 的原生 EventSource。
连接提前结束时最多进行 3 次有界重连，每次先读权威 snapshot，再从当前 sequence
续传。组件卸载只断开订阅，不向服务端发送 cancel。

## 后果

- Vue 的答案、引用、usage、审批与工具轨迹使用同一 Run ID，刷新可恢复 snapshot 并
  从最后 sequence 继续。
- 页面展示 `usage=null` 为“未知”，不伪装成 0；成本只显示服务端投影值。
- M12-T4 只完成实现和 TypeScript/Vite 构建。SSE 分帧、无效 JSON、重复/缺口事件、
  Abort、审批、取消和真实刷新恢复仍须在 M12-T5 自动化验证后才能标记 verified。

## 未采用方案

- 继续调用 `/api/research`：会让独立请求覆盖主 Run 的答案和证据。
- 把 capability 放入 URL：会进入浏览历史、代理和访问日志。
- 使用 `localStorage`：超出当前标签页恢复范围并扩大长期凭证暴露面。
- 本任务引入 Pinia、Axios、UI 库或生产认证：不符合 M12-T4 的最小迁移边界。

## 验证依据

- `frontend/src/types/agent.ts`
- `frontend/src/services/agentApi.ts`
- `frontend/src/composables/useAgentDesk.ts`
- `V-20260828-011`
