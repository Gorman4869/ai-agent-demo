# 学习进度与复盘

> 本文件只记录学习者个人掌握情况，不代表代码或工程实施状态，也不会由自动化测试代填。工程状态以[连续性状态页](continuity/status.md)为唯一来源。

## 基础诊断

- [ ] 我能用 Python 定义类型、处理 JSON、异常和异步函数。
- [ ] 我能解释 HTTP、SSE 与 WebSocket 的区别。
- [ ] 我能解释 LLM 为什么不能直接执行本地函数。
- [ ] 我能运行标准库单元测试并看懂失败信息。
- [ ] 我能说明环境变量与源码配置的安全差异。

不会的项目不用先补完；在对应周次回填即可。

## 周进度

| 周 | 开始 | 完成 | 测试证据 | 最大问题 | 可复用沉淀 |
| --- | --- | --- | --- | --- | --- |
| 1 |  |  |  |  |  |
| 2 |  |  |  |  |  |
| 3 |  |  |  |  |  |
| 4 |  |  |  |  |  |
| 5 |  |  |  |  |  |
| 6 |  |  |  |  |  |
| 7 |  |  |  |  |  |
| 8 |  |  |  |  |  |
| 9 |  |  |  |  |  |
| 10 |  |  |  |  |  |
| 11 |  |  |  |  |  |
| 12 |  |  |  |  |  |

## M8–M14 生产补齐训练

| 补齐周 | 里程碑 | 开始 | 完成 | 独立重做证据 | 最大问题 | 可复用沉淀 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | M8 Runtime 基础 |  |  |  |  |  |
| 2 | M8 真实模型与框架对照 |  |  |  |  |  |
| 3 | M9 MCP Client 与 Skill |  |  |  |  |  |
| 4 | M10 Checkpoint 与审批 |  |  |  |  |  |
| 5 | M10 重规划与多 Agent |  |  |  |  |  |
| 6 | M11 PostgreSQL 与 pgvector |  |  |  |  |  |
| 7 | M11 上下文与记忆 |  |  |  |  |  |
| 8 | M11 RAG 评测 |  |  |  |  |  |
| 9 | M12 持久 Run 与 SSE |  |  |  |  |  |
| 10 | M12 Vue 恢复与 E2E |  |  |  |  |  |
| 11 | M13 观测、错误与 CI |  |  |  |  |  |
| 12 | M13 Docker、压测与安全 |  |  |  |  |  |
| 13 | M14 浏览器与多模态 |  |  |  |  |  |
| 14 | M14 作品集与最终审计 |  |  |  |  |  |

## 单次复盘

- 本次可运行产物：`list_concepts` MCP 工具及其直接调用测试；查询会话 API 的服务层查询、`GET /api/sessions/{session_id}` 路由，以及已存在会话 200、不存在会话 404、查询响应不返回 `access_token` 的测试。已验证 M2 框架测试 3 项、手写 Agent Loop 测试 10 项通过；本阶段收尾时学习者已运行并确认完整 API 测试类通过，`git diff --check` 通过。
- 我能独立重做的部分：区分本地函数测试与 MCP 协议测试；说明 `initialize → list_tools → call_tool`；区分 Tool、Resource、Prompt 的发现与使用链路；理解 TypeScript `server.registerTool`、无参 `inputSchema: {}` 和 `content` 返回结构；说明 Skill 是组合 Prompt、Resource、Tool 的可复用业务 SOP，不是第四种 MCP 协议能力、不直接提供 `call_tool`；按用户意图选择匹配的 Skill，而不是按某个 Tool 名称机械选择；说明 Skill 只约束 Agent 的执行流程，Server 才是权限与业务校验的最终执行者；能读懂真实 `SKILL.md` 中的触发条件、Workflow、限制条件和 Default Output，并说明动态数据由 Tool 获取、制度正文由 Resource 提供、表达模板可由多个 Skill 复用，少用细则放在 `references/` 按需读取；说明 FastAPI 负责 HTTP Schema、鉴权和响应映射，业务服务不依赖 HTTP，Agents SDK 只管理通用 Agent 运行机制且不会自动授予 Tool，LangGraph 用 State、节点和边控制固定分支，Tool 仍独立校验参数与权限；能把会话查询的“存在且有权才返回，否则返回 `None`”放在服务层，将统一 404 映射放在路由层，并用测试锁定令牌不会由查询接口重新发放；能设计真实模型测试的双开关策略：同时有 `RUN_ONLINE_MODEL_TESTS=1` 与 `OPENAI_API_KEY` 才执行，否则跳过。
- 仍需参考的部分：TypeScript MCP Server 中无参 `list_concepts` 的完整实现与测试写法；Skill 被选中后如何作为 Agent 当前任务的工作说明使用；三种运行方式在完整业务任务中的选型与组合。
- 失败现象与根因：无。已知直接调用 `list_concepts()` 不能证明 `@mcp.tool()` 注册有效，原因是它绕过了 MCP Client 的发现与协议调用链。
- 下次先检查什么：先确认 Git 工作区状态，再阅读当前课程文件；M2 已完成，从第 4 周的“同一业务场景应选择手写 Loop、Agents SDK 还是 LangGraph，以及何时组合使用”继续。
- 能迁移到哪个工作场景：为前端业务助手设计稳定的工具契约、只读知识资源、标准提示模板，并将权限校验保留在 Server。
