# M13 生产观测与故障恢复一页速查表

## 一句话定义

Log 记录一次离散事实，Metric 说明一段时间有多少、是否恶化，Trace 还原一个 Run 经过哪些
步骤；Run snapshot 给当前权威状态，citation 才说明回答使用了什么证据。

## 五种信号

| 信号 | 最适合回答 | 不能单独证明 |
| --- | --- | --- |
| Log | 这一次发生了什么稳定事件/错误 | 全局影响、完整调用链 |
| Metric | 错误率、P95、吞吐、重试是否异常 | 某个 Run 的精确步骤 |
| Trace | 哪一层、哪一步、哪次 attempt 失败 | 答案事实正确或生产容量 |
| Snapshot | Run 当前权威状态、答案、citation、usage | 实时过程的全部原因 |
| EventStore | 持久事件顺序和恢复依据 | 前端展示或外部副作用 exactly-once |

## 拿到 Run ID 后

```text
owner/capability
  -> Run snapshot
  -> observability: run span
  -> 最细 failed/retrying node/model/tool
  -> step + error_code + error_category + attempt + duration
  -> metrics 看影响范围
  -> usage/cost 看 known 或 unknown
  -> 结果未知？六道重试门
  -> 最小恢复与五证
```

## 常用 span

| 故障 | layer / name | 优先字段 |
| --- | --- | --- |
| Context/RAG 准备失败 | `node / context.prepare` | step、`context_unavailable` |
| 模型重试 | `model / model.request` | attempt、delay、`model_retry` |
| 模型终态失败 | `model / model.run` | error code/category |
| 工具权限/执行失败 | `tool / tool.<server-name>` | step、side-effect policy |
| 工作流步骤失败 | `node / plan.step` | attempt、workflow error |

## 六道重试门

```text
retryable stable error
  + retries remaining
  + durable idempotency key for side effect
  + idempotent and replay-safe
  + result-unknown still replay-safe
  + backoff < remaining deadline
= 才允许下一次尝试
```

审批不是幂等键。副作用、Store mutation、结果未知和整个 Runtime 默认不自动重试。

## Usage 与成本

- `scope=run` 是累计快照：保留 ledger，summary 取最新有效 sequence，不相加。
- `usage=null`、`estimated_cost_usd=null` 或 `cost_source=unknown` 都是未知，不是 0。
- Decimal 字符串是估算表达，不等于 Provider 账单。
- 当前没有逐调用 usage、版本化价格表或调用前 `max_cost_usd` 硬门。

## 敏感信息边界

允许：稳定 ID、layer/name、status、step/attempt、时间、可信 duration、稳定错误分类和 usage
元数据。

禁止：Key、Authorization、DSN、owner/session 原值、prompt、answer/delta、RAG excerpt、Memory、
完整工具 arguments/results、源码/命令输出和 raw exception。

## 恢复五证

1. 新 Run 成功；
2. 故障前已完成 Run 仍可读；
3. liveness、readiness、migration/seed 满足；
4. Run/EventStore 收敛且 unknown 被明确保留；
5. 临时 project、网络、卷、进程和 secret 精确清理。

## 高频故障

| 现象 | 第一检查点 | 安全动作 |
| --- | --- | --- |
| 429/临时不可用 | model attempt + deadline | 有界指数退避 |
| 401/请求非法 | 稳定非重试错误 | 修配置/合同，不重试 |
| 工具 timeout | side effect + result unknown | 只读可过门；副作用停止 |
| DB 断开 | readiness + Store 状态 | fail closed，不回退内存 |
| SSE 不实时 | EventStore sequence + proxy buffering | snapshot/续传，不取消 Run |
| CI 少跑一层 | 七层最终汇总 | required 缺失失败，online 未授权 skip |
| 容器 running 但不可用 | readiness/migration/业务纵切 | 按依赖恢复并验证 |
| 代码进程残留 | process tree cleanup | 终止整树，不只 kill parent |
| cost 为 0 | source 是否 unknown | 显示“未知” |

## 最小命令

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_durable_observability -v
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_reliability backend.tests.test_mcp_tool_adapter -v
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/check-continuity.ps1
```

有状态 Docker 部署/故障演练和在线 Provider 仍需本次明确授权。完整处置见
[M13 故障响应手册](m13-incident-handbook.md)。

## 五问自检

1. 当前问题需要 log、metric、trace、snapshot 还是 citation？
2. 最细失败层和稳定错误码是什么？
3. 结果是否未知，六道重试门是否全部通过？
4. 恢复后是否同时具备五类证据？
5. 哪些结论仍只是本地、Mock、单实例或短样本？
