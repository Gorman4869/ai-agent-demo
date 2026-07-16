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
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_run_store_contract -v
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
| LangChain 实验“通过”但无 import | 只写了文档或包装原 Loop | 用调用链测试证明框架实际参与 |

## 自测

1. 概念题：为什么创建 `Agent` 对象不等于完成真实 Agent 调用？
2. 概念题：为什么 `StoredRunEvent` 不直接复用现有 `AgentEvent`？
3. 实操题：新增 `EchoRuntime`，不修改 Coordinator 即通过契约测试。
4. 排错题：在线开关关闭但代码仍发请求，按层定位根因。
5. 场景题：如果接入第二家模型，哪些 Provider 字段不能泄漏到 API 和 Vue？

## 费曼复述

用“浏览器请求一个后端任务”的语言解释 Manual、Agents SDK 和 LangGraph 如何共享一个 Runtime 契约，以及为什么默认测试必须使用 Mock。

## 官方资源

- OpenAI Agents SDK Agents：<https://openai.github.io/openai-agents-python/agents/>
- OpenAI Agents SDK Running agents：<https://openai.github.io/openai-agents-python/running_agents/>
- OpenAI 工具指南：<https://developers.openai.com/api/docs/guides/tools>
- LangChain 文档：<https://docs.langchain.com/oss/python/langchain/overview>
- LangGraph 文档：<https://docs.langchain.com/oss/python/langgraph/overview>
