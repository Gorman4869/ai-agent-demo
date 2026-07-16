# M8：真实模型与统一运行时

> 工程状态只查看 `../continuity/status.md`。本文件是计划与跟练材料，不代表任务已经验证。

## 本阶段目标

在不破坏手写 Loop 和 Mock 回归的前提下，建立异步 Runtime、持久事件扩展缝、真实 OpenAI Agents SDK 执行链路，以及 LangChain/LangGraph 对照。

- 时间预算：2 周，约 16–28 小时。
- 任务：M8-T1 至 M8-T7。
- 在线门：M8-T6 单独授权，不阻塞 M9 离线工作。
- 工作映射：模型网关、Agent 平台 Runtime、提供方适配和用量治理。

## 20% 关键知识

| 类型 | 知识点 | 工作场景 | 学到什么程度 | 验证任务 |
| --- | --- | --- | --- | --- |
| 必学 | Agent 定义与 Runner 执行的区别 | 真实 SDK 接入 | 能解释并实现完整执行 | M8-T4 |
| 必学 | Runtime Protocol 与适配器 | 多模型/多框架 | 新增实现不修改 API | M8-T3 |
| 必学 | 事件先持久化再推送 | SSE、恢复、审计 | 能证明通知前已存储、通知失败可重放；HTTP/SSE 断线 E2E 留给 M12 | M8-T2、M8-T3 |
| 高频 | Tool Schema、结构化输出、usage | 工具型 Agent | 跨 Runtime 统一映射 | M8-T4、M8-T5 |
| 易错 | 把 fake runner 当在线证据 | CI 与验收 | 能区分契约和冒烟 | M8-T6 |
| 暂缓 | 第二家模型提供方 | 多云模型网关 | 知道适配边界 | 场景题 |

## M8-T1 配置门禁速查

| 配置 | 默认值 | 作用与边界 |
| --- | --- | --- |
| `AI_AGENT_RUNTIME` | `manual` | 可选 `manual`、`agents_sdk`、`langgraph` |
| `AI_AGENT_MODEL_PROVIDER` | `mock` | Key 存在也不会自动从 `mock` 切到 `openai` |
| `AI_AGENT_ONLINE_ENABLED` | `false` | 只接受明确的 `true` 或 `false` |
| `AI_AGENT_TRACE_INCLUDE_SENSITIVE` | `false` | 当前课程始终拒绝敏感 Trace，避免 SDK 默认记录输入内容 |
| `OPENAI_API_KEY` | 空 | 使用 `SecretStr`，不得写入源码、日志或验证记录 |
| `OPENAI_MODEL` | 空 | 必须由环境显式指定，仓库不硬编码在线模型 |
| `AI_AGENT_MAX_STEPS` | `8` | 单 Run 工作流步骤上限，服务端范围 1–64 |
| `AI_AGENT_MAX_MODEL_CALLS` | `8` | 单 Run 模型调用上限，服务端范围 1–64 |
| `AI_AGENT_RUN_TIMEOUT_MS` | `30000` | 单 Run 总超时，服务端范围 100–120000 毫秒 |
| `AI_AGENT_MODEL_TIMEOUT_MS` | `20000` | 单次模型调用超时，不得大于 Run 总超时 |
| `AI_AGENT_MAX_INPUT_TOKENS` | `16000` | 单 Run 累计输入预算，服务端范围 1–200000 |
| `AI_AGENT_MAX_OUTPUT_TOKENS` | `2000` | 单 Run 累计输出预算，服务端范围 1–32000 |
| `AI_AGENT_MAX_COST_USD` | `0.25` | 单 Run 累计费用预算，必须为有限正数且不大于 10 |
| `AI_AGENT_MAX_MODEL_RETRIES` | `2` | 只允许模型临时错误使用，服务端范围 0–5 |

`backend/.env.example` 只是模板，应用不会自动加载 `.env`。默认组合根只创建本地内存依赖，不实例化在线 Runner；Runtime 与预算的实际执行接线分别在 M8-T3、M8-T4 完成。

## M8-T2 运行数据基础速查

### 为什么暂时有两个 RunRecord

```text
ApplicationContainer
├─ run_service
│  └─ services.run_service.RunRecord
│     旧同步教学 API：执行后一次返回 completed / failed
└─ run_store + event_store
   └─ domain.run.RunRecord + StoredRunEvent
      M8+ 持久主链：queued、CAS、审批暂停、恢复与续传
```

两条链在 M8-T2 只并存，不双写。`main.py` 把旧类型显式命名为 `LegacyRunRecord`；新类型不具备旧类型的 `event_types/error` 展示字段，不能直接交给旧 `_to_run_response()`。M8-T3 把 Coordinator 接入 Container 的程序化路径，但旧 HTTP/SSE 仍保持 legacy 行为；统一持久 API 与前端迁移属于 M12。

### Run 状态机与 CAS

```text
queued -> running -> waiting_approval -> running
   |          |              |
   |          |              +-> failed | cancelled
   |          +-> completed | failed | cancelled
   +-> cancelled
```

- completed、failed、cancelled 是终态，不能回到任何状态，也不能转换到自身。
- 每次合法转换把 `version` 加 1；Store 要求调用方提交 `expected_version`。
- 完成与取消同时竞争同一版本时只能一个成功，另一个得到 `concurrent_write`，不能覆盖赢家。
- 时间必须是 UTC-aware 且不能倒退。Tool 等待审批后被拒绝可以在没有 `started_at` 时失败，因为工具确实没有执行。

### 幂等创建

作用域固定为：

```text
(owner_id, sha256(Idempotency-Key))
```

请求摘要使用 `run-request-v1` 规范 JSON，覆盖 session、runtime、provider、model、输入与执行选项。

| 情况 | Store 行为 |
| --- | --- |
| 首次 Key | 创建 queued Run，`created=true` |
| 同 owner、同 Key、同请求 | 返回最早的 Run 及其当前状态，`created=false` |
| 同 owner、同 Key、不同请求或 session | `idempotency_conflict`，不泄漏 Key/输入 |
| 不同 owner、相同 Key | 各自创建，互不读取 |
| 相同 Run ID、不同 Key | `run_conflict` |

原始 Key 不进入模型、repr、日志或 Store。不要用 Python `hash()`、对象 `repr()` 或数据库无约束的“先查再插”实现幂等。

### 持久事件与断线续传

| 规则 | 含义 |
| --- | --- |
| event ID | 调用方预生成稳定 ID，重试不能换 ID |
| sequence | Store 按 Run 分配、唯一递增；客户端游标只依赖 sequence |
| 同 ID 同内容 | 返回原事件及原 sequence，不重复追加 |
| 同 ID 改内容 | `event_conflict` |
| owner 隔离 | 不存在与无权访问表现一致，避免枚举 Run |
| payload | 标准 JSON、有限数字、字符串 Key，最多 64,000 字节，并限制深度和节点数 |
| heartbeat | 只属于 SSE 传输，不存储、不占业务 sequence |
| 终态之后 | 新业务事件拒绝；已经落盘的最终事件仍可幂等重放 |

`StoredRunEvent` 不直接复用 `AgentEvent`：后者是 Runtime 的瞬时消息，前者增加持久 ID、Run ID、sequence 与 Store 时间，并在写入和每次返回时复制嵌套 JSON。

### ToolExecution 与 UsageRecord

- `ToolExecution` 只保存参数摘要、结果摘要、有界安全说明和状态时间，不保存原始参数或无界结果。
- 有副作用的工具从创建记录开始就必须有幂等摘要；不能等执行时再补，也不能通过持久化还原绕过。
- `UsageRecord` 表示一次模型调用，不是会被下一次覆盖的 Run 汇总；`sequence=1,2,...` 区分重试或多轮调用。
- 未返回费用时保存 `estimated_cost_usd=None + cost_source=unknown`；已知费用必须使用 `Decimal`，不能把 float 直接持久化为金额。
- 日志使用 `safe_summary()` 或显式字段白名单。`repr=False` 不能阻止 `dataclasses.asdict()` 导出内容，因此禁止把整个领域对象直接转成日志。

### 并发保证与尚未关闭的边界

内存实现只服务单进程、单 event loop 的离线学习与测试：

```text
Run 操作：Run lock
事件追加：Run lock -> Event lock
事件读取：短暂读取 Run，释放后再取 Event lock
```

固定锁序使“检查终态 + 追加事件”线性化，不能在持有 Event lock 时反向调用 RunStore。适配器无关合同测试覆盖 20 路幂等创建、完成/取消 CAS 竞争、同 event ID 并发重放和 50 路事件追加；M11 PostgreSQL 继续继承同一 mixin。

普通 `RunStore.transition()` 与 `EventStore.append()` 两次调用仍不具备原子性，不能用于生命周期。M8-T3 已增加 `commit_start()` 与 `commit_terminal()`，内存适配器在同一 Run→Event 锁对内提交状态和事件；`KI-015` 因而降为 mitigated，但 PostgreSQL 同事务、多进程竞争与重启证据仍由 M11 关闭。

### 本节跟练 Demo

1. 阅读 `backend/tests/test_run_domain.py`，手画合法和非法状态边。
2. 阅读 `backend/tests/test_run_store_contract.py`，找出 adapter-independent mixin 与内存 fixture 的分界。
3. 运行下列命令，观察并发断言不是靠 sleep：

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_run_domain backend.tests.test_run_store_contract -v
```

4. 练习新增一个 `EchoRunStore` 测试 fixture，只实现 Protocol，不修改合同测试；它必须通过 owner、幂等、CAS 与事件测试。
5. 故意把 EventStore 锁去掉，运行 50 路追加测试并解释为什么“本机偶尔通过”不等于并发正确；练习结束后恢复代码。
6. 用自己的话说明为什么同 Key 同请求重放要返回 Run 的当前 running 状态，而不是重新生成 queued Run。

## M8-T3 异步 Runtime 与协调器速查

### 主链结构

```text
RunCoordinator
├─ commit_start：queued -> running + run.started
├─ AgentRuntime.run(request, emit, control)
│  └─ ManualRuntime -> worker thread -> 白名单过程事件
├─ PersistentEventEmitter：EventStore.append -> notifier
└─ commit_terminal：终态 + 答案/安全失败 + 终态事件
```

| 组件 | 只负责什么 | 明确不负责什么 |
| --- | --- | --- |
| Runtime | 模型、工具、工作流和非生命周期过程事件 | 不写 RunStore，不产生 `run.*` 生命周期事件 |
| Coordinator | Runtime 选择、singleflight、执行 deadline、取消和生命周期编排 | 不包含 Provider 响应类型或具体工具业务逻辑 |
| Store | owner、CAS、sequence、重放和生命周期一次提交 | 不等待模型、工具或实时消费者 |
| Notifier | 在事件已持久化后做有界、最佳努力的实时唤醒 | 不是真相源，失败不能回滚事件或改变 Run 结果 |

### ManualRuntime 为什么不能直接转发旧 AgentEvent

旧 Loop 的 `tool.completed/tool.failed` 事件包含工具原始结果和错误文本。新适配器只允许以下白名单：

| 旧事件 | 可持久字段 |
| --- | --- |
| `model.retrying` | `attempt`、`model_duration_ms` |
| `tool.started` | `id`、`name`、`model_duration_ms` |
| `tool.completed` | `id`、`name`、`duration_ms`、`ok` |
| `tool.failed` | 上述字段加稳定 `error_code` |

用户输入、工具参数、工具 `value`、原始 `error_message` 和最终答案副本不能通过过程事件进入 Store。最终答案只进入 `RunRecord.answer`。未知旧事件类型 fail closed，避免旧 Loop 新增字段后绕过脱敏审查。

ManualRuntime 使用 `asyncio.to_thread()` 包装同步 Loop。它在 Loop 完成后才按顺序回放过程事件，因此只是兼容适配器，不是真实时工具审计。取消时先设置共享 token，只等待有限清理宽限；Python 线程不能安全强杀，宽限后仍阻塞的模型或工具可能继续在后台收尾，该限制由 `KI-017` 跟踪。

### 生命周期一次提交与竞争

```text
StartCommit
  expected_version=0
  -> running(version=1) + run.started(sequence=1)

TerminalCommit
  expected_version=1
  -> completed | failed | cancelled
  + 与状态匹配的 run.* 事件
```

- 生命周期 event ID 由 Run、阶段和目标状态稳定派生；重试不能换 ID。
- 同一命令精确重放返回 `created=false`，不增加 sequence，也不重复 notifier。
- start claim 只有 `created=true` 的 Coordinator 可以启动 Runtime；另一执行者等待并读取持久终态，不能重复工具副作用。
- 取消不是“只设一个内存布尔值”：它也提交 cancelled CAS。若完成与取消竞争同一 version，Store 只接受一个赢家。
- 普通 `EventStore.append()` 直接拒绝 `run.started/completed/failed/cancelled`，防止调用者绕过状态与事件一致性。

### 失败矩阵

| 故障点 | 规定结果 |
| --- | --- |
| StartCommit 发布前失败 | Run 保持 queued，`run.started` 不可见，Runtime 不启动 |
| 过程 append 失败 | 不通知该事件、不伪造终态；Run 保持 running 等恢复服务处理 |
| notifier 抛错或超时 | 事件已存；记录安全告警，Run 继续执行 |
| Runtime 未配置或抛异常 | 写入安全分类的 failed，不包含原异常文本 |
| cancel 与 complete 竞争 | version CAS 只有一个终态和一条匹配终态事件 |
| cancel 发生在 token 检查与 append 之间 | 晚到 append 被拒绝，执行方读取 durable cancelled 赢家 |
| TerminalCommit 发布前失败 | Run 与终态事件都不变化，不退化成两次调用 |
| 调用方取消一个 execute waiter | 共享执行任务继续，其他 waiter 可得到结果 |

执行 deadline 从 Coordinator 接受任务时开始，启动通知会消耗预算；Runtime 超时后还允许有限 worker 清理、终态提交和有界通知，所以它不是严格等于配置毫秒数的端到端硬墙钟。真实进度 Store 故障恢复、lease 与重启扫描由 `KI-016` 及 M11–M13 跟踪。

### 本节跟练 Demo

1. 运行 Runtime、Coordinator 与 Store 合同：

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_runtime_contract backend.tests.test_run_coordinator backend.tests.test_run_store_contract -v
```

2. 对比 `test_direct_answer_matches_legacy_loop_and_filters_lifecycle`：最终答案保持一致，但新 Runtime 不把旧 `run.started/run.completed` 当过程事件发出。
3. 仿照 `StaticRuntime` 实现一个 `EchoRuntime`，只返回 `RuntimeResult(completed)`；不得修改 Coordinator。
4. 阅读 `InspectingNotifier`，解释为什么 notifier 被调用时事件已经能从 EventStore 重放。
5. 在内存 Store 的 start/terminal fault seam 注入错误，验证 Run 和 Event 均未半提交。
6. 阅读 cancel-vs-complete、blocked append 和双 Coordinator barrier 测试，画出各自的 CAS 赢家。
7. 运行旧 API 兼容测试，确认字段仍为 `id/session_id/status/answer/event_types/error`，且 durable Store 为空。

## M8-T4 OpenAI Agents SDK Runtime 跟练教程

本节面向已经会写前端组件、请求封装和状态管理，但还没有独立接过真实 Agent SDK 的开发者。训练目标不是“会创建一个 Agent 对象”，而是能把 SDK 的模型流、工具流、usage、取消和错误收敛成应用自己的稳定 Runtime 契约。

### 先确认状态与证据边界

> 本节离线实现证据等级为 `code_complete`。该标签表示代码与离线契约测试已经完成，不替代 `../continuity/status.md` 的任务账本，也不等于真实 Provider 已验证。M8-T6 在线冒烟尚未执行，本节没有读取真实 API Key、没有发起在线模型调用，实际费用为 0。

| 项目 | 当前事实 | 不能据此声称什么 |
| --- | --- | --- |
| 实现状态 | 离线 `code_complete` | 不能写成在线 `verified` |
| 离线证据 | fake Runner、真实 SDK dataclass、Container 门禁和 33 项专项测试；全量后端 231 项通过、1 项既有环境跳过 | fake 响应不能证明 Provider strict schema、真实流或真实 usage 正常 |
| 在线调用 | 未执行 | 不得展示伪造的在线截图、Token 或模型答案 |
| 本节费用 | 0 | `estimated_cost_usd=None` 不是“真实费用为 0”，而是“费用未知” |

### 从前端心智迁移到 Agent Runtime

下面的类比只帮助迁移，不表示两套机制完全相同：

| Agent 后端概念 | 前端近似类比 | 准确定义 |
| --- | --- | --- |
| `Agent` | 组件定义或路由配置 | 声明 instructions、tools、output type；创建对象本身不发送模型请求 |
| `Runner` | 渲染器加事件循环 | 真正驱动“模型 → 工具 → 再次模型 → 终态”的执行循环 |
| `RunResultStreaming` | 一次可取消的流式请求句柄 | 暴露 `stream_events()`、`cancel()`、终态、最终输出和聚合 usage |
| `OpenAIAgentsRuntime` | Provider adapter | 把 SDK 对象转换成应用的 `RuntimeEvent` 与 `RuntimeResult`，并执行脱敏、预算和取消策略 |
| `RunCoordinator` | 业务流程 store/action 层 | 选择 Runtime、管理 deadline、持久化生命周期，并仲裁完成与取消 |
| `PersistentEventEmitter` | “先落 store，再通知 UI” | 先写 EventStore，再做实时通知；未来 M12 才把持久主链统一暴露给前端 |

最重要的心智模型是：

```text
Agent = 这名助手是谁、能做什么、必须返回什么
Runner = 这一次任务怎样真正跑起来
Runtime = 怎样把第三方 Runner 安全接入本系统
Coordinator = 怎样让这次运行具有持久状态、期限和并发语义
```

因此，`create_openai_learning_agent()` 返回成功只证明定义可以构造；只有 `Runner.run_streamed()` 创建执行句柄并消费 `stream_events()`，才进入真实 Agent 执行链路。

### 架构与数据流

```text
调用方 / 未来 Vue Run 页面
          |
          v
RunCoordinator
  |  commit_start、deadline、取消、commit_terminal
  v
OpenAIAgentsRuntime
  ├─ AgentFactory ───────────────> Agent(instructions, tools, output_type)
  ├─ ModelFactory ───────────────> 每 Run AsyncOpenAI + OpenAIResponsesModel
  └─ Runner.run_streamed(...)
       |
       ├─ SDK stream_events() 原迭代器
       |    ├─ structured answer 增量 JSON 解码
       |    ├─ SDK 事件白名单映射
       |    └─ await emit(RuntimeEvent)
       |             |
       |             v
       |        EventStore -> 有界 Notifier -> 未来 SSE / Vue
       |
       ├─ SDK FunctionTool -> sdk_tools bridge -> ToolRegistry.execute()
       |
       └─ final_output + aggregate usage
                    |
                    v
              RuntimeResult
```

一次正常运行按以下顺序发生：

1. Coordinator 把 Run 从 queued 原子提交为 running；Runtime 再用可信请求创建每 Run 工具上下文和 Agent。
2. ModelFactory 只在真正执行时创建显式 client/model；Runtime 传入模型、turn/output/retry 上限并关闭敏感 Trace。
3. Runner 驱动模型和工具循环；Runtime 消费同一个流迭代器，把通过校验、脱敏和白名单的事件逐个 `await emit()`。
4. 流结束后检查完整终态、未闭合工具、aggregate usage 和 typed answer；Runtime 返回结果，Coordinator 提交生命周期终态。

边界要记牢：Runtime 不生成 `run.started/run.completed`，Coordinator 不解析 SDK raw event，SDK/Pydantic 对象不越过 Runtime 边界。

### 为什么结构化输出的 JSON delta 必须解码

学习 Agent 声明了 `OpenAIAgentOutput(answer: str)`。在锁定的 SDK 路径中，`response.output_text.delta` 承载的是结构化输出的 JSON framing，不是可以直接展示的答案。例如 Provider 可能把一个答案切成：

```text
' { "answer" : "line\\'
'nquote:\\" emoji:\\uD83D'
'\\uDE80" } '
```

直接把这些 raw delta 发给前端会产生以下问题：

- Vue 会看到 JSON 外壳；escape 和 Unicode 代理对还可能跨 chunk，逐块 `json.loads()` 必然失败。
- Provider framing 会扩大持久数据面，而且流式正文与 typed final output 不一致时可能被误标为 completed。

当前 Runtime 使用增量状态机，只接受连续的 `{"answer":"..."}` 最小对象：

1. 跨 chunk 识别对象、`answer` 键和字符串边界。
2. 解码 `\n`、`\"`、`\\` 等 JSON escape。
3. 合并 `\uD83D\uDE80` 这类跨 chunk Unicode 代理对。
4. 每个完整 JSON 对象分配递增的安全整数 `segment`；同一对象跨多少 chunk 都保持同一编号，新对象才递增。
5. 只把解码正文和 `segment` 作为 `model.output.delta.data` 发出；流结束时只把最后一个 segment 与 typed `final_output.answer` 精确核对。

多个结构化对象可能来自不同模型轮。前端必须先按 `segment` 分组，只在同一 segment 内追加 delta；发现新 segment 时开启新草稿/答案边界，不能把 `draft + final` 无边界拼成一个字符串。最终 Run answer 对应最后一个 segment。若 JSON 不完整、键不对、存在额外字段或最后一段与终态不一致，Runtime fail closed。

### SDK 事件映射白名单

| SDK 事实 | Runtime 处理 | Runtime 事件与允许字段 | 边界说明 |
| --- | --- | --- | --- |
| `raw_response_event / response.output_text.delta` | 校验字符串与字节上限；结构化模式先增量解码 | `model.output.delta`：`delta`；结构化模式增加安全整数 `segment` | 同一 JSON 对象跨 chunk 编号不变；不保存 response ID、logprobs 或 raw framing |
| 其他已知 raw response 内层事件 | 显式忽略 | 无 | 创建、完成等 Provider 细节不进入应用事件 |
| 第一次 `agent_updated_stream_event` | 视为 SDK 初始 Agent 通知并忽略 | 无 | 不把 SDK Agent 对象持久化 |
| 第二次 Agent update | 视为 handoff | 失败码 `agents_sdk_handoff_not_supported` | handoff 与恢复留到后续工作流阶段 |
| `run_item_stream_event / tool_called` | 校验 call ID 与工具名，登记未完成调用 | `tool.started`：`id`、`name` | 不保存工具 arguments |
| `run_item_stream_event / tool_output` 成功 | 与已登记 call ID 配对，只读安全 `custom_data` | `tool.completed`：`id`、`name`、`ok` | 不保存原始 output |
| `run_item_stream_event / tool_output` 失败 | 同上，并规范稳定错误码 | `tool.failed`：`id`、`name`、`ok`、`error_code` | 不保存异常文本或错误详情 |
| `message_output_created`、`reasoning_item_created` | 显式忽略 | 无 | 不复制消息对象或 reasoning payload |
| 未知顶层 wrapper 或未知 workflow item | fail closed 并取消、drain | `agents_sdk_contract_error` 或 `agents_sdk_workflow_event_not_supported` | SDK 升级不会静默扩大持久字段 |
| 流完成后的 aggregate usage | 校验非负整数、非零请求/Token 和总数相等 | `model.usage`：scope、provider、model、requests、Token、unknown cost | 它是 Run 汇总，不是单次 `UsageRecord` |

前端开发者可以把这张表理解成“Provider DTO → 领域 action”的转换表：新增 SDK 事件时必须显式评审，不能像透传任意接口 JSON 那样自动展开字段。

### 工具安全边界

M8-T4 的目标是证明工具桥接，而不是提前实现审批恢复。当前只允许低风险、无需审批且无副作用的工具进入 SDK Agent。

| 边界 | 当前做法 | 防止的问题 |
| --- | --- | --- |
| 身份与角色 | 每 Run 创建 `OpenAIAgentsRunContext`；工具定义先按可信 `ToolExecutionContext` 过滤 | 模型伪造 principal/roles，或并发 Run 串身份 |
| 审批与风险 | `approval_required` 为 true 的定义全部省略；它覆盖显式审批、高风险和有副作用工具 | 在 M10 持久审批/恢复完成前执行不可逆操作 |
| 定义快照 | 深拷贝定义和 Schema，重新校验名称、描述、结构、深度、节点数与字节数 | 注册后修改 Schema 的 TOCTOU 绕过 |
| 严格参数 | 根 Schema 强制 `additionalProperties=false`；参数必须是有界 JSON object | 模型注入额外字段、超大参数或非法 JSON |
| 调用绑定 | SDK context 必须是当前 Run 的同一对象；工具名和 call ID 必须匹配并有界 | 跨 Run context 替换、伪造调用和重复配对 |
| 真实执行 | 最终仍调用隔离后的 `ToolRegistry.execute()` | SDK 不绕过角色、Schema 和应用工具契约 |
| 返回模型 | 工具结果先规范成有界 JSON；循环、非有限数字、过深/过多节点和超限输出变为 `tool_output_invalid` | 内存/序列化放大和不受控 Provider 输入 |
| 持久事件 | 只从 safe custom data 提取 `ok/error_code` | 工具参数、结果和异常文本泄漏到 EventStore |

同步工具 handler 通过 `asyncio.to_thread()` 运行。取消后 Runtime 可以停止采用结果，但 Python 不能硬杀已经阻塞的线程；线程仍可能占用默认 executor。由于本阶段拒绝副作用工具，数据一致性风险已降低，但资源占用风险仍由 `KI-017` 跟踪，不能描述成“工具已被强制终止”。

### Usage 与预算真实性表

预算说明必须区分“调用前设置”“SDK 执行上限”“本地过程保护”和“完成后核对”。当前实现不是完整的请求级成本治理。

| 配置或数据 | 当前生效点 | 可以保证什么 | 不能保证什么 |
| --- | --- | --- | --- |
| `max_steps` + `max_model_calls` | 调 Runner 前设置 `max_turns=min(...)` | SDK turn 不超过较紧的执行上限；MaxTurns 映射到对应稳定失败码 | SDK retry 也会产生请求，真实 requests 仍可能先超过 `max_model_calls` |
| `max_output_tokens` | 每次模型请求的 `ModelSettings.max_tokens`；流中另有限制单块/累计 UTF-8 字节；结束后核对 aggregate output | 单次响应有 Provider 参数，本地不会无限持久化正文 | 不是整个多轮 Run 的精确 Token 硬门禁；字节数也不等于 Token 数 |
| `max_model_retries` | SDK `ModelRetrySettings` | SDK retry 层有界；底层 `AsyncOpenAI(max_retries=0)` 避免双重隐藏重试 | 不保证实际 requests 小于 turn 数；Runtime 不自动重跑整个工具型 Run |
| `model_timeout_ms` | 每 Run client 的 HTTP 连接、写入、读取/流阶段 | 单个 client I/O 不会使用无限 timeout | 不是完整模型执行或整个 Run 的硬墙钟，也不能撤销 Provider 已开始的工作 |
| `run_timeout_ms` | Coordinator 接受任务时建立 deadline | Runtime 主执行受统一期限控制 | 有界清理、终态提交和通知会占用额外时间，不能宣称端到端精确等于配置毫秒数 |
| `usage.requests` | Run 完成后从 SDK aggregate usage 读取并核对 | 能发现已发生的模型请求数超过配置 | 属于事后检测，不能在超额请求发出前阻止它 |
| `usage.input_tokens` | Run 完成后核对 | 能把已报告的输入超额标记为 `input_token_budget_exceeded` | 当前 SDK 路径不能在每次请求前可靠硬关闭累计输入 Token |
| `usage.output_tokens` | Run 完成后核对 | 能把聚合输出超额标记为 `output_token_budget_exceeded` | 不能代替 Provider 每请求限制或精确流式 Tokenizer |
| `max_cost_usd` | 当前只在 Settings 中有界解析 | 配置形状安全，为后续成本治理保留契约 | M8-T4 没有可信定价与持久 ledger，不能执行费用硬门禁 |
| `estimated_cost_usd` | `model.usage` 固定为 `None`，`cost_source=unknown` | 如实表达“费用未知” | 不能填 0、不能伪造成真实账单，也不能构造单次调用 `UsageRecord` |

判断口诀：turn、单次输出参数和 retry 是执行前的有界设置；aggregate requests/input/output 是完成后的核对；费用当前未执行。任何文档或 UI 把后三者写成“超额前一定中止”都是错误的。

### 取消、失败与 drain 时序

取消的目标是停止新事件并释放流资源，不是撤销已经发生的外部世界。

```text
t0  consumer 正在同一个 iterator 上等待 anext() 或 await emit()
t1  CancellationToken、外层 task 或处理失败触发中止
t2  suppress_events=true，禁止任何后续 RuntimeEvent
t3  stream.cancel("immediate")，同一条流只调用一次
t4  继续消费原 stream_events() iterator，使 SDK run loop 进入清理终态
t5  第一个 grace 超时后 cancel consumer，再等待第二个有限 grace
t6  关闭该 Run 的显式 client/model context
t7  token 取消返回 cancelled；外层 task 取消重新抛 CancelledError
```

必须 drain 原迭代器，因为重新调用 `stream_events()` 可能创建另一条迭代路径，不能证明原生成器、队列和 SDK run loop 已经收尾。drain 期间即使收到晚到 delta，也因 `suppress_events` 不再落库。

还有两条优先级规则：

- 结构/预算/事件处理失败也先 immediate cancel，再在同一迭代器上 drain，最后返回安全失败。
- Event sink/Store 失败不能被包装成 Provider 错误；若它与 token 或外层 task 取消同时发生，Store 失败优先传播给 Coordinator，遵守 `KI-016`。

`cancel("immediate")` 不承诺撤销已经发出的 Provider 请求，也不能终止已经进入 worker thread 的同步工具。它只定义本进程后续如何停止采用结果和有界清理。

### 稳定错误映射

公开失败只保留稳定 code、category、retryable 和安全消息，不使用 `str(exception)`，也不携带请求、Key 或 Provider body。

| 来源 | 稳定 code | category | retryable |
| --- | --- | --- | --- |
| `MaxTurnsExceeded` | 较紧上限对应 `max_steps_exceeded` 或 `model_call_budget_exceeded` | `budget` | false |
| `ModelBehaviorError` | `provider_invalid_response` | `provider` | false |
| `ModelRefusalError` | `model_refused` | `provider` | false |
| `ToolTimeoutError` | `tool_timeout` | `tool` | false |
| Python/Provider timeout | `provider_timeout` | `timeout` | true |
| 输入、输出或工具 guardrail tripwire | `guardrail_blocked` | `security` | false |
| SDK `UserError` | `agents_sdk_configuration_error` | `runtime` | false |
| Provider rate limit | `provider_rate_limited` | `provider` | true |
| Provider authentication/permission | `provider_auth_failed` | `provider` | false |
| Provider bad request/not found/unprocessable | `provider_request_rejected` | `provider` | false |
| Provider 5xx 或连接失败 | `provider_unavailable` | `provider` | true |
| 其他 SDK/未知执行异常 | `agents_sdk_execution_failed` | `runtime` | false |

Runtime 自身契约错误另行处理：usage 缺失/无效使用 `agents_sdk_usage_missing/invalid`；未完成流使用 `agents_sdk_contract_error`；SDK interruption 使用 `agents_sdk_interruption_not_supported`；未知 workflow 与 handoff 分别使用稳定不支持码。Store/sink 异常不进入上表，因为它们必须原样越过 Runtime，由 Coordinator 决定持久恢复语义。

### 分步跟练（全部离线）

#### 步骤 0：确认环境与零成本边界

目标：确认练习使用项目现有环境，不安装依赖、不触发在线门。

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -c "import importlib.metadata as m; print(m.version('openai-agents'))"
```

完成标准：分别看到 `Python 3.12.10` 和 `0.18.2`。不要读取或打印本机 API Key，也不要运行 `scripts/verify-online.ps1`；本节产出必须注明 online 未执行、费用为 0。

#### 步骤 1：证明 Agent 定义不等于 Runner 执行

1. 阅读 `create_openai_learning_agent()`、`OpenAIAgentsRuntime.run()` 和 Container 的 `_create_agents_sdk_runtime()`。
2. 找出 Agent 的 instructions/tools/output type，以及真正调用 `Runner.run_streamed()` 的位置。
3. 运行最小主链测试：

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_streams_reviewed_text_and_maps_structured_output_and_usage -v
```

产物：画出 AgentFactory、ModelFactory、Runner、stream、RuntimeEvent、RuntimeResult 六个节点。完成标准：能解释为什么 Container 构造不联网，以及为什么模型 client 必须在每 Run context 中关闭。

#### 步骤 2：手算并验证结构化 delta

先不用代码，手算下面三块最终应发给前端什么：

```text
' { "answer" : "line\\' | 'nemoji:\\uD83D' | '\\uDE80" } '
```

再运行跨 chunk escape 与终态一致性测试：

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_decodes_structured_answer_escapes_across_chunks backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_decodes_escaped_key_and_tracks_the_latest_structured_turn backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_structured_stream_must_match_the_typed_final_answer -v
```

产物：写出“raw chunk → segment → 解码正文 → final answer 核对”表。完成标准：单对象所有 chunk 使用 segment 1；`draft` 与 `final` 分别使用 1、2，最终答案只核对 `final`；事件不含 JSON framing，不一致终态必须 failed。

#### 步骤 3：验证事件白名单与 fail closed

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_maps_tool_items_without_arguments_outputs_or_errors backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_unknown_raw_events_are_ignored_but_unknown_wrappers_fail_closed backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_handoff_and_extended_workflow_events_fail_closed -v
```

产物：从测试的 `emitted` 断言反推一张允许字段表。完成标准：能指出哪些 raw 事件被忽略、哪些未知 wrapper 必须失败，并证明工具 arguments、output 和异常文本不在序列化事件中。

#### 步骤 4：验证每 Run 工具隔离

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime.OpenAIAgentsToolAdapterTest.test_run_contexts_filter_roles_and_omit_approval_tools backend.tests.test_openai_agents_runtime.OpenAIAgentsToolAdapterTest.test_bridge_revalidates_schema_and_bounds_calls_and_outputs -v
```

练习：把一个工具分别设为高风险、`has_side_effects=true`、`requires_approval=true`，预测 `build_sdk_tools()` 的结果；再用已有测试核对。完成标准：三种定义都不会暴露给 SDK；低风险工具仍经过角色、Schema、call ID、参数和输出边界。

#### 步骤 5：区分执行上限与事后 usage

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_usage_budget_excess_is_reported_after_safe_usage_event backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_zero_request_or_zero_token_usage_is_invalid backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_max_turns_uses_and_reports_the_tighter_execution_budget backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_stream_and_post_stream_errors_use_safe_stable_mapping -v
```

产物：不看上文，重新填写“配置、生效时机、是否硬门禁、超限 code”四列。完成标准：能解释 `max_turns=min(...)` 为什么仍不能精确硬限制 aggregate requests，以及为什么未知费用必须是 `None/unknown`。

#### 步骤 6：画出取消与 drain 的确定性时序

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_processing_failures_cancel_and_drain_the_same_stream backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_token_cancellation_cancels_once_drains_and_suppresses_late_events backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_outer_task_cancellation_cancels_stream_and_is_re_raised backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_abort_grace_force_closes_a_stalled_consumer backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_sink_failure_wins_an_outer_task_cancellation_race -v
```

产物：画出 cancel、suppress、drain、grace、client close 和结果传播的先后关系。完成标准：cancel mode 只出现一次 `immediate`，流被 drain，晚到事件不 emit，Store 失败与取消竞态时 Store 失败胜出。

#### 步骤 7：验证 Runtime 没有侵入 Coordinator 和旧 API

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeCoordinatorTest.test_coordinator_persists_sdk_progress_and_owns_lifecycle backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeCoordinatorTest.test_coordinator_stores_only_safe_sdk_failure backend.tests.test_container backend.tests.test_framework_runtimes -v
```

产物：列出 Coordinator 拥有的生命周期事件与 Runtime 拥有的过程事件。完成标准：SDK 过程事件先持久化，最终生命周期仍由 Coordinator 提交；默认 `manual + mock` 路径和旧 API 不发网络、不双写。

#### 步骤 8：提交离线验收证据

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime -q
```

当前基线应得到 33 项通过。记录命令、退出码、测试数，并明确写下：证据类型为 offline contract、实现为 `code_complete`、online smoke 未运行、真实 Provider 未验证、在线费用为 0。

测试数量未来可能随回归增加；验收看退出码和全部通过，不要为了保持“30”而删除新增测试。

### M8-T4 验收清单

- [ ] 能在白板上讲清 Agent、Runner、Runtime、Coordinator 的职责，不把 Agent 构造当模型调用。
- [ ] 能从 raw JSON chunks 手工还原 `answer`，按 `segment` 分隔多轮，并解释为什么不能逐 chunk `json.loads()` 或跨 segment 拼接。
- [ ] 能为每个 RuntimeEvent 写出允许字段，并证明 raw Provider、工具参数/结果和异常文本没有越界。
- [ ] 能说明高风险、需审批和有副作用工具为何在 M10 前全部省略。
- [ ] 能区分 turn 上限、每请求参数、流中字节保护、aggregate 事后核对和未执行的费用门禁。
- [ ] 能画出 immediate cancel + 原迭代器 drain + 有界清理时序。
- [ ] 能说明 Store/sink 失败为什么不能映射成 Provider 失败或普通取消。
- [ ] 能运行专项离线测试并得到全部通过，同时保持在线调用为 0、费用为 0。
- [ ] 能列出仍待 M8-T6 验证的 Provider strict schema、真实 streaming、真实 usage 和费用证据。

满足全部条目只能把 M8-T4 离线实现写为 `code_complete`；完成用户单次授权的真实模型、真实工具与真实 usage 冒烟后，才有资格讨论在线 `verified`。

### 本节故障排查

| 现象 | 最可能原因 | 排查顺序 |
| --- | --- | --- |
| 创建 Agent 成功但没有事件 | 只构造 Agent，没有调用/消费 Runner | 查 `Runner.run_streamed()` 调用，再查是否迭代 `stream_events()` |
| UI 出现 `{"answer":...}` 或 `draftfinal` | raw delta 被透传，或不同结构化轮被无边界拼接 | 查增量解码和 `segment`；只在相同 segment 内 append，最终答案取最后一段 |
| emoji 变成乱码或解析失败 | Unicode surrogate pair 被 chunk 拆开后逐块解析 | 运行跨 chunk escape 测试，检查高低代理对状态是否跨 chunk 保留 |
| usage 是 0 仍 completed | fake usage 或 Provider contract 被当合法值 | 查 requests/total_tokens 非零校验和 input+output=total 断言 |
| `max_model_calls=1` 却观察到多个 requests | 把 SDK turn 近似上限误当请求硬门禁，或 retry 已发生 | 查 `max_turns`、`max_model_retries` 和完成后的 aggregate usage；不要改写为“预算失效”或“硬门禁已保证” |
| 工具没有出现在 Agent | 角色不可见，或工具需要审批/高风险/有副作用 | 先查 `ToolExecutionContext.roles`，再查 `approval_required`，最后查 Schema 快照校验 |
| 工具事件含结果或错误文本 | 绕过 safe custom data，或直接持久化 SDK item | 查 `custom_data_extractor` 和事件白名单；EventStore 不得接收原始 item |
| 取消后仍出现新 delta | 没有先设置 suppress，或 drain 期间仍 emit | 查 `suppress_events` 设置是否早于 immediate cancel，运行 late-event 测试 |
| 取消后测试挂起 | 迭代器没有 drain，或 stalled consumer 没有有限 grace | 确认继续消费的是原 iterator，并检查两段有界 cleanup |
| Store unavailable 被显示成 Provider 错误/取消 | sink 异常被 Runtime 捕获后错误归类 | 运行两类 sink/cancel race 测试，确认 Store 异常原样传播 |
| 默认测试发出网络请求 | Container 门禁、Runtime 注入或模型 factory 提前执行 | 先确认默认 `manual + mock + online=false`，再检查 client 是否只在每 Run context 创建 |

### M8-T4 自测

1. 概念题：`Agent`、`Runner`、Runtime adapter 和 Coordinator 各自只负责什么？
2. 数据题：为什么结构化 delta 不能直接显示，且 UI 为什么必须按 `segment` 而不是整个 Run 无边界拼接？
3. 实操题：给定一个把 `\uD83D` 与 `\uDE80` 分在两块的流，写出应发出的正文和终态校验条件。
4. 安全题：模型在工具 JSON 参数里传入 `principal_id=admin`，为什么不能改变真实权限？
5. 场景题：一个低风险工具改为 `has_side_effects=true` 后，本阶段应怎样处理，为什么？
6. 预算题：`max_turns=min(max_steps,max_model_calls)` 为什么不等于 requests 的绝对硬上限？
7. Usage 题：为什么 Run aggregate usage 不能伪造成一条带 duration/cost 的 `UsageRecord`？
8. 取消题：为什么要在原 `stream_events()` 迭代器上 drain，而不是重新调用该方法？
9. 竞态题：Store append 失败与外层 task 取消同时发生时，哪一个应对 Coordinator 可见？
10. 证据题：33 项 fake/SDK-shape 测试全部通过后，为什么状态仍不能写在线 `verified`？

### 费曼复述

假设你要向一名前端同事解释“点击发送后为什么不能直接把 OpenAI chunk 塞进 Pinia”。请不用 SDK 术语堆砌，按下面顺序讲 3 分钟：

1. Agent 像一份什么定义，Runner 又像什么执行者？
2. Provider 为什么会发 JSON 外壳，后端怎样只留下答案正文？
3. 工具为什么必须先过角色、风险、Schema 和输出边界？
4. 取消为什么是“停止采用 + cancel + drain”，而不是“撤销一切”？
5. usage 中哪些是事后事实，哪些配置只是执行前上限，费用为什么仍未知？
6. 为什么离线 `code_complete` 不能冒充在线 `verified`？

复述合格标准：听者能画出一条“SDK event → RuntimeEvent → EventStore → 未来 SSE/Vue”的数据线，能指出至少两个不能透传的敏感字段，并能准确说出一个当前仍未关闭的预算或取消边界。

## 跟练顺序

### 第 1 次：配置与领域契约

- 前置：C0-T4 verified。
- 动作：完成 M8-T1、M8-T2；画出 Run、Event、Runtime 和 Store 的依赖图。
- 产物：Settings、领域模型、内存 Store 契约测试。
- 通关：默认环境零网络；事件序号唯一；终态不可回退。

### 第 2 次：异步 Runtime 与兼容

- 动作：完成 M8-T3；用 ManualRuntime 包装现有 Loop。
- 产物：RunCoordinator、持久 emitter、兼容测试。
- 通关：旧 API 与原测试继续通过；EventStore 失败时不向消费者伪报事件。

### 第 3 次：真实 SDK 与框架对照

- 动作：完成 M8-T4、M8-T5。
- 产物：OpenAI Runtime、LangChain 实验、统一契约与取舍报告。
- 通关：离线 fixture 覆盖文本、工具、usage、限流、超时和取消；LangChain 确实进入调用链。

### 第 4 次：显式在线验证与复盘

- 动作：仅在用户单次授权后完成 M8-T6；随后完成 M8-T7。
- 产物：在线验证记录、速查表、自测和费曼复述。
- 通关：真实工具调用和 usage 有证据；日志无密钥；费用记录完整。

## 计划验证命令

下列命令只有写入 verification log 后才算已验证：

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_settings backend.tests.test_container -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_run_domain backend.tests.test_run_store_contract backend.tests.test_container -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_runtime_contract backend.tests.test_run_coordinator -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_langchain_comparison -v
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

在线计划命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify-online.ps1 -Suite M8
```

## 常见错误与排查

| 现象 | 可能原因 | 排查顺序 |
| --- | --- | --- |
| 默认测试访问网络 | Settings 默认值或 fixture 泄漏 | 检查在线开关，再检查 Runtime 注入 |
| SSE 有事件但 Store 为空 | emitter 顺序错误 | 检查 append 是否在 notify 前完成 |
| usage 为 0 或空 | Provider 事件映射不完整 | 保存最小脱敏 fixture，对照 SDK 结果对象 |
| 工具被执行两次 | 重试与幂等边界错误 | 检查 tool call ID、幂等键和 retryable |
| Run 已终态仍出现新事件 | Store 终态检查与追加未线性化 | 检查 Run→Event 锁序；数据库检查同事务锁 |
| completed 事件存在但 Run 仍 running | 两次 Store 调用间崩溃 | 检查 KI-015；不要把独立调用描述成事务 |
| LangChain 实验“通过”但无 import | 只写了文档或包装原 Loop | 用调用链测试证明框架实际参与 |

## 自测

1. 概念题：为什么创建 `Agent` 对象不等于完成真实 Agent 调用？
2. 概念题：为什么 `StoredRunEvent` 不直接复用现有 `AgentEvent`？
3. 实操题：新增 `EchoRuntime`，不修改 Coordinator 即通过契约测试。
4. 排错题：在线开关关闭但代码仍发请求，按层定位根因。
5. 场景题：如果接入第二家模型，哪些 Provider 字段不能泄漏到 API 和 Vue？
6. 并发题：为什么 `expected_status` 不如 `expected_version` 足以防止所有丢失更新？
7. 事务题：Event append 的终态检查已加锁，为什么仍不能说终态事件和 Run 状态原子提交？

## 费曼复述

用“浏览器请求一个后端任务”的语言解释 Manual、Agents SDK 和 LangGraph 如何共享一个 Runtime 契约，以及为什么默认测试必须使用 Mock。

## 官方资源

- OpenAI Agents SDK Agents：<https://openai.github.io/openai-agents-python/agents/>
- OpenAI Agents SDK Running agents：<https://openai.github.io/openai-agents-python/running_agents/>
- OpenAI 工具指南：<https://developers.openai.com/api/docs/guides/tools>
- LangChain 文档：<https://docs.langchain.com/oss/python/langchain/overview>
- LangGraph 文档：<https://docs.langchain.com/oss/python/langgraph/overview>
