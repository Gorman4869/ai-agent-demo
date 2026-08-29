# M13-T2 交接：稳定错误、安全重试、超时与取消

- 日期：2026-08-29，Asia/Shanghai
- 当前任务：`M13-T2 / verified`
- 下一任务：`M13-T3 / planned`
- 验证基线：`892d863`
- 验证记录：`V-20260829-001`
- 关联决策：`ADR-0035`
- 任务等级：A 类共享 Runtime/ToolRegistry 公共契约、取消/副作用与错误安全
- 在线模型/付费调用：未执行，费用 0
- 真实 PostgreSQL：本任务未读取 DSN、未运行 integration
- 远程仓库：未配置，未 push

## 本次结果

新增 `backend.app.reliability`，统一 Provider、MCP、Tool、Store、Run 和预算的内容无关错误目录、
指数退避及 fail-closed 重试决策。`retryable` 只描述错误类别可能是瞬态；实际重试还必须通过
次数、remaining deadline、幂等/可重放、副作用、持久幂等键和 result-unknown 检查。

Manual 与 LangGraph 只对显式瞬态模型错误使用可取消退避；Agents SDK 使用公开
`ModelRetrySettings`、显式 backoff 和 provider-suggested policy，OpenAI HTTP client 仍关闭自身
重试。默认应用组合为模型最多 2 次重试、只读工具最多 1 次重试。

共享 ToolRegistry 记录稳定 prior error code、attempt 和 delay，且只重试无副作用工具。当前主链
没有向普通工具调用注入持久外部结果仲裁证明，因此副作用工具即使已批准并遇到结果未知 I/O
故障也只执行一次。Store mutation、终态 commit 和整个 Runtime 没有套通用 retry loop。

MCP adapter 现在区分 timeout、disconnect、remote error、invalid response 和 request rejected。
`CancellationToken` 增加 remaining budget 和可唤醒等待；取消在退避期间获胜时不开始下一尝试。
`tool.retrying` 只携带安全元数据，并由 durable observability 映射为 tool span 与
`agent.tool.retry` metric。

## 修改文件

- `backend/app/reliability.py`
- `backend/app/agent/cancellation.py`
- `backend/app/agent/manual_loop.py`
- `backend/app/agent/manual_runtime.py`
- `backend/app/agent/graph_runtime.py`
- `backend/app/agent/sdk_runtime.py`
- `backend/app/agent/sdk_tools.py`
- `backend/app/integrations/mcp/client.py`
- `backend/app/tools/registry.py`
- `backend/app/tools/__init__.py`
- `backend/app/settings.py`
- `backend/app/services/run_service.py`
- `backend/app/container.py`
- `backend/app/observability/durable.py`
- `backend/.env.example`
- `backend/tests/test_reliability.py`
- `backend/tests/test_settings.py`
- `backend/tests/test_manual_agent_loop.py`
- `backend/tests/test_runtime_comparison.py`
- `backend/tests/test_openai_agents_runtime.py`
- `backend/tests/test_mcp_tool_adapter.py`
- `backend/tests/test_durable_observability.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/continuity/decisions/ADR-0035-fail-closed-retry-and-cancellation.md`
- `docs/m13-reliability.md`
- `docs/implementation-plan.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/status.md`
- 本 handoff

没有新增依赖、数据库 migration、前端代码、CI 配置、Docker/Nginx 配置或学习者
`docs/progress.md`；没有读取/写入 `.env`、Key、Token 或 DSN。

## 验证与失败尝试

- 恢复基线 127 项在沙箱内因本地 MCP 子进程变成 `process_unavailable`，出现 2 failures +
  2 errors；相同命令经批准沙箱外 127 项全部通过。
- 稳定策略/设置/三 Runtime/SDK/观测聚焦 94 项通过；最终策略和设置边界 33 项通过。
- 真实本地 Python MCP STDIO 定向 7 项通过；没有远程 transport 或网络。
- Coordinator、ToolExecution、Runtime 合同、LangGraph 重规划与 Container 100 项通过；Store
  故障、持久取消竞争、deadline 和结果未知恢复保持 fail closed。
- 最终完整后端 666 项通过，1 项既有 Windows symlink 能力跳过。日志中的 Provider URL 来自
  测试 MockTransport；没有真实 Provider 请求。
- 最终连续性检查通过 52 个稳定任务和 146 个 Markdown 文件；`git diff --check` 无 whitespace
  错误，最终 status 只包含 M13-T2 代码、测试和证据文档。

## 决策与边界

- 有副作用工具没有可信持久幂等键时永不自动重试；一次人工审批不是持久幂等证明。
- 当前实现刻意不开放“有持久键即可重试”的生产路径，因为普通工具调用还没有外部结果仲裁
  证据。未来放宽需要新 ADR、持久 Store 接线和结果未知恢复测试。
- Store 的 command/event ID、CAS、lease 和 recovery 继续拥有自己的重放协议；通用重试不能
  绕过它们。数据库不可用不静默回退内存。
- Trace/ledger 只记录已发生事实，不授予重试。retry event 不包含参数、结果或异常文本。
- 同步 worker thread、SDK transport 和已发出的远端请求仍不能硬取消；`KI-017` 保持 open。

## 未验证范围

- 副作用工具的持久幂等自动重试、外部 exactly-once、连接结果未知生产仲裁。
- Windows/Linux 硬线程或进程树取消、生产 MCP reconnect/容量与远程 transport。
- 本任务的真实 PostgreSQL 故障注入、多进程终态竞争和硬进程中断；复用 M11 已验证持久协议。
- 逐调用 Provider usage、版本化价格、`max_cost_usd` 硬门和经单独授权的在线低预算证据。
- M13-T3 分层 CI、M13-T4 Docker/pgvector/Nginx 部署、M13-T5 Code Agent 资源安全和
  M13-T6 故障演练。

## 下一条原子动作

开始 M13-T3 前按 AGENTS 顺序恢复，先只读审计 `scripts/verify.ps1`、现有 test/build/integration/
online opt-in 入口和 `KI-008`。设计分层门时必须保证：任何必跑层失败都不能打印“全部通过”，
跳过项显式汇总，默认 CI 不接收仓库密钥且不因在线任务未授权而失败。不要提前执行 M13-T4
镜像、容器健康或 Nginx SSE 验收；依赖升级仍须单独授权和任务边界。

## 交接时工作区

本 handoff 创建时，以上 M13-T2 文件均为待提交改动，基线 HEAD 为 `892d863`；结束前应运行
连续性检查、`git diff --check`、最终范围审计，并只提交本任务文件。提交后的新 HEAD 由下一条
verification 或 handoff 记录。
