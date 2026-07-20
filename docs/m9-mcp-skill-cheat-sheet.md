# M9 MCP、Function Calling 与 Skill 一页速查表

## 一句话定义

- Function Calling：模型提出符合 Schema 的结构化调用，Host 决定是否执行。
- MCP：Host 中的 Client 用统一协议发现并调用独立 Server 的能力。
- Skill：应用按任务加载的受控说明文本，不是工具、插件或权限。

## 一条主链

```text
Host / ApplicationContainer
  -> McpClientManager
  -> connection worker（同一 Task 持有 SDK context）
  -> STDIO + ClientSession.initialize()
  -> list_tools
  -> McpToolPolicy 可信映射
  -> shared ToolDefinition / ToolRegistry
  -> call_tool
  -> 有界 ToolResult
```

Skill 走另一条输入链：

```text
fixed skill root
  -> SkillCatalog（只读、严格 frontmatter、路径检查）
  -> SkillResolver（显式/全词元触发）
  -> SkillContextBuilder（最多 4 个、24,000 UTF-8 字节）
  -> RuntimeRequest.prompt_context（最多 32,000 UTF-8 字节）
  -> system message / agent instructions
```

## 三者怎么选

| 需求 | 使用 | 不要误写成 |
| --- | --- | --- |
| 让模型按 JSON Schema 提议参数 | Function Calling | 工具已经执行 |
| 跨进程、跨语言发现和调用工具 | MCP | 权限系统或 OS 沙箱 |
| 为特定任务加载团队操作说明 | Skill | 可执行插件或管理员授权 |

## 信任边界

- request/model 只能选择服务端登记的 Server ID，不能提供 command、args、cwd 或 root。
- 远端 name/description/Schema/result 都是不可信输入；本地 `McpToolPolicy` 决定公开契约。
- 共同 Registry 在执行前重复做角色、审批和参数校验。
- MCP 调用有独立超时且不自动重试；结果、页数、游标、深度、节点数和字节均受限。
- Skill 只读 Markdown；不执行 `agents/`、Python、shell 或任意文件。
- Skill 不能构造身份、角色、审批、工具或 Schema，原始 user input 保持不变。
- roots 只是 Client 声明的协调范围，不是 OS 权限、容器或文件沙箱。

## 证据等级

| 等级 | M9 示例 | 上限 |
| --- | --- | --- |
| E1 | import、Settings、对象构造 | 不证明进程或协议执行 |
| E2 | fake session、纯映射测试 | 不证明真实 STDIO |
| E3 | 本地 Python/Node STDIO + Runtime 集成 | 不证明远程、跨平台或生产 |
| E4 | 经单独设计和授权的远程/生产验证 | 只证明指定环境和当次执行 |

## 稳定错误定位

| 层 | 典型错误 | 先查 |
| --- | --- | --- |
| Catalog | `server_not_allowed`、`process_unavailable` | Server ID、固定 command/cwd |
| Lifecycle | `startup_timeout`、`protocol_error` | build、stdout/stderr、initialize |
| Discovery | Schema、重复或缺失工具错误 | page/cursor、policy、Schema 子集 |
| Registry | `permission_denied`、`approval_required`、`invalid_arguments` | roles、绑定审批、参数 |
| Remote call | `tool_not_allowed`、`remote_tool_error` | allowlist、timeout、结果上限 |
| Skill | Catalog/Resolver 稳定 code、`skill_context_unavailable` | UTF-8、路径、触发、上下文上限 |

排查顺序：服务端目录 -> 进程/transport -> initialize -> discovery/Schema -> policy/Registry -> call/result -> Skill Catalog/Resolver -> Runtime context。

## 最小命令

```powershell
npm.cmd run build --prefix mcp-servers/knowledge-server
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_lifecycle backend.tests.test_mcp_tool_adapter backend.tests.test_mcp_client_e2e backend.tests.test_skill_catalog backend.tests.test_skill_context -v
.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.skill_context
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

## 五问自检

1. 真实 Node 进程和 JSON-RPC 在哪条命令中执行？
2. 远端工具为何必须映射回本地可信策略？
3. Function Calling、MCP、Skill 各自不负责什么？
4. roots 为什么不能替代 OS 权限和服务端路径校验？
5. Skill 的字节/Token 启发式为什么不是 Provider usage 或账单？
