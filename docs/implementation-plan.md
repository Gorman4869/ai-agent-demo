# AI Agent 学习项目实施计划

> 计划版本：2.0
>
> 已确认设计：`docs/superpowers/specs/2026-07-16-ai-agent-transition-completion-design.md`
> 当前动态状态：`docs/continuity/status.md`

## 计划契约与实际状态

本文件只保存稳定任务 ID、依赖、产物和验收门槛，不保存“当前正在做什么”。任务发布后不得重编号；取消或替换时标记 `superseded`。

M0–M7 的现有代码和文档继续保留，但 2026-07-16 审计已确认其中存在真实模型、MCP Client、LangChain、LangGraph 恢复、真实 pgvector、真 SSE 和生产验证等缺口。旧的“全部完成”声明已失效，实际状态、验证和问题分别以以下文件为准：

- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`

新增 C0 与 M8–M14 衔接原 M0–M7，不重写原项目。

## 实施原则

- 每个里程碑都必须可独立运行、测试和讲解。
- 先实现原理，再接入框架；先使用 Mock，再接入真实模型。
- 不提前创建尚未教学的复杂模块，不一次安装全部依赖。
- 每一阶段同时交付代码、跟练文档、练习、自测和验收证据。
- 所有真实密钥仅从环境变量读取，仓库只保存 `.env.example`。

## 里程碑总览

| 里程碑 | 周期 | 大纲主题 | 核心交付 | 验证方式 |
| --- | --- | --- | --- | --- |
| M0 学习工作区 | 第 0 周 | 全局 | 学习计划、主题映射、进度表、速查与考核模板 | 文档链接和任务闭环完整 |
| M1 最小 Agent | 第 1–2 周 | 01–06 | Python/Node 基础实验、手写 Agent Loop、Mock 模型、Function Calling | 无 API Key 运行测试 |
| M2 Agent 工程骨架 | 第 3–4 周 | 07–13 | FastAPI、模型适配器、工具注册表、MCP、Skill、上下文、LangChain/LangGraph 对照 | 契约与集成测试 |
| M3 知识与工作流 | 第 5–7 周 | 14–18、21 | Workflow、多 Agent、RAG、记忆、任务推理、向量存储 | 固定知识集评测 |
| M4 Agent UI | 第 8 周 | 04、19、20、22 | Vue 3 UI、REST、SSE、工具过程与引用展示 | 前后端联调与断线测试 |
| M5 生产准备 | 第 9–10 周 | 23–26 | 日志、Tracing、成本、自动化测试、权限、安全、Docker | 回归、越权与部署验证 |
| M6 高级扩展 | 第 11 周 | 27–29 | 多模态、代码、浏览器 Agent 受控实验 | 至少完成一个扩展 |
| M7 系统设计与答辩 | 第 12 周 | 30 | 架构说明、故障演练、迁移任务、演示脚本 | 最终验收清单 |
| C0 连续性基线 | 补齐第 0 周 | 全局 | Git、设计规格、稳定计划、状态、ADR、验证与交接 | 文档一致性和全量离线基线 |
| M8 真实模型与运行时 | 补齐第 1–2 周 | 05、09、10 | 异步 Runtime、持久事件、OpenAI Runner、LangChain 对照 | 离线契约 + 显式在线冒烟 |
| M9 MCP Client 与 Skill | 补齐第 3 周 | 07、08 | MCP Client 发现/调用、Skill Catalog 与触发评测 | STDIO 协议端到端测试 |
| M10 LangGraph 持久工作流 | 补齐第 4–5 周 | 11、14、15、18 | checkpoint、interrupt、审批恢复、重规划、多 Agent 对照 | 中断和同进程换实例恢复测试；真重启留 M11 |
| M11 上下文、记忆与真实 RAG | 补齐第 6–8 周 | 12、16、17、21 | PostgreSQL、pgvector、Embedding、上下文预算、持久记忆 | 数据库集成与固定评测集 |
| M12 统一 Run 与实时 UI | 补齐第 9–10 周 | 04、19、20、22 | 持久 Run API、真 SSE、断线续传、Vue 恢复 | 前端单测与浏览器 E2E |
| M13 生产工程闭环 | 补齐第 11–12 周 | 23–27 | Trace、成本、错误、CI、Docker、安全与故障演练 | CI、容器健康、压测和安全回归 |
| M14 高级 Agent 作品集 | 补齐第 13–14 周 | 28–30 | 真实浏览器、真实视觉、评测报告与最终答辩 | 作品集演示和 30 项终审 |

## M0：建立学习工作区

### 任务 0.1：项目入口与学习导航

新增文件：

```text
ai-agent-demo/README.md
ai-agent-demo/docs/learning-plan.md
ai-agent-demo/docs/syllabus-map.md
ai-agent-demo/docs/progress.md
```

内容要求：

- README 给出学习顺序、环境检查、Mock 路径和目录导航。
- learning-plan 按五级路线展开 12 周、每周 8–10 小时任务。
- syllabus-map 将图片中的 30 个编号映射到课程、代码和验收项。
- progress 提供可勾选任务、开始/完成时间、问题和复盘记录。

验收：学习者能从 README 定位第一课、运行入口、练习和验收标准。

### 任务 0.2：考核与复盘材料

新增文件：

```text
ai-agent-demo/docs/assessments.md
ai-agent-demo/docs/cheat-sheet.md
ai-agent-demo/docs/feynman-template.md
```

验收：题库同时包含概念题、实操题、场景题；速查表覆盖 Agent 最小闭环和排错顺序。

## M1：实现无框架最小 Agent

### 任务 1.1：Python 与 Node.js 基础实验

新增：

```text
labs/python-basics/
labs/node-basics/
```

实验范围：异步、类型、JSON、HTTP、环境变量、异常、模块和测试。Node.js 只覆盖后续 MCP Server 所需能力。

验收：不依赖第三方库运行基础脚本和标准库测试。

### 任务 1.2：手写 Agent Loop

新增：

```text
backend/app/domain/
backend/app/models/mock_model.py
backend/app/tools/
backend/app/agent/manual_loop.py
backend/tests/
```

实现顺序：

1. 定义 Message、ToolCall、ToolResult、AgentEvent 等领域类型。
2. 定义模型协议和确定性 MockModel。
3. 实现工具 Schema、注册表和两个无副作用工具。
4. 实现带最大步数、停止条件和错误事件的 Agent Loop。
5. 用标准测试验证直接回答、单工具、未知工具、参数错误和超步数。

验收：无网络、无 API Key 完成完整工具闭环；能打印清晰事件序列。

## M2：形成 Agent 工程骨架

### 任务 2.1：FastAPI 服务边界

新增：

```text
backend/pyproject.toml
backend/app/main.py
backend/app/api/
backend/app/services/
backend/.env.example
```

接口初版：健康检查、创建会话、提交消息、查询运行状态。初期状态存内存，数据访问通过接口隔离。

验证命令在创建依赖清单后确定，不在未核对环境时承诺具体包管理器。

### 任务 2.2：框架对照实验

新增：

```text
labs/langchain-agent/
labs/langgraph-agent/
backend/app/agent/sdk_runtime.py
backend/app/agent/graph_runtime.py
```

使用同一组工具和测试样例对比手写循环、SDK 和 LangGraph；文档记录抽象、持久化、恢复和调试差异。

### 任务 2.3：MCP 与 Skill

新增：

```text
mcp-servers/knowledge-server/
labs/mcp/
skills/research-summary/
```

TypeScript MCP Server 暴露只读知识工具；Python 客户端完成发现和调用。Skill 包含说明、输入边界、执行步骤与示例，不将 Skill 等同于任意代码执行。

## M3：加入知识、记忆与多 Agent

### 任务 3.1：可替换 RAG 管线

模块：文档加载、切分、Embedding、索引、检索、重排、引用构造。先实现内存与 Mock Embedding，再增加 pgvector 适配器。

测试：切分边界、稳定检索、空结果、引用可追溯、恶意文档指令隔离。

### 任务 3.2：会话和长期记忆

短期消息、运行状态和长期事实使用不同模型；长期记忆写入需要明确策略，可删除、可审计，不默认保存所有对话。

### 任务 3.3：Workflow 与多 Agent

依次实现顺序、条件、并行、路由、汇总和人工审批。研究员、检索员、审核员只作为学习角色，优先验证“是否真的需要多 Agent”。

## M4：构建 Vue Agent UI

在进入本里程碑前检查当前 Node、包管理器和 Vue 脚手架版本，再生成前端，不预先假设构建命令。

页面能力：

- 会话列表和消息输入。
- 流式消息增量。
- 运行步骤与工具状态。
- 引用来源。
- 中断、失败、重连和完成状态。
- Token、耗时与成本摘要。

前端依赖统一 `AgentEvent` 协议；EventSource/Fetch 流选择依据鉴权和 POST 流需求确定。

## M5：工程化、安全与部署

### 可观测性

统一 run ID、结构化日志、节点耗时、工具耗时、Token 与错误分类；敏感输入默认不进入日志。

### 测试与评测

固定样例覆盖答案依据、工具选择、引用、权限拒绝、恢复和成本；真实模型测试与默认 Mock 测试分离。

### 安全

加入输入限制、工具 RBAC、审批、工作目录限制、超时、取消、有限重试和 Prompt Injection 测试。

### 部署

提供开发环境与 Docker 路径、健康检查和配置检查。只有在 PostgreSQL/Redis 确实进入课程后才加入对应服务。

## M6：高级扩展

三个实验共用安全 Harness：

- 多模态 Agent：图片输入、结构化观察和失败回退。
- 代码 Agent：只允许在隔离工作目录内读取、修改和运行白名单命令。
- 浏览器 Agent：限定站点、动作、登录状态和人工确认点。

必做要求：选择一个完成端到端扩展；其余两个完成最小实验和安全分析。

## M7：系统设计与最终验收

交付架构图、组件边界、事件协议、容量估算、成本模型、降级、重试、幂等、数据安全与故障恢复说明。

最终现场任务：启动 Mock 模式、新增工具、索引新资料、排查预置故障、展示越权拒绝、运行评测并迁移到相似业务场景。

## 每个任务的完成定义

一个任务只有同时满足以下条件才完成：

1. 代码或文档产物存在且无未解释占位符。
2. 正常路径和至少一个失败路径可以复现。
3. 对应测试或人工验收步骤通过。
4. 跟练文档说明工作场景、常见错误和排查顺序。
5. 学习者能用自己的话解释设计边界。
6. 产物被进度表和大纲映射表引用。

## 首轮实施批次（历史记录）

第一批只完成 M0 与 M1，避免在基础接口尚未稳定时同时生成前端、数据库和部署代码：

1. 创建学习导航、12 周计划、大纲映射、进度表、题库、速查表和费曼模板。
2. 创建 Python/Node.js 前置检查与基础实验。
3. 定义 Agent 领域类型、Mock 模型、工具注册表和手写循环。
4. 编写标准库单元测试和第一阶段跟练文档。
5. 运行环境检查与测试，记录尚未验证的后续命令。

该批次属于原始 M0–M7 计划，后续实施入口已切换为 C0 与 M8–M14，不再从本节重新开始。

## C0–M14 通用规则

### 课程交付节奏

- 通用执行方式遵循 [`docs/continuity/course-delivery-playbook.md`](continuity/course-delivery-playbook.md)：默认采用“课程优先、里程碑验收”，按风险选择任务等级、时间盒、测试深度和复审强度。
- 当前任务的明确产物、验收契约和 ADR 高于 playbook 的通用建议，但不能绕过依赖安装、在线付费、远程 Git、破坏性操作和范围扩张的授权门。
- 普通原子任务交付最小真实纵切、关键测试、精确验证记录和简短 handoff；完整阶段教程、题库、速查表、费曼复述和 30 项映射在对应里程碑跟练与验收任务中统一汇总，避免每个子任务重复编写整章材料。
- 定向测试是每个原子任务的默认验收；全量后端、前端、MCP、Compose 和连续性验证在里程碑验收、依赖或公共契约变化、发布前门禁以及任务明确要求时执行。

### 任务依赖

- 一个任务只有在所有前置任务至少达到 `verified` 后才能开始，在线验收明确例外时可保留 `code_complete`。
- 新依赖必须先在任务产物中列出用途、版本、锁定方式和无依赖替代方案，并取得用户许可后才安装。
- 在线模型、远程系统、付费 API、远程 Git 和破坏性迁移需要单独授权。

### 通用完成定义

任一任务进入 `verified` 前必须同时满足：

1. 产物与已确认设计和项目编码规约一致。
2. 正常路径、失败路径和安全边界有自动化测试或可复现人工验收。
3. 相关既有回归仍通过。
4. 本任务的简短交接或所属里程碑文档包含目标、前置、命令、文件、工作场景、错误和排查；普通原子任务不重复扩写整章教程。
5. verification log 记录 commit、命令、退出码、通过数、跳过、警告和未验证范围。
6. known issue 已关闭、缓解或明确保留。
7. status 和最新 handoff 指向下一条精确动作。
8. 学习者能在所属里程碑验收时完成概念题、实操题、场景题和费曼复述；原子任务先提供完成该闭环所需的真实产物和证据。

## C0：连续性与真实基线

### C0-T1：确认补齐设计规格

- 依赖：无。
- 产物：`docs/superpowers/specs/2026-07-16-ai-agent-transition-completion-design.md`。
- 验收：总体架构、数据流、错误安全、测试和连续性四部分均获用户确认；规格无占位符或矛盾。
- 当前证据：用户已确认，设计落盘。

### C0-T2：建立本地 Git 基线

- 依赖：C0-T1。
- 产物：本地 `main`、`.gitignore`、ADR-0004、基线 commit。
- 验收：依赖、虚拟环境、构建产物、真实 `.env` 和本地数据库被忽略；源码、锁文件、`.env.example` 正常追踪；无 remote；工作区干净。
- 当前证据：基线 `9a54ebe`，设计状态修订 `acb12c0`。

### C0-T3：建立稳定计划和连续性文档

- 依赖：C0-T1、C0-T2。
- 产物：`AGENTS.md`、计划 2.0、status、verification log、known issues、ADR 和首份 handoff。
- 验收：所有动态状态只在 status；任务 ID 不重复；README、progress、syllabus map 均指向恢复入口；文档链接可解析。
- 学习验收：学习者能在没有聊天记录时按恢复顺序找到当前任务和下一动作。

### C0-T4：重跑离线基线并修正文档漂移

- 依赖：C0-T3。
- 产物：首条完整 verification record、修正后的 M1 命令和阶段导航。
- 必跑命令：

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests -v
.\.venv\Scripts\python.exe -m pip check
npm.cmd run build --prefix frontend
npm.cmd run build --prefix mcp-servers/knowledge-server
docker compose -f deploy/compose.yaml config --quiet
```

- 验收：成功、失败、跳过、警告和 Docker 未验证范围全部落盘；C0 状态达到 `verified`。
- 关闭目标：KI-012；Docker Engine 问题继续由 KI-009 跟踪。

## M8：真实模型与统一运行时

### M8-T1：Settings、在线开关与依赖决策

- 依赖：C0-T4。
- 产物：`backend/app/settings.py`、`backend/app/container.py`、配置测试、更新后的 `.env.example`、依赖变更清单和 ADR-0005。
- 约束：默认 `ManualRuntime + MockModel + 内存 Store`；模型名必须来自环境配置，实施时核对当前官方文档。
- 测试：缺失密钥、空模型、非法预算、在线开关关闭时均 fail closed；日志不包含密钥。
- 依赖决策：不新增依赖，不直接使用 MCP 传递安装的 `pydantic-settings` 或 `python-dotenv`；应用只解析显式进程环境。
- 验收命令：

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_settings backend.tests.test_container backend.tests.test_api backend.tests.test_identity -v
```

- 验收：默认环境不触发网络；本任务未新增或安装依赖，后续新增依赖仍按通用规则单独取得许可。

### M8-T2：Run、StoredRunEvent 与 Store 协议

- 依赖：M8-T1。
- 产物：独立 `RunRecord`、`StoredRunEvent`、`ToolExecution`、`UsageRecord`，以及 `RunStore`、`EventStore` 内存实现。
- 测试：事件序号单调、Run 所有权隔离、幂等创建、终态不可回退、并发追加无重复序号、CAS 竞争、事件重放、审批拒绝和有界 JSON。
- 兼容：旧 `InMemoryRunService`、旧 RunRecord、HTTP API 和 SSE 不双写新 Store；`ApplicationContainer` 只增加成对 Store 扩展缝。
- 复用：`test_run_store_contract.py` 是适配器无关 mixin；M11 PostgreSQL 实现必须继承同一合同测试，不复制断言。
- 验收命令：

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_run_domain backend.tests.test_run_store_contract -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_container backend.tests.test_run_service backend.tests.test_api backend.tests.test_observability backend.tests.test_manual_agent_loop -v
```

- 工作映射：建立数据库替换缝和断线续传的数据基础；Run 终态与终态事件的原子提交继续由 M8-T3 的用例边界和 M11 的数据库事务关闭，不把两次独立调用称为事务。

### M8-T3：异步 AgentRuntime 与 RunCoordinator

- 依赖：M8-T2。
- 产物：`RuntimeRequest`、`RuntimeControl`、`RuntimeEvent`、`RuntimeResult`、`AgentRuntime` Protocol、`ManualRuntime`、`RunCoordinator`、运行控制和持久 emitter。
- 生命周期所有权：Runtime 只产生非 `run.*` 过程事件；Coordinator 通过 `StartCommit` 一次提交 `queued -> running + run.started`，通过 `TerminalCommit` 一次提交终态、答案或安全失败以及对应终态事件。普通 `append()` 不得绕过这两个入口。
- 兼容：保留现有同步 `ManualAgentLoop`、`execute_agent()`、旧 HTTP/SSE 和旧响应；M8-T3 只把新 Coordinator 接入 Container 的程序化路径，不双写旧 API，统一 API 属于 M12。
- 执行语义：同一 Coordinator 的并发调用共享一个任务；多个 Coordinator 以持久 start claim 仲裁，只有 `created=true` 的执行者启动 Runtime；取消与完成通过 version CAS 竞争。
- 测试：结果映射和事件脱敏、顺序 await、start/terminal 故障原子性、精确及并发重放、通知前已存储、通知失败/超时、取消与完成竞争、阻塞 append 窗口、共享 waiter、多 Coordinator、执行 deadline、同步 worker 有界取消宽限、Runtime/Store 失败和旧 API 不双写。
- 当前结果边界：`RuntimeResult` 只接受 completed、failed、cancelled；waiting approval、interrupt 和 resume 属于 M10。模型调用数、单次模型超时、Token、usage 与费用预算继续由 M8-T4 及后续任务消费。
- 验收：同步手写 Loop 不被改写成 SDK；新协调器不包含 Provider 或具体工具业务逻辑；内存锁内不等待模型、工具或 notifier。
- 残余边界：PostgreSQL 同事务、多进程 lease、重启恢复和进度 Store 故障恢复属于 M11–M13；ManualRuntime 是同步兼容适配器，不是真流式也不能硬终止 Python worker thread。

### M8-T4：OpenAI Agents SDK Runtime

- 依赖：M8-T3。
- 产物：`OpenAIAgentsRuntime`、可注入 Runner/stream 边界、共享 `ToolRegistry` 包装、最小结构化输出、Run 级 usage 事件和提供方错误映射；不修改 Coordinator 或旧 HTTP/SSE。
- 组合与密钥：Container 只在完整 `agents_sdk + openai + online=true + Key + model` 配置下注册 SDK Runtime；每次 Run 使用显式 client/model，不调用进程全局 Key setter，不依赖 SDK 默认模型，构造 Container 不发网络请求。
- Trace：每次 Runner 调用显式设置 `tracing_disabled=true`、`trace_include_sensitive_data=false`；不能依赖 SDK 默认值或只依赖应用 Settings。
- 工具：每个 Run 建立隔离的 SDK context，把已按身份过滤的 `ToolDefinition` 转为 `FunctionTool`；执行仍经过 `ToolRegistry` 的角色和参数 Schema 校验。M8-T4 只暴露低风险、无需审批且无副作用的工具；审批、恢复和副作用幂等尚未进入 M10 前，其他工具一律 fail closed。持久事件不包含原始参数、结果或异常文本。
- 事件：只映射审核过的文本 delta、工具开始/完成/失败和 Run 级 usage；Provider raw response、SDK 对象、响应 ID 和 trace payload 不越过 Runtime 边界。结构化输出的 SDK raw delta 是 JSON framing，Runtime 必须增量解码并且只发出 `answer` 内容与安全 `segment`；同一对象跨 chunk 编号不变，多对象递增，最终答案只核对最后 segment。文本 delta 必须限制单块与累计字节，且不得进入普通日志或 repr。
- Usage：`result.context_wrapper.usage` 映射为明确标记 `scope=run` 的聚合事件，费用未知保持 `null + unknown`；它不能冒充一次调用的 `UsageRecord`。每请求 duration/cost、持久 ledger 与可信定价留 M13。
- 预算：`max_turns=min(max_steps, max_model_calls)` 约束 SDK turns，`max_output_tokens` 进入每次模型请求的 ModelSettings；client 使用显式 HTTP timeout 且关闭自身重试，唯一重试层由 SDK `ModelRetrySettings` 消费 `max_model_retries`。SDK 重试仍可能使实际 requests 超过 turn 近似上限；`max_model_calls`、输入/输出 Token 只在聚合 usage 可用后再次核对，`max_cost_usd` 尚无可信定价可执行。以上不是请求级硬预算或整个 Run 的硬墙钟，统一执行 deadline 仍由 Coordinator 提供。
- 取消与失败：调用 SDK stream 的 immediate cancel，并在有界清理期间停止新 emit；不宣称撤销已开始的 Provider 请求或工具副作用。SDK/Provider 异常只映射稳定 code、category、retryable 和安全 public message，Store/sink 异常继续向 Coordinator 传播。
- 离线测试：使用 0.18.2 兼容的 fake runner/event fixture 验证文本顺序与 await、结构化终态、工具执行和脱敏、并发 Run 上下文隔离、usage/预算、限流/认证/timeout/MaxTurns/guardrail、部分流失败、取消 drain、Trace 参数、零网络和旧 API 不双写。
- 在线测试：只有显式授权后运行一次低预算冒烟，不把密钥和原始敏感输入写入记录。
- 验收：在线未执行时最高状态为 `code_complete`；离线契约与在线冒烟均有证据后才能 `verified`。

#### M8-T4 离线实现结果与恢复边界

- 已实现：公开 Runner Protocol 注入、每 Run 显式 client/model、Trace 双重关闭、结构化 `answer` 增量解码、事件白名单、Run 级 aggregate usage、稳定错误映射、immediate cancel + 同一迭代器有界 drain，以及 Container 完整配置门。
- 已实现：每 Run 工具定义快照与 Schema 重校验、可信 principal/roles 注入、call ID 和输出大小限制；M10 前拒绝所有需审批、高风险或有副作用的工具。
- 已实现：Coordinator 在执行前校验 `execution_context.principal_id == Run.owner_id`，不一致时 Runtime 与 Store 均不被触发。
- 离线证据：fake Runner 覆盖流式文本/工具/usage/错误/取消/竞态；真实锁定 SDK 类型与签名由专项测试和只读审查核对。该证据不等于 Provider 在线兼容性。
- 已知边界：同步只读工具通过 worker thread 执行，Python 不能硬杀阻塞线程；Provider schema、真实 streaming、真实 usage 和费用只允许在 M8-T6 获得单次授权后验证。

### M8-T5：三运行时契约与 LangChain 对照实验

- 依赖：M8-T3、M8-T4。
- 产物：Manual、Agents SDK、现有 LangGraph 统一输入/工具/事件/结果契约；`labs/langchain-agent/` 最小对照；框架取舍报告。
- 测试：同一计算工具和同一错误用例在三运行时产生语义一致结果；对照实验不进入主 Run。
- 验收：能够解释手写 Loop、SDK、LangChain 和 LangGraph 的抽象收益、成本和使用边界。
- 关闭目标：KI-001、KI-003 的代码部分。

#### M8-T5 离线实现结果与恢复边界

- 已实现：`LangGraphRuntime` 通过实际 `StateGraph.ainvoke()` 接入共享 `AgentRuntime`，并在 `langgraph + mock` Container 配置下可选择；M10 前不包含 checkpoint、interrupt 或 resume。
- 已实现：共享 fixture 用同一输入、`add_numbers` 工具、成功结果和缺参错误比较 Manual、Agents SDK 与 LangGraph；Agents SDK 路径实际执行 `FunctionTool` 桥，事件只保留稳定字段。
- 已实现：`labs/langchain-agent/` 通过 LangChain `create_agent().invoke()` 实际进入 ToolNode，保留离线确定性模型边界和四框架取舍报告，不接入主 Run。
- 离线证据：三 Runtime 共享契约达到 E3，LangChain 实验达到 E2；验证见 `V-20260716-008`。
- 未验证：真实 Provider、费用与在线 usage 仍由 M8-T6 接管；LangGraph 持久恢复由 M10 接管，旧 HTTP/SSE 不变。

### M8-T6：显式在线付费冒烟

- 依赖：M8-T4、M8-T5。
- 产物：独立 `scripts/verify-online.ps1` 与在线验证记录；不得进入默认离线验证。
- 前置：在线开关、API Key、显式模型名和用户单次执行授权全部存在，缺一项必须拒绝运行。
- 验收：完成一次真实流式 Run 和真实工具调用；usage 大于 0；记录模型、耗时、Token、估算费用和退出码；日志无密钥。
- 依赖边界：本任务未授权时不阻塞 M9/M10 的离线结构任务，但 M8 不能标记 `accepted`。

### M8-T7：M8 跟练与验收

- 依赖：M8-T1 至 M8-T5；在线状态引用 M8-T6。
- 产物：`docs/stages/08-real-model-runtimes.md`、速查表、自测、费曼任务和验证记录。
- 验收：学习者能从 Mock 切换到显式在线模式、定位一次提供方失败，并解释为什么默认测试不调用真实模型。

## M9：MCP Client 与 Skill Runtime

### M9-T1：MCP Client 配置与生命周期

- 依赖：M8-T3。
- 产物：`integrations/mcp` Client、允许的 Server 配置、FastAPI lifespan 连接与关闭。
- 测试：进程不存在、启动超时、协议错误、正常关闭和取消均可诊断。
- 安全：Server 命令和工作目录来自服务端允许配置，客户端请求不能注入启动命令。

### M9-T2：工具发现与共同 ToolDefinition 映射

- 依赖：M9-T1。
- 产物：`list_tools`、Schema 规范化、权限过滤、名称冲突策略和远程调用适配器。
- 测试：非法 Schema、重复工具、未授权工具、超时和不可信结果稳定拒绝或隔离。
- 验收：MCP 工具能被 Manual/SDK/LangGraph 的共同工具边界使用。

### M9-T3：TypeScript Server 协议端到端

- 依赖：M9-T2。
- 产物：测试进程真实启动现有 TypeScript STDIO Server，完成初始化、发现、调用和关闭。
- 验收命令：

```powershell
npm.cmd run build --prefix mcp-servers/knowledge-server
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_mcp_client_e2e -v
```

- 关闭目标：KI-002。

### M9-T4：只读 Skill Catalog 与 Resolver

- 依赖：M8-T3。
- 产物：固定根目录扫描、元数据解析、触发匹配、引用加载、缓存和错误模型。
- 安全：拒绝路径逃逸、符号链接越界、超限文件和任意代码执行。
- 测试：现有 `research-summary` Skill 可加载；错误 frontmatter、缺失引用和恶意路径被拒绝。

### M9-T5：Skill 进入上下文并完成效果评测

- 依赖：M9-T4。
- 产物：Skill 上下文片段、触发/不触发固定样例、效果和成本对照。
- 验收：Skill 只影响受控上下文，不绕过权限、审批或工具 Schema。

### M9-T6：M9 跟练与验收

- 依赖：M9-T1 至 M9-T5。
- 产物：`docs/stages/09-mcp-client-skills.md`、MCP/Function Calling/Skill 对照速查和考核。
- 验收：学习者能独立启动 Server、用 Client 发现并调用工具，并解释 roots 不是 OS 安全边界。

## M10：LangGraph 持久工作流与任务推理

### M10-T1：可持久 StateGraph 与 Checkpointer

- 依赖：M8-T3、M9-T2。
- 产物：稳定 graph state、thread ID、共享内存 checkpointer、状态版本和迁移边界。
- 测试：相同 thread 跨 invocation 恢复、不同用户隔离、无 thread ID fail closed、节点失败保留 checkpoint。
- 验收：当前简单图继续可运行，持久 Runtime 使用独立实现；M10 不把共享内存 checkpointer 描述成进程重启持久化，真正 PostgreSQL 恢复由 M11 验收。

### M10-T2：Interrupt、服务端审批与 Resume

- 依赖：M10-T1。
- 产物：审批请求、`interrupt()`、服务端绑定审批、`Command(resume=...)` 和拒绝分支。
- 测试：批准、拒绝、过期、重复使用、参数被篡改、同进程新 Runtime 实例恢复；真正进程重启由 M11 验收。
- 验收：客户端裸 `approved=true` 不能恢复工具执行。

#### M10-T2 离线实现结果与恢复边界

- 已实现：`RuntimeApprovalPause`/`RuntimeApprovalResume`、真实 LangGraph `interrupt()`/`Command(resume=...)`、Run 绑定 ApprovalRequest，以及 `PauseCommit`/`ResumeCommit` 原子生命周期事件。
- 已实现：审批绑定 Run、principal、call、tool 和参数摘要；原始参数只在服务端内存 Store 中保存，批准后仍由共享 `ToolRegistry` 单次消费。拒绝、过期、篡改、布尔 decision 和重复 resume 均不重复执行 handler。
- 离线证据：专项测试实际暂停 graph，再由新 Runtime/Coordinator 实例复用同一 saver/store 恢复；这属于同进程 E3，不是操作系统进程重启或 PostgreSQL 证据。
- 未实现：默认 Container/HTTP 审批端点属于 M12；结果未知的副作用故障注入属于 M10-T5；持久私有参数、进程重启和多进程事务属于 M11。

### M10-T3：动态计划、失败诊断与重规划

- 依赖：M10-T1。
- 产物：结构化计划、步骤预算、失败分类、受限重规划和停止条件。
- 测试：可重试故障、不重试故障、预算耗尽、取消和循环检测。
- 验收：固定三步计划被替换为可解释、可恢复的任务状态，但确定性任务仍优先 Workflow。

#### M10-T3 离线实现结果与恢复边界

- 已实现：显式导入的 `ReplanningLangGraphRuntime`，真实执行 `plan -> execute -> diagnose -> replan` StateGraph；结构化 operation、完成步骤、revision、执行/重规划预算、失败分类和计划签名进入版本化 checkpoint。
- 已实现：`retryable=true`、服务端错误码白名单和安全 category 三重门；权限、校验、审批、存储、取消和副作用失败不重规划。相同操作路径换 step ID 仍触发循环检测，已完成副作用不能进入新计划。
- 离线证据：动态改路通过实际 `RunCoordinator`、EventStore 和终态 Run；共享 `InMemorySaver` 可恢复被取消的只读 pending step，终态不重放，结果未知副作用 fail closed。这属于同进程 E3。
- 未实现：默认 Container/HTTP 迁移、真实模型规划质量、多 Agent、持久 ToolExecution 结果仲裁、进程重启和 PostgreSQL 恢复；分别由 M10-T4/M10-T5、M11 与 M12 承接。

### M10-T4：真实多 Agent 对照

- 依赖：M10-T3、M8-T4。
- 产物：manager-as-tools 与 handoff 中至少一种真实实现；独立角色指令/工具；单 Agent 对照组。
- 评测：质量、延迟、Token、失败率和复杂度对比；没有收益时保留单 Agent 结论。
- 关闭目标：KI-013。

#### M10-T4 离线实现结果与恢复边界

- 已实现：显式导入的 OpenAI Agents SDK manager-as-tools；manager 只持有 researcher、writer、reviewer 三个 `Agent.as_tool()`，角色使用独立指令和隔离工具集，并由公开 `Runner.run()` 实际执行嵌套调用。
- 已实现：研究与审查工具继续由共享 `ToolRegistry`、可信 Run context 和 `build_sdk_tools()` 快照提供；writer 无业务工具，manager 无直接业务工具；高风险、审批和副作用工具保持 fail closed。
- 对照结论：3 个固定课程案例中，多 Agent 与同工具单 Agent 的质量均为 1.0、失败率均为 0；多 Agent 每例 9 次 fixture model request/108 fixture Token、复杂度 12，单 Agent 为 3 次/36 Token、复杂度 3，本地延迟也更高，因此保留单 Agent。
- 证据边界：这是实际 SDK 公开编排路径加确定性离线 Model/usage 的 E2，以及共享工具安全边界的本地 E3；不是 Provider Token、账单、线上质量或生产延迟证据。默认 Container、现有 SDK Runtime handoff 拒绝语义和 HTTP/SSE 均未迁移。

### M10-T5：恢复与故障注入测试

- 依赖：M10-T2、M10-T3。
- 产物：中断、新 Runtime 实例复用同一 checkpointer、工具超时、审批等待和 checkpoint 损坏测试。
- 验收：副作用不重复；无法安全恢复时产生明确终态和诊断事件；进程重启能力明确列为 M11 前置缺口。

#### M10-T5 离线实现结果与恢复边界

- 已实现：10 项独立故障矩阵覆盖 checkpoint 读取不可用/状态损坏、只读 pending step 中断后换 Runtime 恢复、只读工具 timeout 改路、审批等待换 Runtime 恢复/取消/丢 checkpoint，以及重规划和审批两条结果未知副作用路径。
- 已实现：审批 handler 已完成但 checkpoint 写失败时，单次 approval 已被消费；后续 Runtime 返回 `side_effect_resume_unsafe`、发出 `approval.stopped`，且不再次调用 handler。重规划 pending 副作用继续返回同一稳定终态并发出 `plan.stopped`。
- 离线证据：实际 `StateGraph`、`InMemorySaver` 故障 saver、`RunCoordinator`、EventStore 和 `ToolRegistry` 均执行；专项 10 项、受影响定向 123 项和 M1 隔离 7 项通过。这是同进程 E3，不是操作系统进程重启、跨进程或 exactly-once 证据。
- 未实现：PostgreSQL checkpointer/Store、持久 ToolExecution 结果、lease、恢复扫描、私有参数重启恢复和默认 Container 迁移；这些分别由 M11/M12 承接。

### M10-T6：M10 跟练与验收

- 依赖：M10-T1 至 M10-T5。
- 产物：`docs/stages/10-durable-langgraph.md`、状态图、排错、考核和费曼任务。
- 验收：学习者能演示暂停、审批、同进程新 Runtime 实例复用共享 saver 恢复、失败重规划，并解释单 Agent 与多 Agent 取舍；PostgreSQL 真正进程重启明确留给 M11。
- 关闭目标：KI-013；完成 KI-004 的 M10 同进程故障恢复部分和 KI-005 的重规划部分。KI-004 在 M11 真重启验收前保持 `mitigated`。

#### M10-T6 课程与里程碑验收结果

- 课程产物：Stage 10 已汇总三张状态图、四次跟练、固定排错顺序、概念/实操/场景题与评分红线；`docs/m10-langgraph-cheat-sheet.md` 提供一页工作速查，30 项大纲映射同步到 `docs/syllabus-map.md`。
- 聚焦证据：checkpoint、审批 resume、重规划、恢复故障、多 Agent 和对照评测共 58 项通过；固定 3 例两种策略质量均为 1.0、失败率均为 0，多 Agent request、fixture Token、延迟和复杂度更高，继续保留单 Agent。
- 里程碑门：统一离线验证的后端 354 项通过、1 项因 Windows 符号链接能力跳过；受控代码 Agent、Python 依赖、Vue 生产构建、MCP TypeScript 构建和 Compose 配置均通过。
- 证据边界：M10 达到工程 `verified`，但最高仍是确定性离线 E3；没有在线 Provider、真实 Token/账单、PostgreSQL、跨进程 checkpoint、持久 ToolExecution、lease 或恢复扫描证据。`KI-004` 保持 `mitigated`，由 M11-T1 继续承接。

## M11：上下文、持久记忆与真实 RAG

### M11-T1：PostgreSQL 迁移与持久 Store

- 依赖：M8-T2、M10-T1。
- 产物：版本化 SQL migration、Postgres Run/Event/Approval/Memory Store、PostgreSQL LangGraph checkpointer、连接生命周期和事务边界。
- 风格：沿用 dataclass、Protocol 和显式 SQL，不引入 ORM。
- 测试：迁移首次执行、重复执行、回滚失败、所有权隔离、并发事件序号、幂等创建、状态事务和进程重启后 checkpoint 恢复。
- 验收：内存与 PostgreSQL Store 运行同一契约测试；数据库不可用时错误可诊断，不静默回退内存。

#### M11-T1 首个真实纵切边界

- 已实现工作区纵切：固定 `psycopg[binary,pool]` 与官方 `langgraph-checkpoint-postgres`，新增带校验和和 advisory transaction lock 的应用 migration，并由共享异步连接池提供 PostgreSQL Run/Event Store 与 `AsyncPostgresSaver`。
- 已实现工作区证据：PostgreSQL Run/Event 继承 M8 的适配器无关合同；每 Run 计数器分配事件序号，start/pause/resume/terminal 的状态与事件在一个数据库事务内提交。migration 首次/重复、校验和漂移、失败回滚和 event INSERT 故障回滚均走真实数据库。
- 已实现工作区恢复：两个 PID 不同的 Python 进程使用相同可信 thread，从 PostgreSQL 读取 checkpoint 并把 invocation count 从 0 推进到 1、再推进到 2；数据库不可用返回稳定 `store_unavailable`，不回退内存。
- 首个纵切结束时尚未完成 PostgreSQL Approval/Memory Store、持久私有审批参数、ToolExecution 仲裁、lease/recovery scanning、默认 Container 迁移和完整 M11-T1 验收；其中 Approval/Memory 由下面的第二纵切承接。当时 M11-T1 只能保持为 `in_progress`，不能关闭 `KI-004`、`KI-014`、`KI-015` 或 `KI-016`。

#### M11-T1 第二个真实纵切边界

- 新增同步 `ApprovalStore`/`MemoryStore` Protocol，保留现有 ToolRegistry、记忆 API 和默认内存 Container；PostgreSQL persistence 用同一 DSN 统一管理原异步 pool 与 Approval/Memory 共享同步 pool，两类 pool 之间不宣称共同事务。
- `0002_approval_memory_store.sql` 分离私有审批 request 与精确 grant；resolve 与 grant 同事务，consume 使用 row lock。消息按 session 计数器分配顺序并在追加事务中裁剪，长期事实保持显式批准和 owner 隔离。
- 内存与 PostgreSQL 运行同一 Approval/Memory 合同；两个 PID 不同的进程实际恢复私有参数、决议后单次消费、消息和长期事实，probe 不输出这些内容。
- 第二纵切结束时尚未完成默认 async 主链接线及同步数据库调用的线程/取消边界、持久 ToolExecution 结果仲裁、lease/recovery scanning 和跨 pool 一致性；ToolExecution 由下面的第三纵切承接。当时 M11-T1 继续保持 `in_progress`，不提前进入 M11-T2。

#### M11-T1 第三个真实纵切边界

- 新增 async `ToolExecutionStore` 共同合同、内存参考实现、`0003_tool_execution_store.sql` 和 PostgreSQL 适配器；owner 由所属 Run 绑定，只有 running Run 能创建新 pending 执行。
- 幂等摘要按 `(run_id, tool_name, digest)` 仲裁；副作用必须有 key，同键同参数返回既有权威状态，同键改参数冲突。claim 与 terminal settlement 均使用 version CAS，并发只有一个赢家。
- 真实 PostgreSQL 跨进程 probe 覆盖 terminal commit 后进程异常退出但恢复读到 completed，以及遗留 running 显式转为 terminal unknown；触发器故障证明 settlement 失败回滚且不保存结果。
- 尚未完成：默认 Container/Runtime 接线、同步 Approval/Memory 的 async 线程与取消边界、ToolExecution 与 Run/Event/checkpoint/外部副作用的共同事务、lease/heartbeat/recovery scanning。因此 M11-T1 保持 `in_progress`，不宣称 exactly-once，也不进入 M11-T2。

#### M11-T1 第四个真实纵切边界

- 新增 async `RunLeaseStore` 共同合同、内存参考实现、`0004_run_leases.sql` 和 PostgreSQL 适配器。Store 生成 opaque token，handle 的字符串与安全摘要不暴露原值，数据库只保存 SHA-256；PostgreSQL 以数据库时钟判断过期。
- acquire 只允许 running owned Run 且不覆盖过期记录；heartbeat/release 必须匹配未过期 token/version。scanner 使用 `FOR UPDATE SKIP LOCKED` 轮换 recovery token，旧执行者不能复活租约。
- 显式 `RunRecoveryService` 把 running ToolExecution 终结为 unknown、pending/waiting 终结为 cancelled，再提交非重试 `run_orphaned` Run 终态；跨 Store 故障靠 recovery lease 再过期继续收敛，不宣称共同事务或 exactly-once。
- 真实 PostgreSQL 四进程 probe 证明崩溃持有者留下的过期租约在两个 scanner 竞争时只有一个恢复者；触发器故障证明工具先收敛而 Run/Event 回滚，下一次扫描可完成终态。
- 尚未完成：默认 Container/Coordinator 的 acquire/heartbeat/release 与 scanner 调度、同步 Approval/Memory 的 async 线程和取消边界、统一应用重启恢复及跨外部系统 exactly-once。因此 M11-T1 保持 `in_progress`，不进入 M11-T2。

#### M11-T1 第五个真实纵切边界

- `RunLeaseStore` 增加只接受 `queued`/`waiting_approval` 精确前置状态的 execution reservation；显式注入 lease 的 Coordinator 在 `run.started`/`run.resumed` 前先保留租约，关闭 running Run 从未创建 lease row 的不可扫描窗口，既有 running-only `acquire()` 保持兼容。
- 每个 execute/resume 拥有独立 heartbeat session；正常路径按 reservation、生命周期提交、heartbeat、Runtime、停止 heartbeat、pause/terminal、release 排序。heartbeat 丢失或数据库不可用会取消 Runtime 并保留 running Run 给 scanner，不能由失去执行权的 Coordinator 伪造终态。
- 内存风险合同覆盖 start 结果未知、双 Coordinator 单 Runtime、pause/resume、cancel、lease-lost、heartbeat unavailable 和 release failure；真实 PostgreSQL 纵切证明 heartbeat version 推进、terminal release，以及数据库强制过期后由现有 scanner 收敛为 `run_orphaned`。
- 尚未完成：默认 Container/HTTP 注入、定时 scanner/lifespan 调度、统一应用进程重启恢复、同步 Approval/Memory async 线程边界和外部副作用 exactly-once。因此 M11-T1 继续 `in_progress`，不进入 M11-T2。

#### M11-T1 第六个真实纵切边界

- 新增显式 `RunRecoverySupervisor`，每个实例只拥有一个后台 task；首轮立即扫描，后续在上一轮完成后等待周期，因此同一实例不会重叠调用既有 `RunRecoveryService.scan_once()`。
- 生命周期固定为 created/running/closing/failed/closed；start/close 幂等边界、关闭期间拒绝假启动、close 取消并等待 scan 清理，以及调用方取消 close 时继续传播 `CancelledError` 均有自动化合同。
- claim 级 `StoreError` 和单 Run `FAILED` 不终止循环，下一周期继续；非 Store 程序错误保持可见。真实 PostgreSQL 纵切证明 supervisor 自动 claim 过期 lease、提交 `run_orphaned`、释放租约并关闭。
- 尚未完成：默认 Container/HTTP/FastAPI lifespan 注入、统一应用 composition 与进程重启恢复、同步 Approval/Memory async 线程边界和外部副作用 exactly-once。因此 M11-T1 继续 `in_progress`，不进入 M11-T2。

#### M11-T1 第七个真实纵切边界

- 新增显式 `PostgresExecutionComposition`，按 `PostgresPersistence.open/setup -> lease-aware RunCoordinator -> RunRecoveryService/RunRecoverySupervisor -> supervisor.start` 固定启动顺序；setup、配置或 supervisor start 失败时按已取得资源逆序清理。
- composition 固定 running/closing/closed/failed 关闭语义和 `supervisor.close -> persistence.close` 顺序。重复关闭幂等，supervisor 关闭失败仍尝试关闭 persistence，调用方取消继续传播。
- 真实 PostgreSQL 的旧 holder 进程由 composition Coordinator 开始执行后以 17 退出；PID 不同的新 composition 只依靠自动 supervisor 把 Run 收敛为 `run_orphaned`、写入唯一失败事件并释放 lease，probe 输出保持有界和脱敏。
- 尚未完成：composition close 前的 execute/resume admission stop 与 active Coordinator drain、默认 Container/HTTP/FastAPI lifespan 注入、同步 Approval/Memory async 线程边界和外部副作用 exactly-once。因此 M11-T1 继续 `in_progress`，不进入 M11-T2。

#### M11-T1 第八个真实纵切边界

- `RunCoordinator` 增加 accepting/quiescing/quiesced 生命周期；quiescing 后在既有 active lock 内拒绝新 execute/resume，多个 quiesce 调用共享一个不可重启的 drain task。
- quiesce 先给 active execution 自然完成宽限期；超时后使用内部 `coordinator_shutdown` 取消并 await Runtime/heartbeat 清理，不提交用户取消终态，不 release 结果未知 lease。调用方取消等待时先完成 drain 再传播。
- `PostgresExecutionComposition.close()` 固定 `coordinator.quiesce -> supervisor.close -> persistence.close`。真实 PostgreSQL 证明自然完成后 terminal+release，及 timeout 后 running+lease 由下一 composition 自动收敛为 `run_orphaned`。
- 尚未完成：默认 HTTP/命令入口停止、同步 PostgreSQL Approval/Memory 的 async 线程隔离、默认 Container/FastAPI lifespan 注入和外部副作用 exactly-once。因此 M11-T1 继续 `in_progress`，不进入 M11-T2。

#### M11-T1 第九个真实纵切边界

- 新增共享 `PostgresSyncStoreBridge` 与 Approval/Memory async façade；有界专用 worker 数对齐 sync pool 容量，参数在 submission 前脱离调用方引用，真实同步数据库调用不再阻塞 event loop。
- queued timeout/cancel 尝试取消尚未开始的 submission；running timeout 返回稳定 `store_operation_timeout` 与 `result_unknown=true`，不硬取消线程、不自动重试或复用晚到结果。sync pool 耗尽继续越界为稳定 `store_unavailable`。
- bridge close 停止 admission 并等待 in-flight worker，persistence 再关闭 sync/async pools；同步 pool open 也采用 owned worker。真实 PostgreSQL 证明审批/记忆事务、pool exhaustion 和 composition close 等待。
- 尚未完成：默认 Container/FastAPI lifespan、HTTP/命令 admission 与 async façade 接线，以及外部副作用 exactly-once。直接同步 compatibility 调用也不受 bridge 追踪。因此 M11-T1 继续 `in_progress`，`KI-023` 仅为 mitigated，不进入 M11-T2。

### M11-T2：真实 pgvector 文档与检索闭环

- 依赖：M11-T1。
- 产物：仅供集成测试的 `deploy/compose.integration.yaml`、启用 vector 扩展、文档/切片表、向量维度约束、索引、增删改和检索 SQL。
- 迁移：复用现有 `PgVectorKnowledgeBase` 领域边界，把启动时隐式 Demo 写入改成显式幂等 seed。
- 测试：真实容器中插入、替换、删除、相似度查询、维度错误和事务回滚。
- 验收：不再以 Fake Connection 作为向量数据库完成证据；M11 不提前把数据库生产化到主 Compose，M13 再完成密钥、健康检查和部署整合。

### M11-T3：Embedding Adapter 与批处理

- 依赖：M8-T1、M11-T2。
- 产物：确定性离线 Embedding、显式在线 Embedding adapter、批处理、重试、缓存键和维度元数据。
- 约束：在线模型和费用显式启用；离线默认测试不调用网络。
- 测试：批次拆分、空输入、维度漂移、部分失败、缓存命中和敏感日志脱敏。

### M11-T4：ContextAssembler 与 Token 预算

- 依赖：M10-T3、M11-T3。
- 产物：系统约束、最近消息、摘要、长期记忆、RAG、Skill 的选择和排序；预算报告和来源标记。
- 测试：长对话裁剪、关键事实保留、恶意检索指令隔离、超预算、摘要失败和不同用户隔离。
- 验收：至少一组长对话固定测试证明关键事实仍可命中，并能解释每段上下文为何进入模型。

### M11-T5：持久记忆进入主 Run

- 依赖：M11-T1、M11-T4。
- 产物：消息写入、短期窗口、经批准长期事实、读取/纠正/删除 API、版本冲突和审计记录。
- 测试：重启恢复、错误记忆纠正、删除后不再注入、跨用户隔离、模型推测不自动写入。
- 关闭目标：KI-014；KI-005 的上下文与记忆部分。

### M11-T6：RAG 固定评测集与指标

- 依赖：M11-T2 至 M11-T5。
- 产物：不少于 50 条查询的版本化数据集、相关文档标注、Recall@K、MRR、回答依据正确率和失败分析。
- 对照：离线稀疏检索、pgvector、可选重排在相同数据集比较质量、延迟和成本。
- 验收：阈值写入评测配置；未达标不能通过增加无关文本掩盖失败。
- 关闭目标：KI-006。

### M11-T7：显式在线 Embedding 冒烟

- 依赖：M11-T3、M11-T6。
- 产物：独立在线测试和验证记录，不进入默认离线门禁。
- 前置：在线开关、API Key、显式 Embedding 模型和用户单次执行授权。
- 验收：真实向量写入 pgvector 并完成查询；记录维度、批次、耗时、Token/费用和模型名；敏感输入不进入日志。
- 依赖边界：无授权时不阻塞 M12 的离线与数据库结构任务，但 M11 不能标记 `accepted`。

### M11-T8：M11 跟练与验收

- 依赖：M11-T1 至 M11-T6；在线状态引用 M11-T7。
- 产物：`docs/stages/11-context-memory-rag.md`、迁移图、评测报告、速查、自测和费曼任务。
- 验收：学习者能导入新资料、解释一次召回失败、纠正记忆并在重启后验证恢复。

## M12：统一持久 Run 与实时 Agent UI

### M12-T1：新 Run API 与状态事务

- 依赖：M10-T2、M11-T1。
- 产物：创建 Run、查询 Run、列出会话 Run、审批和取消端点；服务端 `Idempotency-Key`。
- API：创建返回 202 + `run_id`；查询返回统一状态、答案、引用、usage 和错误。
- 测试：身份、匿名 capability、幂等重复提交、非法状态转换、取消和终态不可重开。

### M12-T2：持久事件 SSE 与续传

- 依赖：M8-T2、M12-T1。
- 产物：`GET /api/runs/{id}/events?after=<sequence>`、历史补发、实时等待、心跳和终态关闭。
- 测试：半包、多帧、断线、重连、重复 after、慢消费者、取消和事件顺序。
- 验收：事件在执行过程中可观察，不再等待完整 Run 后回放；SSE 断线不触发副作用重放。

### M12-T3：Agent、RAG、记忆与审批统一到同一 Run

- 依赖：M11-T4、M11-T5、M12-T2。
- 产物：同一个 Run 内完成上下文、检索、工具、审批、回答、引用、usage 和终态。
- 迁移：独立 Research API 暂留兼容，但新 Vue 主链不再调用它覆盖答案。
- 测试：答案和证据属于同一 Run；拒答、审批、RAG 失败和模型失败事件一致。
- 关闭目标：KI-007 的后端部分。

### M12-T4：Vue 类型化状态机与刷新恢复

- 依赖：M12-T1 至 M12-T3。
- 产物：判别联合 `AgentEvent`、Run ID/sequence 持久状态、重连、审批、工具、引用、usage 和成本 UI。
- 风格：沿用 Composition API、`agentApi.ts`、`useAgentDesk.ts` 和现有 CSS；当前阶段不引入 Pinia/UI 库。
- 验收：删除 `streamRun()` 后独立调用 `research()` 的双链；刷新后查询快照并从最后序号续传。

### M12-T5：前端单元测试与真实浏览器 E2E

- 依赖：M12-T4。
- 产物：SSE parser、状态机、取消、重连单测；浏览器中的会话、运行、断线恢复和审批 E2E。
- 依赖边界：测试库和浏览器依赖需先列清单并获用户许可。
- 验收：测试覆盖分帧、无效 JSON、重复事件、Abort、终态和页面恢复。
- 关闭目标：KI-007、KI-008 的前端部分。

### M12-T6：兼容层决策与 M12 跟练

- 依赖：M12-T5。
- 产物：`docs/stages/12-realtime-agent-ui.md`、API 迁移记录和旧端点保留/替代 ADR。
- 验收：只有新旧契约、Vue 和文档全过后，旧 POST SSE 或独立 Research 主链才能标记 `superseded`。

## M13：生产工程、观测、测试与部署

### M13-T1：Trace、Metrics、Usage 与成本

- 依赖：M8-T4、M12-T3。
- 产物：保留领域 `RunObserver`，增加可替换 trace/metrics sink、节点/模型/工具 span、usage ledger 和成本摘要。
- 安全：Trace 默认脱敏；可配置关闭敏感模型和工具内容。
- 测试：成功、重试、工具拒绝、模型失败和 RAG 失败均产生相关联观测。
- 验收：能从 run ID 定位一次预置失败的层、步骤、耗时和成本。

### M13-T2：统一错误、重试、超时与取消

- 依赖：M12-T1、M13-T1。
- 产物：稳定错误码、retryable 标记、指数退避、步骤/总预算和持久取消。
- 测试：提供方限流、鉴权失败、MCP 断线、数据库故障、幂等/非幂等工具、取消竞争和预算耗尽。
- 验收：有副作用工具没有持久幂等键时不自动重试。

### M13-T3：分层统一验证与 CI

- 依赖：M9-T3、M11-T6、M12-T5、M13-T2。
- 产物：统一验证脚本和 CI 配置，分为 offline、MCP、PostgreSQL、frontend、E2E、Docker、online opt-in。
- 规则：离线门禁默认必跑；在线任务不接收仓库密钥，不因未授权而失败默认 CI。
- 验收：任一门禁失败时脚本不能打印“全部通过”；跳过项必须显式汇总。
- 关闭目标：KI-008。

### M13-T4：Docker/pgvector/Nginx 实际部署验收

- 依赖：M11-T2、M12-T2、M13-T3。
- 产物：Compose integration profile、运行时 secret 注入、迁移/seed、健康检查和 Nginx SSE 配置。
- 验收：实际构建镜像、启动服务、检查健康、运行数据库集成和通过 Nginx 验证实时 SSE。
- 约束：Docker Engine 不可用时状态保持 `code_complete`，不能写 `verified`。
- 关闭目标：KI-009。

### M13-T5：代码 Agent 资源与进程安全

- 依赖：M13-T2。
- 产物：流式有界 stdout/stderr、子进程树清理、固定环境、资源预算和审计结果。
- 测试：无限输出、超时子进程、嵌套进程、取消、命令拒绝、路径逃逸和 Windows junction 能力说明。
- 关闭目标：KI-011 的代码执行部分。

### M13-T6：基础压测与故障演练

- 依赖：M13-T1 至 M13-T5。
- 产物：并发 Run、慢客户端、数据库断开、模型限流和重启恢复场景；延迟、错误率和资源数据。
- 验收：容量估算使用实测参数更新，降级和恢复步骤可重复执行。

### M13-T7：M13 跟练与验收

- 依赖：M13-T1 至 M13-T6。
- 产物：`docs/stages/13-production-engineering.md`、故障手册、观测速查、考核和费曼任务。
- 验收：学习者能从一次未知故障开始，用 Trace、日志和指标定位并恢复服务。

## M14：真实浏览器、多模态与最终作品集

### M14-T1：真实 Browser Adapter 与受控动作

- 依赖：M12-T1、M13-T2、M13-T4。
- 产物：真实浏览器自动化适配器、DOM/截图观察、导航、点击和输入动作；现有离线 planner 保留为安全对照。
- 约束：浏览器运行在受控环境；默认使用专用测试站点和无真实个人登录态。
- 测试：计划与实际页面不一致、元素消失、跨域、弹窗、新窗口和下载均 fail closed。

### M14-T2：Browser SSRF 与完整审批绑定

- 依赖：M14-T1。
- 产物：完整 URL/计划摘要审批、DNS/IP/重定向复核、私网与云元数据拒绝、上传下载策略。
- 测试：loopback、私网、链路本地、保留地址、DNS 重绑定模拟、跨路径审批复用和重定向绕过。
- 关闭目标：KI-010。

### M14-T3：真实视觉输入与多模态推理

- 依赖：M8-T4、M13-T2。
- 产物：复用统一模型配置的图像输入、结构化观察、OCR/视觉结果不可信标记、预算与失败回退。
- 安全：保留现有 PNG 边界校验；视觉文字不能覆盖系统权限或直接触发副作用。
- 测试：有效图片、损坏/超限图片、错误 MIME、提示注入图片、模型超时和无在线授权。

### M14-T4：显式在线视觉冒烟

- 依赖：M14-T3。
- 产物：独立在线视觉验证与费用记录。
- 前置：在线开关、API Key、显式支持视觉输入的模型和用户单次执行授权。
- 验收：真实图片产生结构化观察；usage/费用可记录；图片中的提示注入不能改变权限或触发工具。

### M14-T5：高级 Agent 评测与对照

- 依赖：M14-T2、M14-T3。
- 产物：浏览器和多模态固定任务集，记录成功率、步骤数、延迟、成本、安全拒绝和人工介入率。
- 验收：不能只展示成功录屏；至少包含失败样例和修复/降级说明。

### M14-T6：生产级作品集交付

- 依赖：M14-T5；在线演示状态引用 M14-T4。
- 产物：真实业务场景、架构图、在线或可复现部署、演示视频脚本、评测报告、成本、威胁模型、故障复盘和迁移说明。
- 必须包含：至少 3 个真实工具，其中至少 1 个有副作用且具备审批和幂等。
- 验收：学习者能不看答案完成部署、演示、故障定位和架构答辩。

### M14-T7：30 项大纲最终审计

- 依赖：M8–M14 所有任务达到各自验收门槛。
- 产物：逐项实现证据、测试 ID、演示入口和残余风险；更新 syllabus map 和最终答辩材料。
- 验收：30 项不能以“依赖存在”或“文档提及”判定完成；必须有实现和可复现证据。
- 未执行的在线/容器能力必须明确标记，不能隐含为已验证。

### M14-T8：M14 跟练与最终验收

- 依赖：M14-T1 至 M14-T7。
- 产物：`docs/stages/14-advanced-capstone.md`、最终速查、自测、费曼复述和面试项目表达。
- 验收：完成讲解、实操、排错、迁移和沉淀五类考核，形成可投递的初级 AI Agent/LLM 应用工程作品集。
