# M13 durable Run 可观测性合同

本页记录 M13-T1 已实现的工程接口与排障边界。旧同步教学链的 `RunObserver` 继续保留；这里
只描述 `/api/durable` 主链。

## 查询入口

```http
GET /api/durable/runs/{run_id}/observability
Authorization: Bearer <token>
```

匿名 durable Run 使用创建时返回到当前标签页的 `X-Session-Token`。读取规则与 Run snapshot
完全相同：只有 owner 可见，missing 与 cross-owner 均为 404。

响应包含四部分：

| 字段 | 含义 | 真相源 |
| --- | --- | --- |
| `spans` | run、runtime/node、model、tool 的脱敏 span | 同 Run 的持久事件 |
| `metrics` | 已知 duration、run count、retry count、Token | span 与最新有效 usage |
| `usage_ledger` | 每条有效 Run 级累计 usage 快照 | `model.usage` 事件 |
| `cost_summary` | 最新累计 usage 与费用来源 | ledger 最新 sequence |

## 固定排查顺序

拿到一个失败 run ID 后：

1. 先找 `layer=run` 的 span，确认终态和总耗时。
2. 找 `status=failed` 或 `retrying` 的最细 layer。
3. 读取该 span 的 `step`、`error_code` 和 `error_category`。
4. 查看 `cost_summary`；`null/unknown` 表示没有可信费用，不是零费用。
5. 需要业务证据时再查普通 Run snapshot 的 citations；不要从 Trace 推断答案事实正确性。

典型定位：

| 事件/失败 | 主要 layer | 关键字段 |
| --- | --- | --- |
| RAG 准备失败 | `node / context.prepare` | `step`、`context_unavailable` |
| 模型重试 | `model / model.request` | `attempt`、`model_retry`、已知 duration |
| 模型终态失败 | `model / model.run` | terminal failure code/category |
| 工具权限拒绝 | `tool / tool.<server-owned-name>` | `step`、稳定 tool error code |
| 工作流步骤失败 | `node / plan.step` | `attempt`、workflow error code |

## Usage 与成本规则

- 当前 SDK `scope=run` 是累计快照；两条快照不会相加，summary 取最后一条有效 sequence。
- Token 必须为非负整数，`total=input+output` 且 total 大于 0。
- 已知费用内部用 `Decimal`；HTTP 以十进制字符串返回，避免再次引入二进制浮点误差。
- `estimated_cost_usd=null` 必须保持 `cost_source=unknown`。
- 当前没有版本化价格表或逐调用硬成本门，`max_cost_usd` 仍不能描述为调用前强制预算。

## 脱敏与导出

Trace/Metric 只允许稳定 ID、layer/name、status、step/attempt、时间、duration、错误分类和 usage
元数据。prompt、answer、delta、RAG excerpt、Memory、工具 arguments/results、raw exception、owner、
session、Key 和 DSN 不进入响应或默认 sink。

`ApplicationContainer.create/open()` 可以显式注入 async `TraceSink` 和 `MetricsSink` adapter。
默认 No-op，不增加网络或第三方依赖。导出只发生在终态事件持久化之后；sink 失败不改写 Run，
以后仍可从 EventStore 重建。

## 验证命令

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_durable_observability -v
```

真实 PostgreSQL 重启验证使用 `backend.tests.postgres_store_integration.PostgresDurableObservabilityTest`，
只连接本机 integration 数据库；默认离线测试不要求 DSN、API Key 或在线 Provider。
