# ADR-0034：基于持久 Run 事件重建 Trace、Metrics 与 usage ledger

- 状态：accepted
- 日期：2026-08-28
- 任务：`M13-T1`
- 依赖：`ADR-0007`、`ADR-0008`、`ADR-0029`、`ADR-0031`

## 背景

M12 已让 durable Run 的生命周期、过程事件、RAG citation 和 SDK Run 级 aggregate usage
进入同一个 owner-scoped EventStore，但公开快照只保留最新有效 usage；它没有 Trace、Metrics、
usage ledger 或成本来源语义。旧 `RunObserver` 仍服务 M1–M7 同步教学链，不能被直接改写成
durable Runtime 的观测实现。

领域 `UsageRecord` 表示**一次模型调用**，而当前 Agents SDK 只可靠提供一次 Run 的聚合 usage，
没有逐调用 duration 或可信费用。若把聚合事件强行写成 `UsageRecord`，会伪造证据；若另建
usage 表并在 EventStore 之后双写，又会增加无法原子提交的新崩溃窗口。

## 决策

### 1. 保留旧 RunObserver，durable 主链增加独立投影

`backend.app.observability.runs.RunObserver` 及旧 `/api/observability/runs` 不修改。M13 新增
`EventRunObservability`，只读取同一个 owner-scoped durable Run 的持久事件，重建：

- run、runtime node、plan/context node、model 和 tool spans；
- span duration、run 总数、retry 和 token metrics；
- 每条有效 `scope=run` usage 事件组成的 Run 级 ledger；
- 最新累计 usage 对应的 cost summary。

公共读取入口固定为：

```text
GET /api/durable/runs/{run_id}/observability
```

它复用 durable Run 的 Principal/capability owner 规则；missing 与 cross-owner 均返回相同 404。

### 2. EventStore 是账本与 Trace 的可重建真相源

本任务不增加表、migration 或 EventStore 之后的业务双写。内存和 PostgreSQL 都通过同一
EventStore Protocol 投影；PostgreSQL 关闭并重新打开后仍能按 run ID 重建相同 ledger 和
脱敏 Trace。

Run 级 usage 事件是累计快照，不能逐条相加。ledger 保留所有有效快照，cost summary 只取
sequence 最新的一条，避免累计 Token 和费用被重复计算。畸形事件被忽略，之前的有效快照
继续可读。

它不是领域 `UsageRecord`：后者仍严格表示一次模型调用，必须包含单次 duration。只有未来
Runtime 能提供真实逐调用证据时，才可创建该类型。

### 3. 未知费用保持未知，已知费用使用 Decimal

- `estimated_cost_usd=null` 必须配 `cost_source=unknown`；不能改成 0。
- 事件报告的已知有限非负费用通过 `Decimal(str(value))` 投影。
- 已知费用但历史事件没有 source 时标记为 `event_reported_unversioned`，不冒充版本化价格表。
- 当前任务不新增价格表，也不强制 `max_cost_usd`；逐调用预算与版本化定价继续由 `KI-018`
  跟踪。

### 4. Trace 和 Metrics sink 可替换，但不是正确性真相

定义 async `TraceSink` 和 `MetricsSink` Protocol，并提供 No-op 与 deterministic in-memory
adapter。Container 可显式注入其它 adapter，不引入 OpenTelemetry 或 vendor 依赖。

Coordinator 只在事件已经持久化后调用 observer。终态事件触发完整 Run 投影，再向 sink 导出；
sink 超时或失败只写 run ID/sequence 的安全 warning，不回滚事件、不改变 Run 终态，也不阻止
HTTP 以后从 EventStore 重新查询。

### 5. Trace 默认且强制脱敏

Trace、Metric 与新 HTTP 响应采用显式字段白名单，只包含：

- run/span/metric 的稳定 ID；
- layer、受控名称、status、step、attempt；
- 持久时间、有限 duration；
- 稳定 error code/category；
- provider/model 标签、Token 和费用来源。

prompt、answer、model delta、RAG excerpt、Memory、工具 arguments/results、raw exception、owner、
session、Key 和 DSN 均不进入这些记录。工具名是服务端工具目录元数据；模型名是服务端配置
元数据。既有 `AI_AGENT_TRACE_INCLUDE_SENSITIVE=true` 继续 fail closed，不能打开敏感 Trace。

### 6. Duration 的证据强度必须明确

- run/runtime node duration 来自持久 `run.started` 与终态事件时间差；
- tool/plan span 优先配对 started/terminal 事件，Manual tool/model 的受控 duration 字段优先；
- 只有单个失败或 usage 事件、没有成对时间边界时，duration 保持 `null`；
- 不用事件间隔猜测 Provider 纯模型耗时，也不把整段 Runtime 时间冒充单次模型调用时间。

因此一次失败可以从 run ID 定位 layer、step、稳定 code、Run 总耗时和 cost summary；某个细分
span 没有可靠边界时，其耗时仍可能未知。

## 后果

- M12 快照的 usage 改用同一 ledger 投影，旧 JSON 形状不变。
- 新 endpoint 可以在应用重启后排查成功、重试、工具拒绝、模型失败和 RAG 失败；外部 sink
  只负责导出，不负责恢复或业务正确性。
- 没有新数据库 schema，也没有 EventStore/usage table 双写一致性问题。
- 本任务不等于生产 OpenTelemetry collector、跨服务 trace propagation、逐调用 Provider usage、
  版本化价格表或硬成本门；这些边界不得被文档或 UI 夸大。

## 未采用方案

- 把 SDK aggregate usage 写成一条 `UsageRecord`：缺少逐调用 duration/cost，会伪造领域语义。
- 新建 usage 表并在事件提交后双写：产生新的结果未知窗口，且 EventStore 已有完整持久事实。
- 从进程内 sink 提供查询：重启后丢失，不能满足 durable Run 排障。
- 把 `model.output.delta`、工具参数/结果或 raw error 放进 Trace：会扩大敏感内容与 Prompt
  Injection 的传播面。
- sink 失败让 Run 失败：遥测 adapter 不应改写已经持久的业务终态。

## 验证依据

- `backend/tests/test_durable_observability.py`
- `backend/tests/postgres_store_integration.py`
- `V-20260828-014`
