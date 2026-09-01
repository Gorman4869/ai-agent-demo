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

#### M11-T1 第十个真实纵切与任务验收结果

- `Settings` 新增默认 memory、显式 postgres 的 persistence gate；DSN 使用脱敏 `SecretStr`，仅配置 DSN 不启用数据库，缺失或无效 PostgreSQL 配置 fail closed。同步 `ApplicationContainer.create()` 只允许内存，`await ApplicationContainer.open()` 才打开 PostgreSQL composition。
- FastAPI lifespan 固定 `PostgreSQL composition -> MCP -> admission` 启动和 `HTTP/command drain -> composition -> MCP` 关闭。纯 ASGI middleware 覆盖完整 StreamingResponse body；`ApplicationRunCommands` 与 HTTP 共用 gate，composition 继续负责 Coordinator quiesce、supervisor 与两类 pool。
- 记忆 HTTP 只调用 `async_memory_store`，application approval 只调用 `async_approval_store`；legacy Run HTTP/同步 ToolRegistry 继续隔离且不向 durable Store 双写，统一 Run 与审批端点仍由 M12 承接。
- 真实 PostgreSQL 91 项通过：两个完整 FastAPI lifespan 先写后删同一持久 fact，application Container 的 Approval façade 执行 grant/单次 consume；完整离线门以后端 463 项通过、1 项既有 Windows symlink 跳过，Code Agent、依赖、Vue、MCP TypeScript 和 Compose 配置通过。
- M11-T1 的 migration、Run/Event/Approval/Memory Store、checkpointer、ToolExecution、lease/recovery、连接生命周期、事务边界与默认 application composition 验收满足，任务更新为 `verified`。外部副作用 exactly-once、Windows/生产部署、统一 durable Run HTTP 与 pgvector 不属于该结论；下一原子任务为 M11-T2。

### M11-T2：真实 pgvector 文档与检索闭环

- 依赖：M11-T1。
- 产物：仅供集成测试的 `deploy/compose.integration.yaml`、启用 vector 扩展、文档/切片表、向量维度约束、索引、增删改和检索 SQL。
- 迁移：复用现有 `PgVectorKnowledgeBase` 领域边界，把启动时隐式 Demo 写入改成显式幂等 seed。
- 测试：真实容器中插入、替换、删除、相似度查询、维度错误和事务回滚。
- 验收：不再以 Fake Connection 作为向量数据库完成证据；M11 不提前把数据库生产化到主 Compose，M13 再完成密钥、健康检查和部署整合。

#### M11-T2 真实纵切与任务验收结果

- `ADR-0023` 固定独立 knowledge migration 命名空间、`knowledge_documents`/`knowledge_chunks`、课程 `vector(3)`、cosine `<=>` 与 HNSW `vector_cosine_ops`；M11-T1 的 vanilla PostgreSQL migration 和主 Compose 均未修改。
- `PgVectorKnowledgeBase` 通过版本化 migration 显式建表，文档 replace、级联 delete、相似度 search 与摘要 seed 均使用事务。FastAPI import、`create_app()` 和 lifespan 不再隐式写 Demo；只有固定 `/api/knowledge/demo-seed` 命令触发幂等 seed。
- 固定 `pgvector/pgvector:0.8.1-pg17` 的 localhost-only integration Compose 实际执行 extension/schema/index 检查、插入、替换、删除、相似度查询、同摘要不重写、维度错误和旧内容回滚；4 项真实数据库测试通过，不再把 Fake Cursor 当完成证据。
- 共享 KnowledgeBase/HTTP 行为变化触发完整离线门：最终后端 470 项通过、1 项既有 Windows symlink 跳过，Code Agent、依赖、Vue、MCP TypeScript 与主 Compose 配置通过。M11-T1 PostgreSQL 91 项和 M1 隔离 10 项也通过。
- M11-T2 更新为 `verified`。该结论不包含在线 Embedding、批处理/缓存、固定 RAG 指标、默认 Container pgvector 接线或生产部署；下一原子任务为 M11-T3。

### M11-T3：Embedding Adapter 与批处理

- 依赖：M8-T1、M11-T2。
- 产物：确定性离线 Embedding、显式在线 Embedding adapter、批处理、重试、缓存键和维度元数据。
- 约束：在线模型和费用显式启用；离线默认测试不调用网络。
- 测试：批次拆分、空输入、维度漂移、部分失败、缓存命中和敏感日志脱敏。

#### M11-T3 第一个离线纵切边界

- `ADR-0024` 固定 knowledge 层 Provider/Model 所有权、冻结 provider/model/revision/dimensions 元数据、单条复用批次、版本化缓存键、按批次暂时性重试和在线 composition 授权边界。
- 新增标准库 SHA-256 token-hash Provider 与通用 Batching Model；确定性输入先规范化空白，批次保持顺序，空批不调用 Provider，部分返回、metadata/维度漂移及非法向量 fail closed。
- `PgVectorKnowledgeBase` 对文档所有切片执行一次 Model batch，并在打开数据库前校验完整结果；真实 pgvector CRUD/查询 4 项继续通过，证明批次协议已进入数据库调用链。
- 新增 12 个关键测试方法或等价覆盖；知识/API 定向 67 项、M1 隔离 10 项通过。没有依赖、Settings、schema 或跨前后端接口变化，因此不重复完整全仓门。
- 本纵切达到本地 E3，但 M11-T3 保持 `in_progress`：缓存命中、暂时性重试、显式在线 SDK Adapter/Settings 和真实授权冒烟尚未实现。

#### M11-T3 第二个离线纵切边界

- 新增版本化 `embedding:v1:<sha256>` key、线程安全且容量有界的进程内 LRU，以及可选缓存的 Batching Model；规范化重复输入只请求一次 Provider，缓存命中仍复核向量合同。
- 所有 miss 批次成功且完成 metadata/数量/维度/有限值校验后才写缓存；后批失败或 retry 耗尽不缓存已成功前缀，非法 key 和污染向量 fail closed。
- 新增 `RetryableEmbeddingError` 与 `RetryingEmbeddingProvider`；每次尝试快照同一 Provider batch，只重试显式暂时性错误，耗尽映射稳定错误，协议/维度/metadata 错误不重试。
- 新增 11 个关键测试方法；Embedding/PgVector/RAG/API/Container 定向 78 项、真实 pgvector 4 项和 M1 隔离 10 项通过。没有依赖、Settings、schema 或跨前后端接口变化，因此不重复完整全仓门。
- 本纵切达到本地 E3，但 M11-T3 保持 `in_progress`：显式在线 SDK Adapter、embedding-specific Settings/composition 与真实授权冒烟尚未完成；内存缓存也不是持久或跨进程证据。

#### M11-T3 第三个离线纵切与任务验收结果

- 新增显式 `OpenAIEmbeddingProvider`，通过已锁定 OpenAI SDK 的公开 `client.embeddings.create()` 执行有界 batch；响应按 `index` 恢复输入顺序，缺失/重复索引、非法 usage、维度和值错误均映射为稳定无内容错误。
- SDK Client Factory 仅由 composition 注入 Key 和 timeout，按 batch 延迟创建并关闭 client，固定 `max_retries=0`；共享 `RetryingEmbeddingProvider` 是唯一重试所有者，只重试连接与服务端暂时性错误，认证、权限、配额/限流、请求和响应协议错误不重试。
- 新增 embedding-specific Settings：默认 `offline`，只有全局 online、embedding provider/model/revision 和共享 `OPENAI_API_KEY` 同时合法才允许在线 composition。仅存在 Key、chat model 或 embedding 标签不会启用；安全摘要和 Container repr 不暴露原值。
- 离线风险测试通过真实 OpenAI SDK + `httpx.MockTransport` 执行请求序列化、响应解析、顺序恢复、usage、缓存命中、错误分类、重试、资源关闭和敏感信息边界。最终定向回归 160 项、真实 pgvector 4 项、M1 隔离 10 项及完整离线门通过；完整门后端 505 项通过、1 项既有 Windows symlink 能力跳过，Vue、MCP TypeScript、依赖、Code Agent 与 Compose 配置通过。
- M11-T3 达到 `verified`。该结论只证明离线 E2/E3 构造与协议映射，不是在线 Provider、语义质量或费用证据；真实单次在线 Embedding 仍仅由 M11-T7 在新的明确授权下执行。下一原子任务为 M11-T4。

### M11-T4：ContextAssembler 与 Token 预算

- 依赖：M10-T3、M11-T3。
- 产物：系统约束、最近消息、摘要、长期记忆、RAG、Skill 的选择和排序；预算报告和来源标记。
- 测试：长对话裁剪、关键事实保留、恶意检索指令隔离、超预算、摘要失败和不同用户隔离。
- 验收：至少一组长对话固定测试证明关键事实仍可命中，并能解释每段上下文为何进入模型。

#### M11-T4 第一个离线纵切边界

- `ADR-0025` 固定六种 Context 来源及 trust、owner scope、服务端选择优先级、独立渲染顺序、完整片段裁剪和估算预算报告；片段不能自行提升 trust 或 priority。
- 新增纯标准库 `ContextAssembler`：system 不可静默丢弃，Memory/Recent/Summary 强制 owner 匹配，RAG 固定为 `untrusted_evidence`，摘要不可用进入报告，空输入返回零成本 no-op。
- 总预算按完整 `context-assembly-v1` JSON 计算且不超过现有 `RuntimeRequest.prompt_context` 的 32 KB；`ceil(UTF-8 bytes / 4)` 只标为离线估算，不冒充 Provider Token、usage 或费用。
- 新增 10 个关键测试方法或等价覆盖；Context/Runtime/Skill/Memory/RAG/M10-T3/Container 定向 88 项和 M1 隔离 10 项通过。没有修改共享 Runtime、Container、Store、依赖、构建或跨前后端接口，因此不重复完整全仓门。
- 本纵切达到本地 E3，但 M11-T4 保持 `in_progress`：尚未从真实 MemoryStore/KnowledgeBase/SkillBuilder 收集来源，也未接入默认 Runtime/Container 或完成最终长对话主链验收。

#### M11-T4 第二个离线纵切边界

- 新增显式 `ContextSourceCollector`、服务端 `ContextCollectionInput`、owner 绑定的 `CollectedContext` 与可注入 `ContextSummaryResult` 协议；没有修改现有 MemoryStore、KnowledgeBase、SkillContextBuilder、RuntimeRequest 或 Container 合同。
- collector 实际调用 `MemoryStore.messages()`/`facts()`、`KnowledgeBase.search()` 与 `SkillContextBuilder.build()`，把消息顺序、fact ID/owner、citation 排名和 Skill 快照映射为来源版本化摘要 ID，再通过现有 ContextAssembler 完成确定性组装。
- fact owner 在任何 Knowledge/Skill 查询前完整校验；摘要 unavailable 只进入来源可用性报告，不恢复 Store 窗口外历史。RAG 指令保持 `untrusted_evidence`，owner/session/query/content 不进入 repr 或预算报告。
- 新增 10 个关键测试方法或等价覆盖；collector 专项 10 项、Context/Runtime/Skill/Memory/RAG/M10-T3/Container 相关 98 项和 M1 隔离 10 项通过。没有依赖、数据库、构建、既有共享协议或跨前后端接口变化，因此不重复完整全仓门。
- 本纵切达到本地 E3，但 M11-T4 保持 `in_progress`：同步 collector 尚未进入显式 Runtime request preparation 或默认 Container，session 与 owner 的绑定仍由可信调用方保证；在线摘要、PostgreSQL fact 主链和最终统一 Run 不在本纵切证据内。

#### M11-T4 第三个离线纵切边界

- 新增显式 `ContextAwareRuntime`、`RuntimeContextBinding`、绑定 factory 协议与 `prepare_context_request()`；不修改现有 `RuntimeRequest`、`AgentRuntime`、`SkillAwareRuntime` 或 Container 合同。
- factory 只提供可信 owner/session/system constraints，query 强制取原 `RuntimeRequest.input_text`。collector→Assembler 非空时只用冻结复制写入 `prompt_context`，并保留 run/input/execution/checkpoint 对象；空上下文把原请求对象交给 delegate。
- 已有 `prompt_context`、非法绑定、collection 或 assembly 失败统一映射为稳定无内容 `context_unavailable`，delegate 不执行；绑定 factory 的程序错误继续传播。正常终态与 `RuntimeApprovalPause` 均原样透传。
- 真实 ConversationMemory/InMemoryKnowledgeBase/SkillContextBuilder→collector→Assembler→Fake AgentRuntime 的离线纵切已执行；summary unavailable、跨 owner、脱敏、字段身份和单次 delegate 均有自动化证据。它不是 import-only 或仅 Fake collection 证据，但 delegate 仍是确定性测试替身。
- 本纵切达到显式离线 E3，M11-T4 保持 `in_progress`：同步适配器尚未接默认 Container，RunCoordinator 也尚未把 RunRecord 的可信 owner/session 传播到 RuntimeRequest。下一纵切先固定该身份合同；不得从 input、tool arguments、principal 或 run ID 推导 session，也不得把同步 PostgreSQL/pgvector 放入事件循环。

#### M11-T4 第四个离线纵切边界

- `ADR-0026` 在 Agent Runtime 层固定冻结、repr-safe 的 `RuntimeContextIdentity(owner_id, session_id)`；它作为 `RuntimeRequest` 末尾可选字段保持直接 Runtime 调用兼容，并与 checkpoint owner 做 fail-closed 一致性校验。
- `RunCoordinator` 的 execute 与 approval resume 共用路径只从当前 owned `RunRecord.owner_id/session_id` 构造 identity。输入、工具参数、execution principal、模型结果和 run ID 均不能提供或覆盖 Context scope。
- 新增具体 `RuntimeIdentityBindingFactory`，只把 identity 与应用固定 system constraints 映射为既有 `RuntimeContextBinding`；缺失身份经 `ContextAwareRuntime` 稳定返回 `context_unavailable`，不查询 source、不调用 delegate。
- 真实 `RunCoordinator -> ContextAwareRuntime -> ConversationMemory/Knowledge/Skill collector -> ContextAssembler -> AgentRuntime delegate` 离线纵切已执行，approved resume 的两次 RuntimeRequest 也都携带同一 RunRecord identity；delegate 仍是确定性测试替身，不是在线模型证据。
- 新增 7 个关键测试方法或等价覆盖；专项 57 项、共享相关回归 175 项、M1 隔离 10 项通过。因修改跨模块共享 `RuntimeRequest` 合同，完整离线门已触发：后端 542 项通过、1 项既有 Windows symlink 能力跳过，Code Agent、依赖、Vue、MCP TypeScript 与 Compose 配置通过。
- 本纵切达到可信身份传播的显式离线 E3，但 M11-T4 保持 `in_progress`：默认 Container 尚未采用 ContextAwareRuntime，持久 PostgreSQL Memory/pgvector source 仍缺适当 async 边界。下一纵切只迁移默认进程内组合并保持显式 Runtime 注入不变，不进入 M11-T5/M11-T6。

#### M11-T4 第五个离线纵切与任务验收结果

- 默认内存 `ApplicationContainer.create()` 先解析同一份 ConversationMemory 与 InMemoryKnowledgeBase，再用共享 SkillContextBuilder、ContextSourceCollector、RuntimeIdentityBindingFactory 和固定应用 system constraint 包装所有内建 Manual/LangGraph/SDK Runtime；旧 SkillAwareRuntime 不再叠加。
- 显式 caller-supplied Runtime mapping 仍原对象透传。显式 PostgreSQL `ApplicationContainer.open()` 继续保留旧 Skill wrapper，没有把同步 PostgreSQL Memory 或 pgvector 放入 async Context collector；持久 source 接线由 M11-T5 的 async 边界承接。
- 默认 Container→RunCoordinator→ContextAwareRuntime→真实进程内 system/Skill/Memory/recent/RAG→ManualRuntime 纵切已执行；捕获的 prompt 保持固定 render/trust 顺序且不含 owner/session。另有默认 LangGraph 工具执行纵切证明结果与事件语义保持不变。
- 新增 5 个关键测试方法并收紧既有 Container 等价覆盖：五来源注入、两组 owner/session 隔离、缺失 identity/已有 prompt 在 source 前失败、未知 Skill 脱敏失败、默认 LangGraph 工具结果、显式 Runtime 保留与 PostgreSQL 边界均通过。
- Container 专项 22 项、Context/Runtime/Container/API/lifecycle/Memory/RAG/Settings/PostgreSQL composition 相关回归 244 项和 M1 隔离 10 项通过。共享默认 composition 行为变化触发完整离线门：后端 547 项通过、1 项既有 Windows symlink 能力跳过，Code Agent、依赖、Vue、MCP TypeScript 与 Compose 配置通过。
- M11-T4 达到 `verified`：长历史裁剪、关键 approved fact 保留、恶意 RAG trust 隔离、预算/摘要失败、不同用户隔离、可解释报告、可信 Run 身份和默认内存主链均有离线 E3。该结论不是 PostgreSQL/pgvector Context、持久消息写入、在线摘要、Provider Token/费用或真实模型质量证据；下一任务为 M11-T5。

### M11-T5：持久记忆进入主 Run

- 依赖：M11-T1、M11-T4。
- 产物：消息写入、短期窗口、经批准长期事实、读取/纠正/删除 API、版本冲突和审计记录。
- 测试：重启恢复、错误记忆纠正、删除后不再注入、跨用户隔离、模型推测不自动写入。
- 关闭目标：KI-014；KI-005 的上下文与记忆部分。

#### M11-T5 第一个离线纵切边界

- 新增独立 `AsyncMemoryContextSourceCollector`，通过现有 `AsyncMemoryStore.messages()`/`facts()` 读取请求绑定的 session/owner 数据；不扩宽同步或异步 Store Protocol，不修改 Runtime/Container。
- 两次 Memory 读取共享有界总 timeout；外层与 Store timeout 归一为 `memory_context_timeout`，其他 Store 失败为 `memory_context_unavailable`，调用方取消原样传播。任一失败、非法 payload 或 fact owner 不匹配均停止 Knowledge/Skill/summary。
- async 结果形成请求级非阻塞 Memory 快照后复用既有同步 collector，因此 source/trust、owner 校验、摘要、RAG/Skill 映射和 Assembler 预算合同保持单一实现。同步 Knowledge/Skill/summary 暂只允许进程内非阻塞实现。
- 新增 11 个关键测试方法：真实 AsyncLocal 全来源纵切、两组 owner/session 隔离、消息/事实 Store 失败、总 timeout、bridge timeout 归一、调用方取消、PostgreSQL façade 不直调同步 Store、非法 payload 与配置边界。专项/bridge 30 项、相关定向 116 项和 M1 隔离 10 项通过。
- 本纵切达到本地 E3，但 M11-T5 保持 `in_progress`：新 collector 尚未进入 Runtime/默认 PostgreSQL Container，没有运行真实数据库或证明重启后 fact 进入 Agent。下一纵切只固定 async Runtime request preparation，不提前实现消息写入、纠正/删除、版本冲突或审计。

#### M11-T5 第二个离线纵切边界

- 新增独立 `prepare_async_context_request()` 与 `AsyncContextAwareRuntime`，只 await 已验证的 `AsyncMemoryContextSourceCollector`，随后复用既有 binding、Assembler、`PreparedContextRequest` 与 `AgentRuntime` 合同；同步 `ContextAwareRuntime` 文件和行为不变。
- 已有 `prompt_context` 在 binding/Store 前失败；缺失可信 identity、跨 owner、Store failure/timeout 与 assembly failure 在 delegate 前统一为无内容 `context_unavailable`。调用方取消与依赖程序错误原样传播，不被伪装成 Runtime 失败。
- 非空 assembly 只替换 `prompt_context`，execution/checkpoint/context identity 保持同一对象；空 assembly 复用原请求。正常终态与 approval pause 原样透传，delegate 至多调用一次。
- 新增 11 个关键测试方法；async/sync Runtime 专项 24 项、Context/async Store/Container/Memory/PostgreSQL composition 相关回归 127 项和 M1 隔离 10 项通过。
- 本纵切达到显式 async Runtime preparation 的本地 E3，但 M11-T5 保持 `in_progress`：adapter 尚未进入默认 PostgreSQL Container，没有运行真实数据库或证明重启后 fact 进入 Agent。下一纵切只迁移 PostgreSQL built-in Runtime composition，保持默认内存与显式 caller Runtime mappings 不变。

#### M11-T5 第三个离线纵切边界

- `PostgresExecutionComposition.open()` 支持在 persistence setup 后执行一个同步 runtime factory，使默认应用组合只能从已打开 composition 获取 owned `async_memory_store`，再构造 Coordinator；factory 失败或返回空结果时关闭 persistence，且 runtimes 与 factory 必须且只能提供一个。
- 默认 PostgreSQL `ApplicationContainer.open()` 用进程内 Knowledge、Skill 和固定 system source 构造 `AsyncMemoryContextSourceCollector` 与单一 `AsyncContextAwareRuntime`，不叠加旧 `SkillAwareRuntime`，也不让同步 PostgreSQL Memory adapter 进入事件循环。
- 默认内存 `ApplicationContainer.create()` 继续使用同步 `ContextAwareRuntime`；显式 caller Runtime mapping 原对象透传。RuntimeRequest、AgentRuntime、Store、HTTP、数据库 schema 和外部 API 均未改。
- 新增 5 个 composition factory 关键测试并扩展 2 个 Container 纵切：setup/工厂/Coordinator 顺序、失败清理、非法返回、互斥输入、Runtime 暴露、真实 async Memory 五来源装配、同步 Memory 禁用和显式 Runtime 身份保持。专项 39 项、共享相关回归 283 项与完整离线门通过；全量后端 578 项通过、1 项既有 Windows symlink 条件跳过，Code Agent、依赖、Vue、MCP TypeScript 与 Compose 配置均通过。
- 本纵切达到默认 PostgreSQL composition 的确定性离线 E3，但没有运行真实 PostgreSQL、数据库重启或 pgvector Context。M11-T5 保持 `in_progress`；下一纵切只固定主 Run 的 user/assistant 消息写入边界、顺序、失败语义和幂等责任，不提前实现纠正/删除、版本冲突/审计或 M11-T6。

#### M11-T5 第四个离线纵切边界

- `RunCoordinator` 成为主 Run 消息的唯一发布者：只允许 `completed` terminal commit 的 `created=true` 仲裁赢家，从可信 `RunRecord.session_id/input_text` 与最终 answer 按 user→assistant 顺序写入现有 `AsyncMemoryStore`。failed、cancelled、approval pause 和 terminal replay 不写消息。
- 顺序固定为 durable terminal commit→user→assistant→live terminal notify→lease release。审批 resume 完成时写入原始输入和最终回答一次；新 Run 可从同一 Store 读取该回合作为 recent context，模型回答不会自动提升为长期 fact。
- terminal 之后的 Memory 失败不回滚或改写已完成 Run，也不自动重试；日志只保留稳定错误码、Run ID 和 result-unknown 标志。Coordinator 将写入作为 owned terminal publication 跟踪，quiesce 不会在写入中途关闭 persistence。
- 新增 8 个风险测试或等价覆盖，并扩展默认内存与 PostgreSQL composition 纵切；相关共享回归 245 项、M1 隔离 10 项与完整离线门通过。完整门后端 586 项通过、1 项既有 Windows symlink 条件跳过，Code Agent、依赖、Vue、MCP TypeScript 与 Compose 配置均通过。
- 当前两次 `append()` 只证明唯一写入者与 at-most-once 发布，不是跨 Run/Memory 的原子事务或 exactly-once：终态提交后崩溃可能缺消息，第二次 append 失败可能只留下 user。M11-T5 保持 `in_progress`；下一纵切先提供 Run-bound atomic/idempotent turn Store command 与真实 PostgreSQL 重启/replay 证据，再进入纠正/删除、版本冲突和审计。

#### M11-T5 第五个真实纵切边界

- `ADR-0027` 固定冻结、repr-safe 的 `PublishTurn` 与 `PublishTurnResult`；命令以 Run ID 作为幂等键，以版本化 SHA-256 digest 绑定隐藏 session 和 plain user/assistant。相同 binding replay 返回 `created=false`，同 Run 改 session/内容返回稳定 `memory_turn_conflict`。
- 内存参考实现用消息锁原子更新窗口与只含 session/digest 的账本；`0005_conversation_turn_publications.sql` 和 PostgreSQL Memory adapter 在一个 sync-pool 事务内写账本、分配两个 sequence、插入两条消息并裁剪。assistant 故障触发器证明消息、sequence 与账本一起回滚，并发同命令只有一个赢家。
- `AsyncLocalMemoryStore`/`AsyncPostgresMemoryStore` 暴露同一命令。Coordinator 新完成路径保持 terminal→turn→notify；execute/resume 读到既有 completed Run 时不调用 Runtime，只重放 turn，因此可修复 terminal 后崩溃缺口且不会重复消息。
- 两个 PID 不同的真实 PostgreSQL 探针证明：进程 A 只提交 completed Run、消息为 0；进程 B 以新 composition replay 两次后消息为 2、Runtime calls 为 0。完整 PostgreSQL 99 项、M1 隔离 10 项和完整离线门通过；全量后端 591 项通过、1 项既有 Windows symlink 条件跳过，其他门均通过。
- Run terminal 与 Memory turn 仍跨 async/sync pool，不是共同事务；没有后续 replay 时不会后台自动补写，digest 账本也尚无生产归档/GC。M11-T5 保持 `in_progress`；下一纵切进入 approved long-term fact 的 version CAS correction/delete 与 append-only audit，不提前进入 M11-T6。

#### M11-T5 第六个真实纵切边界

- `ADR-0028` 固定冻结、repr-safe 的 `CorrectMemoryFact` / `DeleteMemoryFact` 和 version CAS：事实从 version 0 开始，纠正继续要求批准且只改变 value，删除按 owner + expected version 执行；不存在/越权与陈旧版本分别使用稳定、无内容的 `memory_fact_not_found` / `memory_fact_conflict`。
- 内存实现以事实锁原子推进状态与审计；PostgreSQL migration 6 增加 version/deleted_at、tombstone 约束和 `(fact_id, version)` 唯一审计表。适配器用 `SELECT FOR UPDATE` 在同一 sync-pool 事务中更新事实并追加审计，删除清空 key/value，Context 读取只看 active facts。
- 审计只保留 created/corrected/deleted、版本和版本化 value digest，不保留 key/value；迁移回填当时仍存在的旧事实。数据库 trigger 拒绝普通 audit UPDATE/DELETE，但 SHA-256 不是加密，DB owner 仍可禁用 trigger/TRUNCATE，不能描述为外部不可篡改账本。
- 共享合同覆盖批准、owner、陈旧 CAS、并发唯一赢家、tombstone、审计脱敏与非法输入；真实 PostgreSQL 故障注入证明事实状态与审计同事务回滚。四个 PID 分别 create、correct、delete、audit，证明跨进程恢复且探针不输出事实内容。
- Memory/Context 26 项、共享离线 156 项、真实 PostgreSQL 109 项、四进程 1 项、M1 隔离 10 项和完整门通过；全量后端 597 项通过、1 项既有 Windows symlink 条件跳过，其他门均通过。
- 新 CAS 能力尚未暴露为公开 HTTP，兼容 delete 也不要求客户端 expected version；async result-unknown 只能通过当前 version/audit 仲裁而不能自动重试。M11-T5 保持 `in_progress`；下一纵切只接可信 owner 的异步 fact read/correct/delete/audit API 和跨 application lifespan 主 Run 证据，不修改前端、不进入 M11-T6。

#### M11-T5 第七个真实纵切边界

- 保留既有 `POST /api/memories` 响应与无 version 的兼容 DELETE；新增 owner-scoped active fact list/detail、approved version CAS correction、audit，以及 DELETE 的可选 `expected_version`。owner 只来自认证 `Principal`，请求体不能改写身份。
- 固定 401 未认证、403 未批准、404 不存在/已删除/跨 owner、409 陈旧 version 和 422 输入校验合同；错误不含 owner/key/value/current version。公开 audit 只返回 fact ID、version、created/corrected/deleted 与 64 位小写 digest，tombstone 后 owner 仍可审计。
- HTTP 只调用 application-owned async Memory façade。默认内存 API 回归覆盖兼容形状、身份隔离、纠正/删除、陈旧冲突、审计脱敏和请求校验；真实 PostgreSQL 在三个独立 application lifespan 中完成 legacy create→versioned correct→主 Run→versioned delete→主 Run→restart audit。
- 跨 lifespan 主 Run 使用默认 `ApplicationContainer.open()`、真实 durable Run/Coordinator 与 `AsyncContextAwareRuntime`：纠正后的下一 Run 只收到新值，删除后的再下一 Run 不再收到新旧值；新 composition 恢复 active list 为空且 audit 为 created/corrected/deleted。
- API 27 项、相关离线 115 项、真实 PostgreSQL application lifespan 2 项和完整 integration 110 项通过；全量后端 599 项通过、1 项既有 Windows symlink 条件跳过，M1 隔离 10 项及其他构建门全部通过。M11-T5 达到 `verified`；Run/Memory 共同事务、后台扫描、外部防篡改、自动 mutation retry、生产数据库和在线模型不属于该结论，下一任务为 M11-T6。

### M11-T6：RAG 固定评测集与指标

- 依赖：M11-T2 至 M11-T5。
- 产物：不少于 50 条查询的版本化数据集、相关文档标注、Recall@K、MRR、回答依据正确率和失败分析。
- 对照：离线稀疏检索、pgvector、可选重排在相同数据集比较质量、延迟和成本。
- 验收：阈值写入评测配置；未达标不能通过增加无关文本掩盖失败。
- 关闭目标：KI-006。

#### M11-T6 第一个离线纵切边界

- 新增严格 `rag-retrieval-dataset-v1` 固定 fixture：10 篇课程文档、50 条唯一查询、相关文档 ID 与依据词标注，版本 `m11-rag-v1` 和跨格式/换行稳定的 canonical-JSON SHA-256 内容摘要进入报告。`top_k=3`，sparse/pgvector 的 Recall@K、MRR、依据正确率阈值同时冻结为 0.9/0.8/0.9。
- 新增通用 `RagRetrievalEvaluator`：按相关文档宏平均 Recall@K、首个相关结果计算 MRR，只允许相关文档的已检索 excerpt 满足全部依据词。无结果、漏召回、未排名、依据缺失和未配置文档使用稳定失败码；查询、依据词、excerpt 与未配置 ID 不进入报告。
- 默认 sparse runner 只索引 fixture 文档并调用真实 `InMemoryKnowledgeBase.search()`；CLI 低于任一阈值时退出 1。最终 50 条结果 Recall@3=1.0、MRR=1.0、依据正确率=1.0；本地延迟只作同进程参考，Provider usage unavailable、费用 unknown。
- 新增 12 个关键测试方法；覆盖版本/数量/canonical 摘要、固定阈值、指标与首相关排名、空召回、无关文本不能掩盖依据缺失、未知文档脱敏、非法标注/schema/数量和默认 50 条基线。扩大 Knowledge/Embedding/pgvector/Context/eval 相关回归 78 项与 M1 隔离 10 项通过。
- 本纵切达到 sparse 指标合同的离线 E3，但 M11-T6 保持 `in_progress`：尚未用同一数据集和阈值执行真实 pgvector，也没有形成两种 retriever 的固定对照与实际失败分析。下一纵切不得静默修改 `m11-rag-v1` 数据或阈值来让 pgvector 通过；需要修正 fixture 时必须升版本并保留旧摘要证据。

#### M11-T6 第二个真实 pgvector 纵切与任务验收结果

- 新增明确仅供评测使用的三维、确定性课程主题 Embedding；它只识别固定课程词汇，不读取 Key、不调用在线 Provider，不能作为通用语义模型或生产检索质量的证据。
- 使用现有 `PgVectorKnowledgeBase` 的真实 PostgreSQL `vector(3)` 列、cosine distance 与 HNSW 索引，对未改动的 `m11-rag-v1` 同一 canonical 摘要、50 条查询、`top_k=3` 和冻结阈值运行评测。新增集成测试直接断言 pgvector 报告通过。
- sparse/pgvector 对照：sparse 为 Recall@3/MRR/依据正确率 `1.0/1.0/1.0`；pgvector 为 `0.98/0.946667/0.98`，通过 `0.9/0.8/0.9` 阈值。pgvector 保留 1 条 `memory-04` 漏召回及相关稳定失败码，未通过修改 fixture、标注或阈值隐藏它。
- 新增 Embedding 单元测试 2 项，既有真实 pgvector integration 5 项和固定 sparse 专项 12 项通过；报告和 CLI 仍不输出 query、依据词或 excerpt。本地 wall-clock 仅作受控进程参考，usage unavailable、费用 unknown。
- M11-T6 达到 `verified`，`KI-006` 关闭。在线 Embedding、生产容量/延迟、开放域质量、Provider Token/账单与持久/跨进程缓存仍不在本任务结论中；M11-T7 只能在 API Key、在线开关和用户单次授权后独立执行。

### M11-T7：显式在线 Embedding 冒烟

- 依赖：M11-T3、M11-T6。
- 产物：独立在线测试和验证记录，不进入默认离线门禁。
- 前置：在线开关、API Key、显式 Embedding 模型和用户单次执行授权。
- 验收：真实向量写入 pgvector 并完成查询；记录维度、批次、耗时、Token/费用和模型名；敏感输入不进入日志。
- 依赖边界：无授权时不阻塞 M12 的离线与数据库结构任务，但 M11 不能标记 `accepted`。

#### M11-T7 首次外部冒烟尝试（blocked）

- 用户已于 2026-08-27 提供 API Key 的本机环境变量并明确授权一次测试。预检只记录 `configured=true`，不读取或输出 Key。
- 选择 `text-embedding-3-small`、显式三维输出、batch size 1、retry 0 和两段非敏感合成文本；先写入本机 pgvector 测试库、再以相同文本查询、最后删除临时文档。
- 首两次在 SDK 创建 HTTP 客户端前被本机 SOCKS `ALL_PROXY` 与缺失 `socksio` 阻断，没有发出 Provider 请求。最终仅在子进程移除该 SOCKS 变量并保留 HTTP/HTTPS proxy 后到达 Provider，返回稳定 `embedding_provider_quota_or_rate_limited`。
- 本次没有完成向量写入或查询，没有得到 Provider usage、Token 或费用；只读确认临时 document count 为 0。不得把配置识别、SDK 创建失败或此错误码当作 M11-T7 E4 成功。
- M11-T7 保持 `blocked`，解除条件是可用的项目配额/限流窗口，并需要用户再次明确授权新的在线尝试；不安装 SOCKS 依赖、不改变全局代理或默认离线路径。

#### M11-T7 DashScope 替代 Provider 离线准备

- 学习者于 2026-08-27 选择阿里云百炼 `text-embedding-v4` 作为替代的在线 Embedding Provider；它不能复用固定 `vector(3)` 的 M11-T6 评测表。
- 新增独立的 `dashscope_knowledge_*` 64 维 pgvector migration、受限百炼 Workspace OpenAI-compatible endpoint、显式 `DASHSCOPE_API_KEY` gate 和无 Key 的 SDK/错误/pgvector 集成验证。原 OpenAI Adapter、三维表、固定评测集和默认离线路径保持不变。
- 在线 CLI 必须显式 `--authorized`，并固定 batch size 1、retry 0；它只写入一篇非敏感合成文档、查询一次、finally 删除，最多两次 Provider 请求。2026-08-28 已在单次授权、临时清除 SOCKS proxy 的子进程中完成百炼 E4：`text-embedding-v4`、64 维、两次请求、27 input/total tokens、约 2077 ms；费用来源仍未知，临时文档已删除。
- SDK 客户端创建阶段的可选依赖 `ImportError` 必须映射为无原始异常的稳定 `embedding_provider_client_configuration_invalid`；它不能被 CLI 吞为无法排查的通用失败码，也不能触发重试。

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

#### M12-T6 课程与兼容层验收结果

- `ADR-0033` 将 Vue 的 legacy POST SSE + 终态后 Research 覆盖答案双链标记为
  `superseded`，但保留 legacy sessions/runs/read/POST SSE 与独立 Research API 的隔离
  合同；没有删除端点、静默代理或 durable/legacy 双写。
- `docs/m12-api-migration.md` 固定 202、幂等、capability、sequence、snapshot、取消、审批
  与同 Run evidence 的迁移步骤；旧端点退出必须另有消费者、通知、回归和新 ADR 证据。
- Stage 12 汇总六次跟练、三张状态图、排错、自测、速查、费曼、最终清单和 30 项映射。
  Vue 生产源码 legacy 引用为零；46 项新旧 API 契约、12 项前端单测、2 项 Chromium E2E、
  Vue build、连续性和全量离线门均通过。
- 里程碑全量门后端 643 项通过、1 项既有 Windows symlink 能力跳过，其余 Code Agent、
  依赖、Vue、MCP TypeScript 与 Compose 配置通过。M12 达到 `verified`；生产认证、Nginx、
  统一 CI、usage/cost 账本和依赖公告仍由 M13 承接。

## M13：生产工程、观测、测试与部署

### M13-T1：Trace、Metrics、Usage 与成本

- 依赖：M8-T4、M12-T3。
- 产物：保留领域 `RunObserver`，增加可替换 trace/metrics sink、节点/模型/工具 span、usage ledger 和成本摘要。
- 安全：Trace 默认脱敏；可配置关闭敏感模型和工具内容。
- 测试：成功、重试、工具拒绝、模型失败和 RAG 失败均产生相关联观测。
- 验收：能从 run ID 定位一次预置失败的层、步骤、耗时和成本。

#### M13-T1 实现结果（2026-08-28）

- 保留旧同步 `RunObserver`；durable 主链新增 `EventRunObservability`，从 owner-scoped
  EventStore 重建 run/runtime node、plan/context node、model、tool spans 与对应 Metrics。
- 新增 async `TraceSink`/`MetricsSink` Protocol、No-op 与 deterministic in-memory adapter。
  Coordinator 只在事件持久化后观察，终态导出失败不回滚、不改写 Run。
- `scope=run` aggregate usage 成为事件溯源 ledger；累计快照不相加，cost summary 取最新有效
  sequence。未知费用保持 `null/unknown`，已知费用内部使用 Decimal；没有伪造单调用
  `UsageRecord`、版本化价格表或硬成本门。
- 新增 owner-scoped `GET /api/durable/runs/{run_id}/observability`；prompt、answer、delta、RAG
  excerpt、Memory、工具参数/结果、raw error、owner/session 和密钥均不进入返回或 sink。
- 8 项专项覆盖成功、累计 usage、模型重试、工具拒绝、模型失败、RAG 失败、sink 隔离和 owner
  隔离；真实 PostgreSQL 关闭/重开后按同一 run ID 重建 Trace/ledger。验证见
  `V-20260828-014`、设计见 `ADR-0034`。

### M13-T2：统一错误、重试、超时与取消

- 依赖：M12-T1、M13-T1。
- 产物：稳定错误码、retryable 标记、指数退避、步骤/总预算和持久取消。
- 测试：提供方限流、鉴权失败、MCP 断线、数据库故障、幂等/非幂等工具、取消竞争和预算耗尽。
- 验收：有副作用工具没有持久幂等键时不自动重试。

#### M13-T2 实现结果（2026-08-29）

- 新增内容无关的稳定错误目录与 fail-closed 决策：`retryable` 只是瞬态分类；次数、剩余
  deadline、幂等、可重放、副作用、持久幂等键和结果未知共同决定是否进入下一尝试。
- Manual/LangGraph 模型重试和 Agents SDK 公开 retry settings 使用显式有界指数退避；OpenAI
  client 自身仍为零重试，避免叠加。生产组合默认模型 2 次、只读工具 1 次重试。
- 共享 ToolRegistry 仅重试无副作用工具的稳定 timeout/I/O/MCP 瞬态错误。当前主链没有把
  持久外部结果仲裁证明注入普通工具调用，因此所有副作用工具保持零自动重试，人工批准不被
  当成持久幂等键。
- MCP adapter 保留 timeout、disconnect、remote error、invalid response 和 request rejected
  的不同安全错误码；Store mutation、终态提交和整个 Runtime 不套通用 retry loop，继续复用
  既有 command/event ID、CAS、lease、recovery 与持久取消赢家协议。
- 退避等待响应同一个 Run token/deadline；工具退避产生脱敏 `tool.retrying`、tool span 和
  `agent.tool.retry` metric。同步线程和已经发出的远端请求仍不是硬取消，`KI-017` 保留。
- 新策略/边界与跨 Runtime 回归通过；完整后端 666 项通过、1 项既有 Windows symlink 条件
  跳过。验证见 `V-20260829-001`，决策见 `ADR-0035`，工程说明见
  `docs/m13-reliability.md`。

### M13-T3：分层统一验证与 CI

- 依赖：M9-T3、M11-T6、M12-T5、M13-T2。
- 产物：统一验证脚本和 CI 配置，分为 offline、MCP、PostgreSQL、frontend、E2E、Docker、online opt-in。
- 规则：离线门禁默认必跑；在线任务不接收仓库密钥，不因未授权而失败默认 CI。
- 验收：任一门禁失败时脚本不能打印“全部通过”；跳过项必须显式汇总。
- 关闭目标：KI-008。

#### M13-T3 实现结果（2026-08-31，verified）

- `scripts/verify.ps1` 固定七层及 `default`、`integration`、`all` profile；显式选择的
  PostgreSQL/Docker 等 required layer 缺少前置条件时 fail closed，online 缺少本次授权时只
  显式 `SKIPPED`，不会执行独立在线脚本。
- 最终汇总逐层输出 `PASSED/FAILED/SKIPPED`。required layer 失败会停止后续执行、保留完整
  汇总并退出 1；失败路径和有 skip 的路径均不会打印全部通过。
- `.github/workflows/verification.yml` 拆分 offline、MCP、PostgreSQL、frontend、E2E、Docker
  和 online-policy job，只给 `contents: read`，不引用仓库 secret，也不传在线授权开关。
- 本地工作树已通过 offline 670 项（1 项既有 Windows symlink 跳过）、MCP 11 项、真实
  PostgreSQL/pgvector 120 项、Vue 12 项与 build、Chromium E2E 2 项及两份 Compose 配置；
  failure/skip/CI policy 入口测试 4 项通过。
- 首次远程 GitHub Actions run `#1` 在提交 `77492f0` 上真实执行：MCP、frontend、E2E、Docker
  和 online-policy 成功；offline 因干净 runner 缺少 TypeScript MCP build、PostgreSQL 因
  graceful-close 测试复用 100ms 租约而失败。该失败事实保留在 `V-20260831-001`。
- 最小修复提交 `38fd696` 上的远程 run `#2` 随后完成：offline、MCP、PostgreSQL、frontend、
  E2E、Docker 和 online-policy 七个 job 全部成功，见 `V-20260831-002`。online-policy 仍只证明
  未授权 skip，没有读取 Key 或调用 Provider；M13-T3 达到 `verified`，`KI-008` 关闭。
- 决策见 `ADR-0036`，工程入口见 `docs/m13-verification-ci.md`；没有构建镜像、启动服务、
  验证健康或 Nginx SSE，也没有读取 Key、执行在线调用或进入 M13-T4。

### M13-T4：Docker/pgvector/Nginx 实际部署验收

- 依赖：M11-T2、M12-T2、M13-T3。
- 产物：Compose integration profile、运行时 secret 注入、迁移/seed、健康检查和 Nginx SSE 配置。
- 验收：实际构建镜像、启动服务、检查健康、运行数据库集成和通过 Nginx 验证实时 SSE。
- 约束：Docker Engine 不可用时状态保持 `code_complete`，不能写 `verified`。
- 关闭目标：KI-009。

#### M13-T4 实现结果（2026-08-31，verified）

- 新增独立 `deploy/compose.deployment.yaml`：固定 pgvector 版本、password/DSN runtime secret
  文件、持久卷、显式 one-shot knowledge migration/seed、backend/frontend 健康顺序、localhost
  端口和受限容器权限；M11 的 trust/tmpfs integration Compose 保持不变。
- Settings 支持与直接 DSN 互斥的绝对 `AI_AGENT_POSTGRES_DSN_FILE`，读取失败和 seed CLI 只输出
  无内容稳定错误。`deployment_seed` 固定 offline 三维课程 Embedding，复用版本化 pgvector
  migration 与幂等 server-owned seed；FastAPI 启动仍不隐式 seed。
- backend 镜像补入默认 Runtime 启动必需的只读 `skills/`；Nginx 保持 buffering/cache off。
  `scripts/verify-deployment.ps1` 生成仓库外临时 secret 文件和唯一 project，实际 build/up、健康、
  两套 migration/seed/vector、独立测试库、SSE started→completed、同 backend 容器 restart 后 Run
  恢复，并只清理本次容器/网络/卷。
- 真实验收最终在 project `ai-agent-demo-m13-31796-2e35bbd1` 通过：PostgreSQL/pgvector 120 项
  通过，Nginx SSE 与 restart recovery 通过；清理复核没有 M13 容器、卷或网络，既有
  `ai-agent-demo-integration-postgres-1` 继续在 `127.0.0.1:55433` healthy。
- 前序失败均保留：Compose `secrets.environment` 不兼容、镜像漏复制 `skills/`、PowerShell
  纯文本健康换行误判，以及一次旧 recovery 子进程 psycopg stderr/timeout 非确定性失败。最终
  相同 120 项复跑通过；完整默认门在沙箱外以后端 681 项（1 项既有 symlink skip）、MCP 11 项、
  Vue 12 项和 production build 通过。
- 决策见 `ADR-0037`，工程入口见 `docs/m13-deployment.md`，验证见 `V-20260831-003`。本任务不含
  TLS、备份、高可用、外部 secret manager、生产容量、默认 Context 的 pgvector 接线或在线
  Provider；M13-T4 达到 `verified`，`KI-009` 关闭。

### M13-T5：代码 Agent 资源与进程安全

- 依赖：M13-T2。
- 产物：流式有界 stdout/stderr、子进程树清理、固定环境、资源预算和审计结果。
- 测试：无限输出、超时子进程、嵌套进程、取消、命令拒绝、路径逃逸和 Windows junction 能力说明。
- 关闭目标：KI-011 的代码执行部分。
- 实现结果：标准库 `process_runner` 持续排空 stdout/stderr，只保留有界前缀；Windows 使用
  kill-on-close Job Object，Linux 使用独立 process group，并对进程数、进程树内存和 CPU 做
  有界采样。timeout、取消、超限、监控失败和正常 parent 退出均收口树清理，结果以安全元数据
  进入 audit。
- 验证结果：Windows 与无网络/只读一次性 Linux 容器中的同一 20 项合同均通过（各有 1 项
  平台能力 skip）；完整 offline 门后端 691 项通过、1 项既有 symlink skip，Demo 与依赖检查
  通过。决策见 `ADR-0038`，证据见 `V-20260831-005`；M13-T5 达到 `verified`，`KI-011` 关闭。
- 边界：10ms 资源采样不是 cgroup/seccomp/VM；Windows Job assignment 不是 suspended-create
  原子绑定，Harness 也不提供默认禁网。完整 executable/argv 继续由服务端审核，恶意代码需要
  预隔离 worker/container；`KI-016/KI-017` 的 durable 故障和通用同步线程取消仍未关闭。

### M13-T6：基础压测与故障演练

- 依赖：M13-T1 至 M13-T5。
- 产物：并发 Run、慢客户端、数据库断开、模型限流和重启恢复场景；延迟、错误率和资源数据。
- 验收：容量估算使用实测参数更新，降级和恢复步骤可重复执行。

#### M13-T6 实现结果（2026-09-01，verified）

- 新增标准库 `backend.app.evals.load_fault` 与 CLI：冻结、安全报告覆盖延迟分位、吞吐、错误率、
  并发峰值和进程 RSS；默认离线实际执行内存 Container 并发、durable SSE 慢客户端和
  `ManualAgentLoop` 确定性限流重试，localhost 作用域通过 Nginx/FastAPI/PostgreSQL durable HTTP。
- 部署 verifier 只在唯一 `ai-agent-demo-m13-load-*` project 内停止/启动 PostgreSQL、验证
  fail-closed 5xx、新 Run 恢复和 backend restart 后旧 Run 可读，并在四个阶段记录点式 Docker
  资源快照；finally 精确清理本次容器、网络、卷和临时 secret。
- 相同负载/故障逻辑连续三次以 16 Runs / concurrency 4 完整通过，错误率均为 0；部署吞吐为
  17.333/s、11.557/s、6.639/s，p95 为 498.490ms、708.766ms、1,542.506ms。数据库恢复窗口
  分别记录 3、2、3 个明确终态失败，随后新 Run 成功；这固定为本机可重复但波动明显的工作点，
  不是生产容量/SLA。
- 相关回归最终 77 项通过，Python AST、PowerShell Parser、diff check 和三次 Docker cleanup
  通过。决策见 `ADR-0039`，工程入口见 `docs/m13-load-fault.md`，证据见 `V-20260901-001`；
  M13-T6 达到 `verified`。
- 边界：限流是 Fake Model；资源是 Probe RSS 与点式 `docker stats`；没有在线 Provider、长时间
  soak、多机/HA、进行中 Run 的 backend hard-kill、TLS 或公网流量。`KI-015/KI-016/KI-018`
  因各自剩余范围继续保持 mitigated。

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
