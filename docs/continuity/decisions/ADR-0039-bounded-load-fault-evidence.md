# ADR-0039：有界负载与故障演练证据

- 状态：accepted
- 日期：2026-09-01
- 任务：`M13-T6`
- 依赖：`ADR-0034`、`ADR-0035`、`ADR-0037`

## 背景

M13-T1–T5 已分别建立观测、错误/重试、CI、单实例部署和受控进程边界，但仓库仍没有同一入口
覆盖并发 Run、慢客户端、数据库断开、模型限流和重启恢复，也没有把延迟、错误率和资源数据
固定为可复现证据。

直接引入通用压测平台会扩大依赖和操作面；把一次本机短样本称为生产容量又会产生错误结论。
故障注入还必须只作用于本次验证资源，并区分 HTTP 结果未知与已经明确失败的 Run。

## 决策

### 1. 一个标准库测量核心，两个证据作用域

`backend.app.evals.load_fault` 提供冻结报告和有界异步测量器，记录计数、稳定错误码、延迟分位、
吞吐、并发峰值和当前进程 RSS。离线作用域执行真实内存 Container、durable SSE 和
`ManualAgentLoop` 重试路径；localhost 作用域通过 Nginx/FastAPI/PostgreSQL durable HTTP 执行。

两者名称和 evidence scope 必须分开。确定性 Fake Model 的限流恢复不能冒充线上 Provider E4；
Probe 进程 RSS 也不能冒充服务端容器内存。

### 2. 报告只保留安全聚合值

测量器不存储输入、回答、capability、异常文本或 HTTP 正文。已知故障映射为稳定错误码，未知
异常统一为 `scenario_internal_error`。localhost 入口只接受显式 loopback HTTP origin，拒绝
凭据、路径和远程地址。

### 3. 故障只作用于唯一 Compose project

`scripts/verify-load-fault.ps1` 复用 M13-T4 verifier 的临时 secret 生命周期、健康检查、Nginx SSE
和 backend restart 合同。每次使用唯一 `ai-agent-demo-m13-load-*` project；数据库故障只能 stop/start
该 project 的 postgres，finally 只 down 该 project 及其卷，不删除镜像或触碰 M11 integration。

M13-T6 可显式跳过重复的 M13-T4 120 项数据库回归，但只能与 `-LoadFault` 同时使用。它仍必须
build/up、检查 migration/seed/health、验证 Nginx SSE 和 baseline restart；该 skip 不成为普通部署
验收的逃生开关。

### 4. 结果未知保持同键，明确终态后才换键

数据库恢复窗口中，Run create 可能已经提交，但响应查询失败。幂等重放可返回原 Run 且不再次
下发 `session_capability`；客户端继续使用自己持有的 capability 读取它。网络错误、5xx 或响应
未知时不得换键。

若读取明确得到 `failed/cancelled`，旧 Run 已终止，演练才可换新幂等键验证服务恢复；此动作最多
8 次并受总 deadline 限制。最终报告保留恢复前明确失败次数，不把它们从成功结论中隐藏。

### 5. 容量只记录重复工作点

当前默认 16 Runs、并发度 4；最多 100 Runs、并发度 16。多次完整演练均无错误后，只能称该
配置为当前机器上的可重复工作点，并报告所有运行的吞吐/延迟范围。点式 `docker stats` 不称为峰值，
短样本不外推生产 SLA 或最大容量。

## 后果

- 默认 Python 测量保持离线、确定性、无 Key、无新依赖；真实 Docker 仍需显式授权。
- 数据库断开必须 fail closed 为无响应或 5xx，不能静默退回内存成功；恢复 Run 和已完成 Run 的
  backend restart 读取都有明确断言。
- 恢复窗口中的短暂 terminal failure 被计数并允许有界新请求，不会把 result-unknown 误当成可
  重复副作用，也不会把一次最终成功描述为无降级。
- 仍未验证线上 Provider 限流、多机/HA、进行中 Run 的 backend hard-kill、长时间 soak、峰值资源、
  TLS、公网入口或生产负载。

## 未采用方案

- 引入 Locust/k6：当前 16/4 工作点和故障合同可由标准库覆盖，不为单一任务增加依赖。
- 对远程 URL 开放 Probe：扩大 SSRF、凭据和付费调用面，不属于本任务。
- 数据库断开时回退内存：会把持久 durable Run 降级为不可恢复的不同语义。
- 所有失败都换新幂等键：结果未知时可能重复副作用。
- 只保留最后一次成功：会删除恢复窗口、脚本缺陷和非确定性失败证据。

## 验证依据

- `backend/tests/test_load_fault_eval.py`
- `backend/tests/test_load_fault_script.py`
- `scripts/verify-load-fault.ps1`
- `docs/m13-load-fault.md`
- 本任务对应 verification 记录
