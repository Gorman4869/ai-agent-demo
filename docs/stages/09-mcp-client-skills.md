# M9：MCP Client 与 Agent Skill

> 工程状态只查看 `../continuity/status.md`。本文件的命令在进入 verification log 前均为计划命令。

## 本阶段目标

补齐 MCP Client 的真实协议闭环，并把 Skill 建成只读、可验证、不可任意执行的上下文能力。

- 时间预算：1 周，约 10–16 小时。
- 任务：M9-T1 至 M9-T6。
- 工作映射：IDE/Agent Host 工具接入、企业工具目录、可复用任务说明。

## 20% 关键知识

| 类型 | 知识点 | 工作场景 | 学到什么程度 | 验证任务 |
| --- | --- | --- | --- | --- |
| 必学 | Host、Client、Server | 多工具 Agent | 能画清连接和责任 | M9-T1–T3 |
| 必学 | initialize/list_tools/call_tool | 协议互操作 | 真实 STDIO 调用 | M9-T3 |
| 高频 | Schema、命名空间、权限过滤 | 多 Server 冲突 | 能安全映射 ToolRegistry | M9-T2 |
| 高频 | Skill Catalog 与 Resolver | 团队操作手册 | 能受控加载和触发 | M9-T4、M9-T5 |
| 易错 | 直接 import Server 函数冒充 E2E | 测试 | 能识别伪协议测试 | M9-T3 |
| 易错 | 把 roots 当安全沙箱 | 文件型 MCP | 能解释其只是协调边界 | 安全场景题 |

## 跟练顺序

1. 建立 MCP Client 配置和 lifespan，故意让 Server 启动失败并检查清理。
2. 启动现有 TypeScript STDIO Server，完成初始化、发现、调用、非法参数和关闭。
3. 把发现工具映射为带命名空间、Schema、RBAC 和超时的共同 ToolDefinition。
4. 加载 `research-summary` Skill，覆盖显式触发、不触发、越界引用和错误元数据。
5. 运行固定评测，对比 Function Calling、MCP 和 Skill 的职责。

## M9-T1 最小纵切：Client 配置与生命周期

默认 `AI_AGENT_MCP_SERVERS` 为空，应用不启动进程。需要观察真实本地协议初始化时，服务端操作者可选择代码目录中已经登记的 `python-knowledge` ID；请求、模型和工具参数都不能提供命令、参数或工作目录。

```powershell
$env:AI_AGENT_MCP_SERVERS='python-knowledge'
$env:AI_AGENT_MCP_STARTUP_TIMEOUT_MS='5000'
.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_mcp_client_lifecycle.McpFastApiLifespanTest -v
Remove-Item Env:AI_AGENT_MCP_SERVERS
Remove-Item Env:AI_AGENT_MCP_STARTUP_TIMEOUT_MS
```

真实路径是 `FastAPI lifespan -> McpClientManager -> stdio_client -> ClientSession.initialize()`。Server 的 worker 在同一 Task 中进入和退出 SDK context manager；启动超时或取消只发停止信号并等待清理。稳定诊断包括 `server_not_allowed`、`process_unavailable`、`startup_timeout` 和 `protocol_error`，不包含原始命令、stderr 或异常文本。

本纵切只证明本地 STDIO 连接、初始化和关闭，尚未实现 `list_tools`、`call_tool`、Schema/RBAC 映射或 TypeScript Server 端到端；这些分别由 M9-T2 和 M9-T3 验收。

## M9-T2 最小纵切：发现、可信映射与调用

`McpClientManager.discover_tool_definitions()` 在拥有 SDK context 的连接 worker 中分页执行 `list_tools`，再按服务端维护的 `McpToolPolicy` 生成共同 `ToolDefinition`。远端 description、title、默认值和示例不进入模型提示；未列入策略的工具会被隔离，重复远端名称、缺失配置工具、非法 Schema 和跨 Server 本地名称冲突均稳定失败。

共同 Registry 继续负责参数校验、角色过滤和审批策略。handler 通过线程安全桥接回 Client owner loop，在原连接 worker 中执行 `call_tool`；调用有单独的 100–30000 ms 超时，不自动重试。结构化结果优先，文本回退、参数和结果均有大小与结构上限，远端错误和原始内容不会进入公共 `ToolResult`。

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_tool_adapter -v
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_tool_adapter backend.tests.test_mcp_client_lifecycle backend.tests.test_settings backend.tests.test_tool_security backend.tests.test_manual_agent_loop backend.tests.test_runtime_comparison backend.tests.test_openai_agents_runtime backend.tests.test_framework_runtimes backend.tests.test_container backend.tests.test_api -q
```

第一条命令实际启动本地 Python MCP STDIO Server，覆盖发现、调用、角色拒绝、超时、远端失败、结果上限、allowlist 和命名冲突；第二条验证相同 `ToolDefinition` 能被 Manual、Agents SDK 与 LangGraph 共同边界使用。该证据是本地协议 E3，不是 M9-T3 的 TypeScript Server E2E，也不证明断线重连、副作用幂等或生产部署。

## 计划验证命令

```powershell
npm.cmd run build --prefix mcp-servers/knowledge-server
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_mcp_client_e2e -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_mcp_tool_adapter -v
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_skill_catalog backend.tests.test_skill_resolver -v
```

## 常见错误与排查

| 现象 | 原因 | 排查 |
| --- | --- | --- |
| Client 一直等待 | Server 未按 STDIO 协议启动或 stdout 被日志污染 | 先单独构建，再检查 stderr/stdout |
| 工具发现但不能调用 | Schema 规范化或命名空间错误 | 保存发现结果，逐字段对照 |
| 断线后副作用重复 | Client 自动重放未知状态调用 | 关闭自动重放，查询幂等记录 |
| Skill 在 Windows 读取失败 | UTF-8 模式未启用 | 使用 UTF-8 读取并固定验证命令 |
| Skill 能访问仓库外 | 路径解析或符号链接验证缺失 | 比较解析后路径与固定根目录 |

## 自测

1. 画出 Host、Client、Server，并说明一个 Host 为什么可能有多个 Client。
2. 新增一个只读 MCP 工具并完成协议级 E2E。
3. 解释 MCP Tool 与本地 Function Calling 的共同点和差异。
4. 设计一个断线后不能安全重放的工具案例。
5. 说明 Skill 为什么不能天然获得代码执行权。

## 费曼复述

用“插座协议”和“岗位操作手册”分别解释 MCP 与 Skill；必须说明二者都不是安全边界。

## 官方资源

- MCP 架构：<https://modelcontextprotocol.io/docs/learn/architecture>
- MCP Client 教程：<https://modelcontextprotocol.io/docs/develop/build-client>
- MCP Client 概念：<https://modelcontextprotocol.io/docs/learn/client-concepts>
- MCP Client 最佳实践：<https://modelcontextprotocol.io/docs/develop/clients/client-best-practices>
