# M13-T2 稳定错误、重试、超时与取消

本文记录工程实现边界，不代替 M13 里程碑的完整跟练、题库和费曼材料。

## 目标与非目标

本任务统一三种 Runtime 的稳定错误语义、次数预算、指数退避、取消等待和只读工具重试，并继续
复用 Coordinator 的持久取消、总 deadline、终态 CAS 与恢复协议。

本任务不重试整个 Runtime，不新增依赖或数据库 migration，不实现副作用工具自动重试，不修改
前端，不进入 CI、Docker/Nginx 或在线 Provider 验收。

## 稳定错误目录

| 边界 | 稳定错误码 | `retryable` | 当前自动重试 |
| --- | --- | ---: | --- |
| Provider | `provider_rate_limited`、`provider_timeout`、`provider_unavailable` | 是 | 模型重试预算内允许 |
| Provider | `provider_auth_failed`、`provider_request_rejected`、`provider_invalid_response` | 否 | 不允许 |
| MCP | `mcp_timeout`、`mcp_disconnected` | 是 | 仅映射为无副作用工具时允许 |
| MCP | `mcp_remote_error`、`mcp_invalid_response`、`mcp_request_rejected` | 否 | 不允许 |
| Tool | `tool_timeout`、`tool_io_error` | 是 | 仅无副作用工具允许 |
| Store | `store_unavailable`、`store_operation_timeout` | 是 | 不对结果未知 mutation 做通用重试 |
| Run/预算 | `run_timeout`、`cancelled_by_user`、`max_steps_exceeded`、`model_call_budget_exceeded` | 否 | 不允许 |

`retryable=true` 只描述错误类别可能短暂恢复；是否真的重试还必须检查操作的幂等性、可重放性、
副作用、持久幂等键、结果是否未知、次数和剩余时间。

## 决策顺序

```text
稳定错误且 retryable
  -> 重试次数仍有余额
  -> 副作用操作具有持久幂等键
  -> 操作幂等且 replay-safe
  -> 结果未知时仍能证明 replay-safe
  -> 本次退避小于剩余 Run deadline
  -> 允许下一次尝试
```

任何一步缺少证据都 fail closed。当前普通工具调用没有持久外部结果仲裁证明，所以副作用工具即使
通过人工审批，也只执行一次。可把它类比为前端：重复一次 GET 查询通常可接受，但“提交订单”在
不知道第一次是否成功时，不能因为超时就自动再点一次提交。

## 三种 Runtime 的实际边界

- Manual：只捕获显式 `RetryableModelError`；退避可被同一个 `CancellationToken` 唤醒；只读工具
  经过共享 Registry 重试。
- Agents SDK：HTTP client 自身 `max_retries=0`，唯一模型重试层是公开 SDK retry settings；
  provider-suggested policy 配显式指数退避。SDK 只暴露无需审批、无副作用工具。
- LangGraph：模型节点和工具节点使用同一配置；`model.retrying`、`tool.retrying` 均先通过持久
  EventStore 再进入 durable Trace。
- MCP：Manager 仍负责一次远端调用 timeout；适配器把 timeout、断线、远端错误、非法结果和
  请求拒绝映射成不同稳定码，再由共享工具策略决定是否重试。
- Store/Coordinator：Store 错误不静默回退；持久 command、event ID、CAS、lease/recovery 拥有
  独立幂等协议，不套通用 retry decorator。Coordinator 继续仲裁取消与完成的持久赢家。

## 默认配置

| 环境变量 | 默认值 | 含义 |
| --- | ---: | --- |
| `AI_AGENT_MAX_MODEL_RETRIES` | 2 | 模型失败后的最大重试次数 |
| `AI_AGENT_MODEL_RETRY_INITIAL_DELAY_MS` | 100 | 第一次模型重试前等待 |
| `AI_AGENT_MODEL_RETRY_MAX_DELAY_MS` | 2000 | 模型退避上限 |
| `AI_AGENT_MAX_TOOL_RETRIES` | 1 | 只读工具失败后的最大重试次数 |
| `AI_AGENT_TOOL_RETRY_INITIAL_DELAY_MS` | 100 | 第一次工具重试前等待 |
| `AI_AGENT_TOOL_RETRY_MAX_DELAY_MS` | 1000 | 工具退避上限 |

初始延迟不能大于最大延迟，最大延迟必须小于 Run timeout。配置只影响应用组装的 Runtime；测试
可显式使用零延迟，保持确定性。

## 观测与排错

每次实际进入下一尝试时产生 `model.retrying` 或 `tool.retrying`。公开事件/Trace 只含 attempt、
delay 和稳定错误码；工具 retry span 产生 `agent.tool.retry` metric。排错顺序：

1. 先看最终稳定错误码及 `retryable`；
2. 再看是否出现 retry event、attempt 与 delay；
3. 若没有重试，检查次数、deadline、side effect、persistent idempotency key 和 result-unknown；
4. Store 故障优先查持久 winner/recovery，不要手工重放整个 Runtime。

## 验证命令

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_reliability backend.tests.test_settings -q
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_manual_agent_loop backend.tests.test_runtime_comparison backend.tests.test_openai_agents_runtime backend.tests.test_durable_observability -q
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_mcp_tool_adapter -q
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_run_coordinator backend.tests.test_tool_execution_store_contract backend.tests.test_runtime_contract backend.tests.test_langgraph_replanning backend.tests.test_container -q
./.venv/Scripts/python.exe -B -m unittest discover -s backend/tests -q
```

MCP 定向和全量后端在当前 Windows 受控沙箱内需要本地子进程能力；沙箱失败不能改写为代码失败，
应保留首次结果并在经批准的沙箱外环境复跑。本任务的测试全部离线，无需 API Key 或 DSN。

## 保留边界

- Python worker thread、SDK transport 和已经发送的远端请求仍不能被宣称硬取消，见 `KI-017`。
- `max_cost_usd`、逐调用 Provider usage、版本化价格和在线低预算证据仍由 `KI-018` 跟踪。
- 持久 Run/Event 连接结果未知、多进程终态竞争和生产硬进程中断仍由 `KI-015/KI-016` 跟踪。
- 统一分层 CI 属于 M13-T3；Docker/pgvector/Nginx 部署验收属于 M13-T4。
