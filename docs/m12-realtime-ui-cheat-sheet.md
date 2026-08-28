# M12 统一 Run 与实时 UI 一页速查表

## 一句话定义

durable Run 是一次长任务的持久业务身份；EventStore 保存递增流水，SSE 传递增量，
snapshot 提供权威恢复。Vue 只观察和发送显式命令，不拥有身份、审批或副作用真相。

## 三张最小图

```text
状态：queued -> running -> waiting_approval -> running -> terminal

事件：Runtime -> EventStore(sequence) -> notifier -> SSE -> Vue

恢复：sessionStorage -> snapshot -> terminal
                           -> non-terminal -> events?after=lastSequence
```

终态只有 `completed | failed | cancelled`。SSE 断开、组件卸载和标签页关闭都不自动改变
Run 状态。

## 组件职责

| 组件 | 负责 | 不负责 |
| --- | --- | --- |
| RunStore | owner、session、状态、version、终态 | 过程事件和 UI cursor |
| EventStore | append-only 业务事件与 sequence | graph checkpoint、前端状态 |
| notifier | commit 后低延迟唤醒 | 保存 payload、保证历史正确性 |
| SSE | 回放/实时传输、heartbeat | 持久化、业务取消 |
| snapshot | 当前权威 Run、答案、引用、usage、错误 | 实时逐 token 体验 |
| sessionStorage | 当前标签页恢复 capability/cursor | 长期登录、答案/工具参数存储 |

## durable API 最小表

| 动作 | 方法与路径 | 关键输入 |
| --- | --- | --- |
| 创建/重放 | `POST /api/durable/runs` | `Idempotency-Key`、可选 `session_id`、capability |
| 查快照 | `GET /api/durable/runs/{id}` | Principal 或 `X-Session-Token` |
| 订阅/续传 | `GET /api/durable/runs/{id}/events?after=N` | 排他 cursor N |
| 恢复列表 | `GET /api/durable/sessions/{id}/runs` | 同 owner scope |
| 取消 | `POST /api/durable/runs/{id}/cancel` | 不用关闭 Fetch 代替 |
| 审批 | `POST /api/durable/runs/{id}/approvals/{approval_id}` | body 只含 `approve/reject` |

## 前端恢复算法

1. 读取版本化记录：capability、Run/session ID、last sequence、status、公开 approval。
2. 用 capability 查询 snapshot；401/404 清理记录，不降级为无鉴权读取。
3. 终态直接展示权威结果；非终态从 `after=lastSequence` 订阅。
4. 只应用 Run ID 一致、SSE id 与 payload sequence 一致、严格递增的事件。
5. 重复 sequence 忽略；缺口、无终态结束或网络错时先读 snapshot，再有界重连。
6. 组件卸载只 Abort 订阅；用户点击取消才调用服务端 `/cancel`。

## 证据与敏感边界

- citation 只来自同 Run 中已入选 prompt 的公开 RAG 片段，不在 snapshot 时重新检索。
- `usage=null` 是未知，不是 0 Token 或零成本。
- capability、prompt、Memory、工具参数、arguments digest 不进入 URL、UI、日志或事件。
- `sessionStorage` 可被同源 XSS 读取，只是教学应用的当前标签页恢复；生产认证留 M13。
- 浏览器提交 approval decision，不提交工具、参数、owner 或授权结果。

## legacy 兼容结论

```text
已 superseded：Vue 的 legacy POST SSE + 完成后 Research 覆盖答案双链
仍保留：legacy sessions/runs/stream/read 与独立 /api/research 端点和合同测试
```

新调用方只用 durable API。没有消费者清单、通知、回归和新 ADR 时，不删除或静默代理旧
端点；legacy 与 durable 永不双写。

## 常见错误速查

| 现象 | 第一检查点 | 安全判断 |
| --- | --- | --- |
| 创建重复 Run | 幂等键是否在同一次网络重试中保持 | 同请求复用；新业务请求换 key |
| 刷新 404 | capability/header 与 owner | 清理失效记录，不猜身份 |
| 重连重复答案 | last sequence 和 parser 去重 | `<= last` 忽略，缺口停用增量 |
| 终态后引用变化 | 是否又请求 `/api/research` | 只用同 Run snapshot |
| 关闭页面导致取消 | 是否把 Abort 映射为 `/cancel` | 观察断开不等于业务取消 |
| 审批参数可被改 | body 是否提交工具/参数 | 只发 decision，服务端绑定 |
| usage 显示 0 | null 是否被默认转换 | 显示“未知” |

排查顺序：owner/capability -> Run snapshot -> EventStore sequence -> SSE frame/cursor -> Vue
last sequence -> sessionStorage -> approval/cancel -> projection -> legacy 混链。

## 最小验收命令

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_api backend.tests.test_persistent_run_api backend.tests.test_persistent_sse backend.tests.test_durable_run_projection -v
npm.cmd --prefix frontend run test:unit
npm.cmd --prefix frontend run test:e2e
npm.cmd --prefix frontend run build
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/check-continuity.ps1
```

## 五问自检

1. EventStore、notifier、SSE 和 snapshot 为什么不能互相代替？
2. 幂等键、session ID、capability 与 Principal 分别解决什么问题？
3. 断流、Abort、刷新和 `/cancel` 对服务端 Run 的影响分别是什么？
4. 为什么终态后再次 Research 会破坏答案与引用的可核验性？
5. 旧 Vue 主链被替代后，为什么旧 HTTP 端点仍需兼容测试和新的删除决策？
