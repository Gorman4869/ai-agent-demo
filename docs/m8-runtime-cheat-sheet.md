# M8 Runtime 一页速查表

## 一句话定义

模型和框架负责提出或执行 Agent 动作；应用 Runtime 把第三方行为收敛成稳定事件与结果；Coordinator 和 Store 让这次运行可持久、可取消、可恢复和可审计。

## 五层职责

| 层 | 负责 | 不负责 |
| --- | --- | --- |
| Agent | instructions、tools、output type 定义 | 构造对象不执行模型或工具 |
| Runner | 驱动模型、工具循环和终态 | 不拥有应用 Run 生命周期 |
| Runtime | Provider/框架适配、过程事件、稳定失败 | 不写 RunStore，不产生 `run.*` |
| Coordinator | Runtime 选择、deadline、取消、生命周期提交 | 不解析 SDK raw payload |
| Store/Notifier | owner、CAS、sequence、重放；存后通知 | Notifier 不是真相源 |

## 默认门与在线门

```text
默认：manual + mock + online=false -> 无 Key、无网络、零费用

在线：agents_sdk + openai + online=true
    + OPENAI_API_KEY + OPENAI_MODEL
    + 低预算 + 用户当次授权 + 当前费率
```

Key 或 model 单独存在不能启用网络。应用不自动加载 `.env`；Key 不进入命令行、日志、文档或 Git。

## Run 与事件主链

```text
queued
  -> commit_start
running + run.started(sequence=1)
  -> RuntimeEvent -> EventStore.append -> Notifier
  -> commit_terminal
completed | failed | cancelled + 匹配的 run.* 终态事件
```

- 幂等作用域：`owner_id + Idempotency-Key digest`。
- 并发写：使用 `expected_version` CAS，不只比较 status。
- 恢复游标：使用每 Run 唯一递增 `sequence`。
- 生命周期：只能由 start/terminal commit 提交，普通 append 拒绝 `run.*`。

## 四种实现怎么选

| 实现 | 最适合 | 当前边界 |
| --- | --- | --- |
| 手写 Loop/Manual | 学原理、完全显式控制、稳定离线基线 | 非真流式；线程不能硬杀 |
| Agents SDK | 真实模型、工具 loop、结构化输出与 usage | 在线 E4 单独授权；Provider 字段需适配 |
| LangChain lab | 学生态抽象、快速对照 ToolNode | 不进入主 Run |
| LangGraph Runtime | 显式状态图与后续持久工作流 | M8 无 checkpoint/interrupt/resume |

## 事件白名单

| 事件 | 允许字段 |
| --- | --- |
| `model.output.delta` | `delta`、结构化模式的 `segment` |
| `tool.started` | `id`、`name` |
| `tool.completed` | `id`、`name`、`ok` |
| `tool.failed` | 上述字段加稳定 `error_code` |
| `model.usage` | scope、provider、model、requests、Token、cost 状态 |

禁止持久化 Provider raw response、response ID、Key、prompt、工具参数/结果、异常正文和 SDK/Pydantic 对象。

## 结构化流

```text
raw JSON chunks
  -> 跨 chunk 增量解码
  -> 只发 answer 正文 + segment
  -> 最后一段与 typed final answer 精确核对
```

同一 segment 内追加；新 segment 开新草稿。不能逐 chunk `json.loads()`，不能把多个 segment 无边界拼接。

## 预算事实

| 项目 | 事实 |
| --- | --- |
| `max_turns` | SDK 执行上限，不等于真实 request 硬上限 |
| `max_output_tokens` | 每请求参数加事后 aggregate 核对，不是多轮精确硬门 |
| retry | SDK 模型 retry 有界；整个工具型 Run 不自动重跑 |
| model timeout | HTTP 阶段 timeout，不等于整个 Run 精确墙钟 |
| Run timeout | Coordinator 期限；清理、终态提交和通知可能额外耗时 |
| usage | Provider 返回后的 Run 聚合事实，可能只能事后发现超额 |
| cost | 未知必须 `None/unknown`；operator-supplied estimate 不是账单 |

## 稳定错误速查

| 场景 | code | retryable |
| --- | --- | --- |
| 限流 | `provider_rate_limited` | true |
| 鉴权/权限 | `provider_auth_failed` | false |
| Provider 5xx/连接失败 | `provider_unavailable` | true |
| Provider timeout | `provider_timeout` | true |
| 请求被拒绝 | `provider_request_rejected` | false |
| 模型拒绝 | `model_refused` | false |
| guardrail | `guardrail_blocked` | false |
| turn/调用预算 | `max_steps_exceeded` / `model_call_budget_exceeded` | false |

Store/sink 错误不映射成 Provider 错误；原始异常文本不进入公开失败。

## 取消顺序

```text
suppress new events
  -> cancel("immediate") once
  -> drain 原 stream iterator
  -> bounded grace
  -> close per-Run client
  -> 返回取消或传播更高优先级 Store 失败
```

取消不等于撤销已发送请求或强杀 worker thread，更不保证已开始的副作用没有发生。

## 最小命令

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_runtime_contract backend.tests.test_run_coordinator -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_runtime_comparison backend.tests.test_langchain_agent_lab backend.tests.test_framework_runtimes -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_online_smoke -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

在线脚本默认不运行。缺少当次授权时，不带 `-Authorized` 的拒绝只证明 fail-closed，不是 Provider 失败或 E4。

## 排错顺序

1. 查 Settings 完整门和默认 `manual + mock + online=false`。
2. 查 Run 是否 durable start、owner/version 是否匹配。
3. 查 Runtime 稳定 code/category/retryable。
4. 查 EventStore 白名单事件与 sequence，Notifier 只作提示。
5. 查模型 retry、整个 Run retry、工具副作用和幂等边界。
6. 最后才调 Prompt、换模型或扩大预算。

## 五问自检

1. 哪一层拥有 `run.completed`，为什么？
2. Fake Runner 全绿最高能证明到哪一级？
3. 为什么 `max_model_calls=2` 仍可能看到更多 aggregate requests？
4. Provider timeout 后，怎样判断工具能否重试？
5. 从 Mock 切在线必须同时满足哪些门？
