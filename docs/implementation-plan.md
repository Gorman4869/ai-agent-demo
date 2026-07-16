# AI Agent 学习项目实施计划

## 当前实现状态（2026-07-15）

M0–M7 的项目代码、阶段跟练、测试、部署配置、高级安全实验和最终答辩材料均已落盘。`scripts/verify.ps1` 可统一执行后端回归、代码 Agent Demo、依赖检查、Vue/MCP 构建与 Compose 配置检查。Docker Engine 未启动时，镜像构建和容器健康只能保留为待执行的环境验收；`docs/progress.md` 中的个人学习勾选仍需学习者在独立重做后填写，不能由自动化测试代替。

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

## 首轮实施批次

第一批只完成 M0 与 M1，避免在基础接口尚未稳定时同时生成前端、数据库和部署代码：

1. 创建学习导航、12 周计划、大纲映射、进度表、题库、速查表和费曼模板。
2. 创建 Python/Node.js 前置检查与基础实验。
3. 定义 Agent 领域类型、Mock 模型、工具注册表和手写循环。
4. 编写标准库单元测试和第一阶段跟练文档。
5. 运行环境检查与测试，记录尚未验证的后续命令。
