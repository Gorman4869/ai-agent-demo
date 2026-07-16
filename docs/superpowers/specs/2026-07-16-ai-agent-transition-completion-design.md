# AI Agent 转型课程补齐设计规格

## 文档元数据

- 设计日期：2026-07-16
- 设计范围：在现有 M0–M7 基础上新增 M8–M14
- 方案：渐进式补齐，不重写现有项目
- 文档状态：accepted，设计章节及落盘版本已由用户确认
- 在线模型边界：默认离线 Mock；仅在显式启用 `OPENAI_API_KEY` 后执行可能产生费用的在线验证
- 当前版本控制状态：本地 Git `main` 分支已初始化，基线提交为 `9a54ebe`；尚未配置远程仓库

## 1. 背景与当前基线

当前项目已经具备手写 Agent Loop、工具注册与校验、FastAPI、Vue Agent UI、RAG、内存记忆、可观测性、离线评测、安全审批、Docker 配置以及代码、多模态、浏览器安全实验。

2026-07-16 的只读审计确认：

- 后端测试 98 项通过，1 项因 Windows 符号链接能力不足跳过。
- Vue 前端构建通过。
- TypeScript MCP Server 构建通过。
- Node.js 与 Python 基础实验运行通过。
- Docker Compose 配置展开通过。
- Docker Engine 未运行，镜像构建、容器健康和 Nginx SSE 代理尚未验证。
- 30 个大纲主题中，13 项达到当前课程级验收，16 项部分覆盖，1 项 LangChain 实现缺失。

当前主要缺口不是文件数量，而是真实工程闭环：

1. OpenAI Agents SDK 只构造 Agent，没有真实 Runner 执行链路。
2. MCP 只有 Server，没有 Client 发现和调用。
3. LangGraph 没有 checkpoint、interrupt、resume 和持久恢复。
4. LangChain 只有依赖，没有对照实验。
5. RAG、向量库、记忆、审批和 Run 仍主要依赖进程内状态。
6. SSE 在 Run 完成后回放事件，不是真正的实时执行流。
7. Vue 在流结束后调用独立 Research API 覆盖答案，Agent 与 RAG 不属于同一个 Run。
8. 浏览器和多模态能力仍是离线安全模拟。
9. 缺少前端测试、MCP 协议级测试、真实数据库集成、CI/CD 和实际容器运行证据。

本设计从上述实际状态继续，不把原有 M0–M7 推倒重写，也不把“文档中出现过”视为“已经完成”。

## 2. 目标

### 2.1 产品与工程目标

在现有教学项目上建立一条可真实运行、可离线回归、可中断恢复、可审计、可部署的 Agent 主链路，使前端开发者完成课程后具备以下能力：

- 理解并能手写 Agent Loop。
- 能使用真实模型执行结构化输出和工具调用。
- 能实现 MCP Client/Server 互操作。
- 能使用 LangGraph 实现持久工作流、人工审批和失败恢复。
- 能建立真实 PostgreSQL、pgvector、Embedding、记忆和 RAG 评测闭环。
- 能实现真正的流式 Agent UI、断线续传和页面恢复。
- 能建立测试、观测、成本、安全、CI/CD 和部署证据。
- 能完成至少一个真实浏览器 Agent 和一个真实多模态流程。

### 2.2 学习目标

每个新增里程碑都必须形成训练闭环：

```text
原理讲解 -> 跟练实现 -> 自动化测试 -> 故障排查 -> 工作场景题 -> 费曼复述 -> 验收证据
```

### 2.3 连续性目标

即使发生断网、模型切换、上下文压缩或新会话接手，后续执行者也能通过仓库内文档确定：

- 已确认的架构决策。
- 当前准确状态。
- 已通过与未通过的验证。
- 已知问题和风险。
- 下一条精确原子动作。

## 3. 非目标

本阶段明确不做以下扩张：

- 不改造成微服务集群。
- 不提前引入 Redis、消息队列、Kubernetes 或服务网格。
- 不用 ORM 替换现有 dataclass、Protocol 和显式 SQL 风格。
- 不删除现有 Mock、手写 Loop 或安全实验。
- 不让 LangChain 成为核心运行时；它只承担框架对照学习。
- 不在未经用户确认时执行付费模型调用。
- 不把应用级路径和命令限制描述成完整 OS 安全沙箱。
- 不主动引入 Pinia 或新的 UI 组件库；现有 Vue 架构能满足当前阶段。

## 4. 设计原则

1. **现有进度优先**：保留原有学习顺序、接口和测试基线。
2. **一个领域契约，多种实现**：Mock、OpenAI、LangGraph、内存和 PostgreSQL 实现共享稳定协议。
3. **先持久化，再推送**：事件必须先进入 EventStore，SSE 只负责传输。
4. **副作用默认不重放**：没有持久幂等键就不自动重试副作用工具。
5. **离线默认、在线显式**：默认测试不依赖网络、密钥或付费 API。
6. **状态只有一个真相源**：计划、状态、验证和交接文档不相互复制易变信息。
7. **完成必须有证据**：代码完成不等于验收完成。
8. **安全约束高于模型输出**：模型、RAG、MCP、网页和多模态文字均视为不可信输入。

## 5. 总体架构

```text
Vue Agent UI
    |
    |-- 创建/恢复会话
    |-- 创建 Run
    |-- Fetch Streaming 订阅持久事件
    |-- 审批、取消、断线续传
    |
FastAPI API
    |
RunCoordinator
    |-- ManualRuntime
    |-- OpenAIAgentsRuntime
    `-- LangGraphRuntime
    |
共享能力层
    |-- Tool Registry / MCP Client / Skill Catalog
    |-- ContextAssembler / Memory
    |-- RAG / Embedding / Reranker
    |-- Approval / Idempotency / Security
    `-- Trace / Usage / Cost / Eval
    |
持久化层
    |-- PostgreSQL：会话、Run、事件、工具执行、记忆、审批
    |-- pgvector：文档向量
    `-- LangGraph Checkpointer：工作流中断与恢复
```

### 5.1 兼容策略

- 现有 `ManualAgentLoop` 保持教学职责，不改造成 SDK 包装器。
- 现有 `execute_agent()` 和旧 API 在迁移期保留，继续支撑现有测试。
- 新 API 使用异步 Runtime 和持久 Run 模型。
- Vue 完成新链路迁移后，再根据兼容性测试决定旧接口是否进入 `superseded`。

## 6. 组件边界

### 6.1 Settings 与应用容器

新增服务端拥有的 `Settings`，集中解析并验证：

- 运行模式和默认 Runtime。
- OpenAI 模型配置与在线开关。
- 数据库和 pgvector 连接。
- MCP Server 清单与权限。
- Token、费用、超时和重试预算。
- 日志与 Trace 敏感数据策略。

FastAPI 通过小型 `ApplicationContainer` 接收服务依赖，避免 `create_app()` 随里程碑增长出大量参数。

默认配置继续使用 `ManualRuntime + MockModel + 内存 Store`。在线示例必须显式选择 `agents_sdk` 或 `langgraph` Runtime，并同时满足在线开关和密钥校验。

### 6.2 AgentRuntime

三种运行时实现统一异步边界，概念接口如下：

```python
async def run(request, emit, control) -> AgentRunResult:
    ...
```

- `ManualRuntime`：包装现有同步手写 Loop，并把领域事件转换为持久事件。
- `OpenAIAgentsRuntime`：使用 OpenAI Agents SDK Runner/stream，映射工具、结构化输出、usage 和错误。
- `LangGraphRuntime`：承担主工作流、checkpoint、interrupt、resume、人工审批和重规划。

`RunCoordinator` 只负责编排 Runtime、Store、Observer 和控制信号，不包含具体模型或工具业务逻辑。

### 6.3 工具、MCP 与 Skill

- 现有 `ToolRegistry` 保留为共同工具领域契约。
- SDK 和 LangGraph 通过适配器使用相同工具 Schema 和执行规则。
- MCP Client 在应用 lifespan 中建立连接，发现工具后映射为受权限控制的工具定义。
- MCP 工具返回内容按不可信输入处理。
- Skill 第一阶段只加载 `SKILL.md`、引用资源和结构化元数据，用于生成受控上下文；Skill 文件不能直接执行任意代码。

### 6.4 ContextAssembler

`ContextAssembler` 统一组合：

- 最近对话。
- 已批准的长期记忆。
- RAG 证据。
- Skill 指令和参考资料。
- 系统安全约束。
- 当前 Token 预算。

它负责选择、裁剪、摘要和来源标记，并输出可测试的上下文清单和预算报告。

### 6.5 Store 协议

定义并提供内存与 PostgreSQL 两组实现：

- `RunStore`
- `EventStore`
- `MemoryStore`
- `ApprovalStore`
- `KnowledgeBase`
- `CheckpointStore`

默认离线测试使用内存实现；集成模式使用 PostgreSQL、pgvector 和持久 checkpointer。

## 7. 核心数据模型

| 模型 | 关键职责 |
| --- | --- |
| `RunRecord` | 输入、Runtime、状态、答案、错误、时间、所有者、幂等键 |
| `StoredRunEvent` | Run ID、单调递增序号、类型、数据、时间 |
| `ToolExecution` | 工具调用 ID、参数摘要、幂等键、状态、结果摘要 |
| `ApprovalRequest` | 身份、Run、工具、完整参数摘要、有效期、单次状态 |
| `ConversationMessage` | 会话顺序、角色、内容、工具和提供方引用 |
| `MemoryFact` | 所有者、作用域、来源、值、版本、审批状态 |
| `UsageRecord` | 模型、输入/输出 Token、耗时、估算成本 |
| `KnowledgeDocument` | 文档元数据、来源、内容摘要和更新时间 |
| `KnowledgeChunk` | 切片内容、顺序、向量、引用信息 |

原始 API Key、访问 Token 和无界工具输出不得写入上述模型或普通日志。

## 8. Run 状态机

```text
queued
  `-- running
       |-- waiting_approval -- approved --> running
       |-- completed
       |-- failed
       `-- cancelled
```

约束如下：

- 状态转换由服务端事务校验。
- 终态不能重新进入运行态。
- 审批拒绝转换为可解释终态或受控分支，不伪装成系统错误。
- `waiting_approval` 重启后保持暂停。
- `cancelled` 后禁止继续提交模型或工具副作用。

## 9. 主要数据流

### 9.1 创建和执行 Run

1. API 校验身份、会话、输入和 `Idempotency-Key`。
2. 创建 `RunRecord(status=queued)` 和首个持久事件。
3. 返回 HTTP 202 与 `run_id`。
4. `RunCoordinator` 选择 Runtime。
5. `ContextAssembler` 组合消息、记忆、RAG、Skill 和 Token 预算。
6. Runtime 执行模型、工具或工作流。
7. `emit()` 先写 `StoredRunEvent`，再通知流式消费者。
8. Observer 保存耗时、usage、成本和错误分类。
9. 最终答案、引用与终态写入数据库。

### 9.2 审批和恢复

1. 高风险工具创建服务端审批记录。
2. LangGraph 保存 checkpoint，Run 进入 `waiting_approval`。
3. 用户提交审批决定。
4. 服务端验证身份、完整参数摘要、有效期和单次使用状态。
5. 批准后通过 checkpoint 恢复；拒绝后进入受控替代分支或终态。

### 9.3 SSE 断线续传

1. 前端保存最后收到的事件序号。
2. 使用 `GET /api/runs/{id}/events?after=<sequence>` 重新连接。
3. 服务端先从 EventStore 补发历史事件，再等待新事件。
4. SSE 定期发送心跳，不把心跳计入业务序号。
5. 页面刷新后先读取 Run 快照，再从最后序号续传。

### 9.4 进程重启恢复

`RunRecoveryService` 在应用启动时扫描：

- `queued`：重新调度。
- `running`：从 checkpoint 恢复；无法安全恢复时写入明确失败原因。
- `waiting_approval`：保持暂停。
- 终态：不重复执行。

副作用工具只有在持久幂等键能证明安全时才允许恢复执行。

## 10. API 演进

新增接口：

- `POST /api/runs`：创建幂等 Run，返回 202。
- `GET /api/runs/{run_id}`：读取 Run 快照。
- `GET /api/runs/{run_id}/events`：按序号读取实时 SSE。
- `POST /api/runs/{run_id}/approvals`：提交服务端绑定的审批决定。
- `POST /api/runs/{run_id}/cancel`：持久取消。
- `GET /api/sessions/{session_id}/runs`：恢复会话运行列表。

迁移期保留旧接口并通过兼容测试确保现有学习步骤可运行。旧接口只有在 Vue、新文档和自动化测试全部迁移后才能标记为 `superseded`。

## 11. 前端设计

继续沿用 Vue 3、TypeScript、Composition API、`agentApi.ts` 和 `useAgentDesk.ts`：

- 不提前引入 Pinia或新 UI 库。
- `AgentEvent` 改为判别联合类型，包含事件序号、时间、usage、evidence 和 approval 数据。
- 创建 Run 后保存 `run_id` 和最后事件序号。
- Fetch Streaming 负责自定义鉴权头和 `after` 续传。
- `answer`、`evidence`、`critique` 和 `usage` 全部来自同一个 Run。
- 删除流结束后调用独立 Research API 覆盖答案的双链路。
- 增加连接、运行、等待审批、重连、完成、失败和取消状态。

## 12. 错误处理

所有运行时和集成层转换为统一错误模型：

| 字段 | 含义 |
| --- | --- |
| `code` | 稳定错误码 |
| `category` | validation/auth/provider/tool/mcp/storage/workflow/security |
| `retryable` | 是否允许重试 |
| `public_message` | 可返回用户的信息 |
| `internal_ref` | 服务端诊断引用 |
| `step` | 失败步骤 |

重试规则：

- 模型限流和临时网络故障使用有上限的指数退避与抖动。
- 参数、鉴权、权限和审批拒绝不重试。
- 只读幂等工具允许有限重试。
- 有副作用工具没有持久幂等键时不自动重试。
- MCP 重连不等于重放未知状态的工具调用。
- 每次重试都产生事件和观测记录。

超时与取消：

- Run 总超时和模型、MCP、数据库、工具步骤超时分离。
- 用户取消写入持久状态，运行时和工具边界前后都检查取消。
- 代码 Agent 流式读取并限制输出，超时后清理整个子进程树并记录结果。

## 13. 安全设计

### 13.1 审批绑定

审批必须绑定 principal、session、run、tool call ID、工具名、完整参数摘要、目标 URL/路径、浏览器完整计划摘要、有效期和单次使用状态。客户端不能通过裸 `approved=true` 绕过服务端记录。

### 13.2 Prompt、RAG、MCP 和记忆

- 检索内容、MCP 响应、网页文本和图片文字均为不可信输入。
- 外部内容不能覆盖系统权限、审批和数据边界。
- 长期记忆保存来源、所有者、版本和审批状态。
- 用户可以读取、纠正和删除自己的记忆。
- 模型推测不自动写入长期记忆。

### 13.3 浏览器 Agent

真实浏览器接入前必须：

- 拒绝 loopback、私网、链路本地、保留地址和云元数据地址。
- DNS 解析后复核，防止重绑定。
- 每次重定向重新验证目标。
- 限制下载、上传、弹窗、新窗口和跨域导航。
- 审批绑定完整 URL 与计划摘要。

### 13.4 代码 Agent

- 固定工作区、命令白名单、固定环境和默认禁网。
- 限制 CPU、内存、进程数、输出和时间。
- 写操作需要精确审批。
- 应用级 Harness 与 OS/容器沙箱必须明确区分。

### 13.5 成本与数据保护

- 在线 Run 设置 Token、调用次数和费用预算。
- 达到预算后进入可诊断失败。
- 密钥仅由运行环境注入。
- 日志默认脱敏，Trace 中敏感字段使用摘要或关闭采集。
- 在线验证必须标记 `online/cost-incurring`。

## 14. 测试与验收

| 层级 | 内容 | 默认策略 |
| --- | --- | --- |
| 单元测试 | Domain、状态转换、工具、上下文预算 | 必跑 |
| 契约测试 | Manual/SDK/LangGraph 统一输出契约 | 必跑 |
| MCP 端到端 | 启动真实 STDIO Server、发现、调用和错误 | 必跑 |
| 数据库集成 | PostgreSQL、pgvector、迁移、恢复、幂等 | Docker 可用时必跑 |
| 前端单元测试 | SSE 分帧、状态机、重连、取消 | 必跑 |
| 浏览器 E2E | 页面、审批、断线恢复 | CI 或 Docker 环境 |
| 安全测试 | 越权、注入、SSRF、路径、重复副作用 | 必跑 |
| 离线评测 | 固定数据集、引用和回归 | 必跑 |
| 在线冒烟 | OpenAI 模型、usage、工具流 | 显式启用 |
| Docker 验收 | 镜像、健康、Nginx SSE | Docker 可用时必跑 |

每个里程碑必须同时具备代码、自动测试、跟练步骤、排错说明、概念题、实操题、工作场景题、速查表、费曼任务、精确验收命令和实际验证证据。

## 15. 里程碑

### M8 真实模型与运行时对照

- 建立 Settings、ApplicationContainer、异步 AgentRuntime 和持久事件扩展缝。
- 实现 ManualRuntime 和 OpenAIAgentsRuntime。
- 为 Manual、Agents SDK 和现有 LangGraph 适配边界建立相同工具、输入和结果契约；M8 只完成运行时兼容基础，LangGraph 的持久化、审批恢复和重规划由 M10 验收。
- 增加最小 LangChain 对照实验，说明抽象收益和成本。
- 默认离线测试；在线冒烟显式启用。

### M9 MCP Client 与 Skill Runtime

- 建立 Python MCP Client。
- 与现有 TypeScript/Python Server 完成真实发现和调用。
- 处理连接、Schema、权限、超时和错误。
- 建立只读 Skill Catalog/Resolver 和触发评测。

### M10 LangGraph 持久工作流

- 引入 checkpointer、thread ID、interrupt 和 resume。
- 实现人工审批、失败诊断、动态重规划和恢复测试。
- 实现真实多 Agent 角色、handoff/manager 模式与单 Agent 对照评测。

### M11 上下文、记忆与真实 RAG

- 建立 PostgreSQL、迁移脚本和显式 SQL Store。
- 接通 pgvector 与真实 Embedding。
- 建立 ContextAssembler、Token 预算、裁剪和摘要。
- 将短期/长期记忆接入 Agent 上下文。
- 使用固定查询集评测检索与回答依据。

### M12 统一 Run 与实时 UI

- Agent、RAG、记忆、工具和审批统一到同一 Run。
- 建立持久事件、真 SSE、心跳、续传和恢复。
- Vue 删除双链路，显示步骤、工具、引用、usage、成本和审批。
- 增加前端单元测试与浏览器 E2E。

### M13 生产工程闭环

- 增加 Trace/metrics sink、成本汇总、结构化错误和告警基础。
- 建立离线、数据库、前端、MCP、E2E 和 Docker CI 分层。
- Compose 增加 pgvector 集成配置和运行时密钥注入。
- 完成镜像、容器健康、Nginx SSE、基础压测和故障演练。

### M14 高级 Agent 作品集

- 使用真实浏览器自动化实现受控 Browser Agent。
- 使用 M8 模型适配器实现真实视觉输入流程。
- 保留原离线安全实验作为对照。
- 完成架构答辩、评测报告、延迟/成本记录、故障复盘和演示脚本。

## 16. 连续性文档

正式实施前建立：

```text
ai-agent-demo/
|-- AGENTS.md
`-- docs/
    |-- implementation-plan.md
    |-- syllabus-map.md
    |-- stages/08-real-model-runtimes.md ... 14-advanced-capstone.md
    `-- continuity/
        |-- README.md
        |-- status.md
        |-- verification-log.md
        |-- known-issues.md
        |-- decisions/ADR-*.md
        `-- handoffs/YYYY-MM-DD-HHmm-<task>.md
```

职责：

- `AGENTS.md`：未来执行者的强制恢复和收尾规则。
- `implementation-plan.md`：稳定计划、依赖和不可变任务 ID。
- `status.md`：唯一当前实施状态。
- `verification-log.md`：只追加实际执行证据。
- `known-issues.md`：稳定编号的问题和风险。
- `ADR`：不可变架构决策；只能由新 ADR 取代。
- `handoffs`：每次中断或结束的不可变交接快照。
- `stages`：学习者跟练、排错和考核内容。

任务状态固定为：

```text
planned
in_progress
blocked
code_complete
verified
accepted
superseded
```

只有代码、测试、文档和验证证据全部满足，任务才能进入 `verified`。

### 16.1 强制恢复顺序

1. 读取 `AGENTS.md`。
2. 读取 `docs/continuity/README.md`。
3. 读取 `status.md` 当前任务。
4. 查阅 `implementation-plan.md` 对应任务验收条件。
5. 阅读关联 ADR、最新 handoff 和最近验证记录。
6. 检查实际文件和工作区状态。
7. 重跑当前任务的最小验证命令。
8. 从 handoff 的下一条原子动作继续。

冲突优先级：

```text
实际代码与测试证据
  > verification-log
  > status
  > implementation-plan
  > 普通说明文档
```

### 16.2 每次工作收尾顺序

1. 运行验证。
2. 追加 verification log。
3. 有架构变化时新增 ADR。
4. 更新 known issues。
5. 更新 status 并引用验证 ID。
6. 最后创建 handoff，写明修改文件、失败尝试、未验证范围和下一条精确命令。

### 16.3 Git 状态

2026-07-16 经用户明确授权，项目已初始化本地 Git `main` 分支，基线提交为 `9a54ebe`。后续验证记录使用实际 commit ID；在用户提供远程地址前，不配置远程仓库，也不执行 push。

## 17. 风险与缓解

| 风险 | 缓解措施 |
| --- | --- |
| 在线模型非确定性导致测试不稳定 | 离线契约测试为默认门禁，在线测试单独标记 |
| M8 直接耦合 SDK 导致后续重写 | 先建立 AgentRuntime 和持久事件协议 |
| 副作用在断线或重启后重复执行 | 持久幂等键、状态事务和审批单次使用 |
| 内存与 PostgreSQL 行为漂移 | 两种 Store 运行同一套契约测试 |
| 文档状态重复导致冲突 | status 是唯一易变状态源，其他文档只引用任务 ID |
| 浏览器引入 SSRF 和越权 | DNS/IP/重定向复核、完整计划审批和网络限制 |
| 代码 Agent 输出或子进程耗尽资源 | 流式有界读取、进程树清理和资源限制 |
| 依赖和模型版本随时间漂移 | 实施时查询官方文档、固定版本并记录验证日期 |

## 18. 迁移顺序

1. 先落盘连续性文档和 M8–M14 稳定计划。
2. 建立 M8 异步 Runtime、持久事件模型和 Store 协议。
3. 保持旧 API 全部回归通过。
4. 接入真实模型、MCP、LangGraph 和 PostgreSQL。
5. 新建持久 Run API，再迁移 Vue。
6. 新旧链路并行通过契约测试后，才标记旧链路为 superseded。
7. 最后完成生产工程和高级 Agent 作品集。

## 19. 通用完成定义

任一任务只有同时满足以下条件才可标记 `verified`：

- 实现符合本设计及项目编码规约。
- 相关单元、契约、集成或 E2E 测试通过。
- 未破坏既有回归基线。
- 跟练和排错文档已更新。
- 精确命令、退出码、通过数、跳过项和警告已写入验证日志。
- 已知限制已进入 known issues。
- status 指向下一条精确任务。
- handoff 能让新模型在不重新推断架构的情况下继续。

## 20. 已确认决策摘要

1. 采用现有项目上的渐进式补齐方案。
2. 使用 M8–M14 衔接现有 M0–M7。
3. Mock 为默认离线路径，OpenAI 在线验证显式启用。
4. 三种运行时共享领域契约，LangGraph 承担持久主工作流。
5. 使用 PostgreSQL + pgvector 作为集成持久化目标。
6. SSE 基于持久事件和序号续传。
7. Vue 保持现有 Composition API 架构，暂不增加状态库和 UI 库。
8. 安全审批绑定完整副作用计划和参数摘要。
9. 先落盘计划、状态、验证、决策和交接规则，再修改业务代码。
10. 本地 Git 已按用户授权初始化；远程同步和付费在线调用仍需显式授权。

## 21. 参考基线

- OpenAI Agents SDK：<https://openai.github.io/openai-agents-python/>
- MCP 官方文档：<https://modelcontextprotocol.io/docs/>
- LangGraph Persistence：<https://docs.langchain.com/oss/python/langgraph/persistence>
- LangGraph Interrupts：<https://docs.langchain.com/oss/python/langgraph/interrupts>
- pgvector：<https://github.com/pgvector/pgvector>
- OWASP Agentic Security Initiative：<https://genai.owasp.org/initiatives/agentic-security-initiative/>
