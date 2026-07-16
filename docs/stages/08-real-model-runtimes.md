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
| 必学 | 事件先持久化再推送 | SSE、恢复、审计 | 能证明断线不丢事件 | M8-T2、M8-T3 |
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

两条链在 M8-T2 只并存，不双写。`main.py` 把旧类型显式命名为 `LegacyRunRecord`；新类型不具备旧类型的 `event_types/error` 展示字段，不能直接交给旧 `_to_run_response()`。M8-T3 才通过 Coordinator 接入新链，旧测试在迁移完成前继续作为兼容门禁。

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

当前仍不能宣称 `RunStore.transition()` 与 `EventStore.append()` 两次调用具有原子性：进程可能在终态事件和终态状态之间退出。风险记录为 `KI-015`，M8-T3 固定一次提交用例边界，M11 通过 PostgreSQL 同事务关闭。

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
