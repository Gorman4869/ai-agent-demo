# M13-T1 交接：durable Trace、Metrics 与 usage ledger

- 日期：2026-08-28，Asia/Shanghai
- 当前任务：`M13-T1 / verified`
- 下一任务：`M13-T2 / planned`
- 验证基线：`3fcc91b`
- 验证记录：`V-20260828-014`
- 关联决策：`ADR-0034`
- 任务等级：A 类持久化投影、公共 API、遥测隔离与成本语义
- 在线模型/付费调用：未执行，模型费用 0
- 远程仓库：未配置，未 push

## 本次结果

durable Run 现在可按 owner + run ID 从同一个 EventStore 重建 Trace、Metrics、usage ledger
和 cost summary。`EventRunObservability` 生成 run/runtime、plan/context、model 与 tool spans，
只保留稳定 ID、层级、步骤、attempt、状态、可信时间和稳定错误分类；prompt、answer、delta、
RAG excerpt、Memory、工具参数/结果、raw error、owner/session 和 secret 不进入投影或 sink。

`RunTelemetryExporter` 在终态事件成功持久化并通知后，把完整投影导出到可替换 async sink。
sink 失败或超时只生成安全 warning，不回滚、不改写 Run，也不影响 HTTP 从 EventStore 重建。
旧领域 `RunObserver` 与 `/api/observability/runs` 均保留，未被新 sink 协议取代。

新增 `GET /api/durable/runs/{run_id}/observability`，复用 durable API 的 Principal、owner 和
匿名 capability 规则；不存在和跨 owner 均返回相同 404。M12 既有 snapshot usage 公开 shape
不变，内部改由同一 durable cost projection 提供。

## 修改文件

- `backend/app/observability/durable.py`
- `backend/app/observability/__init__.py`
- `backend/app/services/run_coordinator.py`
- `backend/app/postgres_execution.py`
- `backend/app/container.py`
- `backend/app/api/schemas.py`
- `backend/app/main.py`
- `backend/tests/test_durable_observability.py`
- `backend/tests/postgres_store_integration.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/continuity/decisions/ADR-0034-event-sourced-run-observability.md`
- `docs/m13-observability.md`
- `docs/implementation-plan.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/status.md`
- 本 handoff

没有新增依赖、数据库 migration、usage 表、前端代码或学习者 `docs/progress.md`；没有修改、
删除或代理 legacy sessions/runs、Research API、旧 SSE 或旧观测 API。

## 验证与失败尝试

- 新 `backend.tests.test_durable_observability` 最终 8 项通过：成功、累计 usage 不重复求和、
  模型重试、工具拒绝、模型失败、RAG 失败、sink 故障隔离和 owner/cross-owner HTTP。
- observability/projection/Coordinator/Container/PostgreSQL composition/lifespan/API 聚焦回归
  128 项通过。
- 真实 PostgreSQL close/reopen 专项 1 项通过；完整 `postgres_store_integration` 114 项通过，
  不可达数据库负向用例保留一条预期 connection timeout。本机 integration DSN 只注入单次
  测试子进程，未读取或输出模型 Key、DSN 值或其他 secret。
- 完整后端在受控沙箱首次收集 651 项，但 35 项因 Windows Temp 写入拒绝报错，另有 2 项
  MCP 子进程从预期 timeout/协议错误变为 `process_unavailable`。相同完整命令经批准在沙箱外
  651 项通过，1 项既有 Windows symlink 能力跳过。
- `scripts/verify.ps1` 经批准在沙箱外通过：后端、Code Agent demo、`pip check`、Vue build、
  MCP TypeScript build 和 Compose config 全部成功。
- Node 22.16.0 下 Vue build 转换 19 modules，MCP TypeScript build 通过，无需切换 nvm。
- 未执行在线模型、DashScope、Embedding、外部网络或付费调用；未升级依赖或运行
  `npm audit fix`。

## 决策与边界

- EventStore 是可重建真相源；不在持久化之后再双写新的 trace/usage 表，避免 Run 成功但
  观测账本缺失或相反的双写分裂。
- `scope=run` 的 `model.usage` 是累计快照；ledger 保留有效 sequence，summary 只采用最新
  快照，不把累计值逐条相加。它与单次调用领域 `UsageRecord` 语义不同。
- 费用内部使用 `Decimal(str(value))`；没有可靠费用时保持 `null/unknown`，不能写成 0。
  旧事件若有费用但无来源，只标记为 `event_reported_unversioned`，不能冒充版本化价格表。
- 只有持久事件或受控 duration 字段能提供耗时证据；缺少成对边界的细分 span 保持
  `duration_ms=null`，不以整个 Run 耗时推断模型或工具耗时。
- `KI-018` 因持久 Run 级 usage/cost ledger 改为 mitigated，但逐调用 usage、版本化定价、
  `max_cost_usd` 硬门和在线低预算证据仍未完成。

## 未验证范围

- OpenTelemetry/vendor exporter、跨服务 propagation、多实例 sink 与生产观测后端。
- 逐调用 Provider Token/usage、版本化价格表、账单一致性和硬成本拒绝。
- M13-T2 的稳定错误目录、retryable、模型/工具/Run timeout、取消与副作用幂等策略。
- M13-T3 分层 CI、依赖升级，以及 M13-T4 Docker/Nginx/健康检查/部署验收。

## 下一条原子动作

开始 M13-T2 前按 AGENTS 顺序重新恢复并审计现有 Runtime/Coordinator/ToolRegistry 的错误
分类、retryable 信号、timeout/cancel 和持久 ToolExecution 幂等边界。先用故障矩阵区分
“允许重试”“结果未知禁止自动重试”和“稳定终态”，再决定最小实现；不得把 M13-T1 的
Trace、ledger 或 sink 成功当成重试授权，也不提前进入 M13-T3/M13-T4。未经新授权不读取
Key、不执行在线 Provider、不升级依赖、不配置远程 Git。

## 交接时工作区

本 handoff 创建时，以上 M13-T1 文件均为待提交改动，基线 HEAD 为 `3fcc91b`；结束前应先
运行连续性检查、`git diff --check` 和最终范围审计，再只提交上述任务文件。
