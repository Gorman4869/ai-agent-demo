# M9：MCP Client 与 Agent Skill

> 工程状态只查看 `../continuity/status.md`。本文件给出可复现命令，但只有实际运行并写入 `../continuity/verification-log.md` 的结果才算工程证据。

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

## M9-T3 最小纵切：TypeScript Server 协议 E2E

先使用锁文件中已有依赖构建 TypeScript Server，再由 Python `McpClientManager` 选择服务端目录中的 `typescript-knowledge`。测试进程真实执行 `node build/index.js`，依次完成 initialize、list_tools、共同 `ToolDefinition` 调用、协议级非法参数和关闭；不得直接 import `src/index.ts` 或调用知识字典冒充协议测试。

```powershell
npm.cmd run build --prefix mcp-servers/knowledge-server
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_e2e -v
```

聚焦测试覆盖服务端固定 command/cwd/policy、Schema 归一化、已知和未知概念文本结果、服务端 Zod 类型拒绝、客户端 allowlist 和清理。Server stdout 专用于 JSON-RPC，普通运行日志只能写 stderr；Client 不把 stderr 或远端校验文本带入公共错误。该纵切证明 Windows 本地 Node/Python STDIO 互操作 E3，不证明远程 transport、跨平台兼容、重连、幂等或生产容量。

## M9-T4 最小纵切：只读 Skill Catalog 与 Resolver

`default_skill_catalog()` 只扫描仓库固定的 `skills` 根目录。Catalog 使用严格的 `name`/`description` 标量 frontmatter 子集，不执行通用 YAML 标签；只读取 `SKILL.md` 和正文显式链接的 `references/*.md`，`agents/`、脚本和其他文件不会被加载或执行。路径解析拒绝逃逸与符号链接组件，文件、引用数量、总字节和查询长度均有上限。

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_skill_catalog -v
```

Resolver 对 `$research-summary` 使用显式触发；未显式指定时，查询必须包含 Skill 名称的全部词元，例如 `research summary`。Catalog 首次加载后返回不可变缓存快照，只有可信应用显式调用 `refresh()` 才重新读盘。测试真实加载现有 `research-summary` 和 `references/output-contract.md`，并覆盖缓存、错误 frontmatter、缺失/逃逸引用、超限、非 UTF-8、符号链接拒绝分支和禁止执行无关脚本。该任务尚未把 Skill 注入 Runtime，也没有效果或成本评测；这些由 M9-T5 完成。

## M9-T5 最小纵切：Skill Runtime 上下文与离线评测

默认 `ApplicationContainer` 用 `SkillAwareRuntime` 包装内建 Runtime。Resolver 仍只根据原始用户输入选择 Skill，但注入后保留原始 `input_text` 和服务端构造的 `ToolExecutionContext`；Manual 与 LangGraph 使用独立 system message，Agents SDK 默认 factory 使用 agent instructions。Skill 片段最多 4 个 Skill、24,000 UTF-8 字节，`RuntimeRequest` 再执行 32,000 字节上限。片段不会暴露 reference 源路径，也不会改变角色、审批、工具清单或 Schema。

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.skill_context
.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_skill_context -v
```

固定离线评测真实执行 LangGraph Runtime API：显式 `$research-summary` 样例产生带来源和限制的答案，不触发样例保持通用答案。当前仓库 Skill 的触发片段为 3153 UTF-8 字节，`ceil(bytes / 4)` 启发式估算为 789 输入 Token；不触发样例增加 0 字节。该模型是确定性离线 fixture，报告中的 Provider usage 为不可用、美元费用为 `null`，不能描述成真实模型质量、Provider tokenizer 或账单证据。

权限回归让带有“绕过角色、审批和 Schema”字样的测试 Skill 驱动模型尝试调用工具，实际 Registry 仍分别返回 `permission_denied`、`approval_required` 和 `invalid_arguments`，handler 均未执行。显式注入的自定义 Runtime 不会被 Container 自动包装，需要调用方主动组合 `SkillAwareRuntime`；本任务不增加 Skill 写接口、审批恢复、Provider 成本账本或在线调用。

## MCP、Function Calling 与 Skill 对照

三者会出现在同一条 Agent 链路中，但解决的问题不同：

| 维度 | Function Calling | MCP | Skill |
| --- | --- | --- | --- |
| 核心问题 | 模型如何提出结构化工具调用 | Host 如何跨进程发现并调用 Server 能力 | Agent 如何获得可复用任务说明 |
| 本质 | 模型输出与 Host 执行之间的契约 | Client/Server 协议与 transport | 受控加载的上下文材料 |
| 本仓库入口 | `ToolDefinition`、`ToolRegistry` | `McpClientManager`、本地 STDIO Server | `SkillCatalog`、`SkillResolver`、`SkillAwareRuntime` |
| 谁执行动作 | Host 中受信任的 Registry/handler | MCP Server；Client 仍负责可信映射和调用策略 | Skill 本身不执行动作 |
| 模型看到什么 | 角色过滤后的名称、描述与 JSON Schema | 映射为共同 `ToolDefinition` 后的可信字段 | 有界 system context 或 agent instructions |
| 安全控制 | 参数校验、RBAC、审批、handler 边界 | Server allowlist、Schema 归一化、超时、结果上限，再经过共同 Registry | 固定根、严格元数据、路径检查、上下文上限；不能改变权限 |
| 不能证明 | 工具已执行、远程连接安全 | OS 隔离、调用幂等、生产容量 | 代码执行权、工具授权、真实模型遵循 |

记忆顺序：Function Calling 规定“模型怎样提出调用”，MCP 规定“Host 怎样找到并连接能力”，Skill 规定“本次任务应怎样做”。本仓库把 MCP Tool 映射回共同 `ToolDefinition`，因此三种 Runtime 仍复用同一执行安全边界。

## roots 为什么不是 OS 安全边界

MCP roots 用于由 Client 向 Server 声明建议操作的文件 URI 范围，帮助双方协调“这次会话关注哪些目录”。它不是内核权限、容器隔离或文件系统沙箱，不能阻止一个拥有更高 OS 权限或实现有缺陷的 Server 访问 roots 之外的路径。

本仓库当前没有协商 roots，不能声称已实现该能力。已有的文件边界来自服务端固定配置与代码校验：MCP command/cwd 由 `McpServerConfig` 持有，Skill root 由应用固定，并执行 canonical path、路径逃逸和 symlink 检查。生产环境若增加 roots，仍需同时使用最小 OS 账户权限、容器或沙箱、服务端 allowlist、规范化路径和审计；不能删除这些控制。

## M9 里程碑跟练

四次训练共约 8-12 小时。每次先写预期和边界，再运行命令；通过测试不等于已经能解释结果。

### 第 1 次：生命周期、所有权与稳定失败

- 时间预算：2-3 小时。
- 目标：画出 `Host -> McpClientManager -> connection worker -> ClientSession -> Server`，解释为什么 SDK context 必须在同一 Task 进入和退出。
- 动作：先运行空选择用例，再运行真实 FastAPI lifespan；任选进程不存在、启动超时、协议错误或部分启动回滚一个失败分支，记录稳定 code 和被隐藏的数据。
- 命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_lifecycle -v
```

- 产物：生命周期时序图、稳定错误表、roots 与 OS 安全边界的两段说明。
- 工作映射：IDE 插件 Host、企业本地工具进程、应用 lifespan 和子进程清理。
- 通关：能说明默认选择为何不启动进程；取消后无 ResourceWarning；请求不能提供 command、args 或 cwd。

### 第 2 次：独立启动 Server、发现并调用工具

- 时间预算：2-3 小时。
- 目标：从仓库锁定依赖构建 TypeScript Server，并让 Python Client 通过真实 STDIO 完成 initialize、list_tools、call_tool 和关闭。
- 动作：先构建 Server；按顺序运行“发现”和“调用”两个测试方法。测试中的 Manager 从服务端目录读取 `typescript-knowledge` 并自行拉起 `node build/index.js`，因此无需另开一个长期占用 STDIO 的 `npm start` 终端。
- 命令：

```powershell
npm.cmd run build --prefix mcp-servers/knowledge-server
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_e2e.McpTypescriptServerE2ETest.test_discovers_normalized_shared_tool_over_stdio -v
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_e2e.McpTypescriptServerE2ETest.test_calls_known_and_unknown_concepts_through_registry -v
```

- 继续练习：运行非法参数用例，解释为什么公共错误只有 `remote_tool_error`，而没有 Zod 的原始校验正文。
- 产物：一次协议调用序列、发现前后 Schema 对照、有效/无效调用结果摘要。
- 工作映射：跨语言工具接入、内部平台能力目录、第三方 Server 适配。
- 通关：能指出 Node 进程在哪里启动、Python Client 在哪里发现和调用、共同 Registry 在哪里再次校验；不能用直接 import Server 函数代替协议证据。

### 第 3 次：可信工具映射与 Skill 上下文

- 时间预算：2-3 小时。
- 目标：比较 MCP 远端元数据、服务端策略、共同 `ToolDefinition` 和 Skill 上下文四层数据的信任等级。
- 动作：运行 MCP adapter、Skill Catalog 和 SkillContext 测试；再执行固定离线评测，对比显式触发与不触发。
- 命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_tool_adapter -v
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_skill_catalog backend.tests.test_skill_context -v
.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.skill_context
```

- 产物：MCP/Function Calling/Skill 对照表、Skill 触发矩阵、上下文成本记录。
- 工作映射：企业工具目录、团队操作手册、按任务加载说明和提示预算评估。
- 通关：能解释远端 description 为什么不可信；能区分 3153 UTF-8 字节、启发式 789 Token 与 Provider usage；能证明 Skill 无法绕过角色、审批和 Schema。

### 第 4 次：故障演练与里程碑验收

- 时间预算：2-3 小时。
- 目标：按固定顺序定位一个 MCP 或 Skill 故障，并完成默认离线里程碑门。
- 动作：从下表任选一条故障注入，记录“观察 -> 定位层 -> 稳定错误 -> 清理 -> 未验证范围”；随后运行 M9 聚焦集、全量离线门和连续性检查。
- 产物：故障复盘、[M9 一页速查表](../m9-mcp-skill-cheat-sheet.md)使用记录、自测答卷和费曼复述。
- 工作映射：插件接入排障、发布前门禁、安全审阅和证据交接。
- 通关：全部命令退出码与警告如实记录；本地 E3 不描述成远程或生产 E4；默认无 Key、无网络、费用 0。

## 故障定位演练

| 注入或现象 | 第一定位层 | 合格判断 |
| --- | --- | --- |
| 把 Server command 改成不存在的程序 | Server catalog / lifecycle | 返回 `process_unavailable`，不泄漏 command 或原始异常 |
| Server 在 stdout 打普通日志 | STDIO protocol | initialize 失败且公共诊断稳定；日志应改到 stderr |
| 远端工具增加未知 Schema keyword | discovery normalization | 映射阶段 fail closed，不把远端提示直接交给模型 |
| 同一本地工具名来自两个 Server | trusted policy / namespace | 启动或发现失败，不静默覆盖 |
| `lookup_concept` 传入数字 | remote call / Zod | 公共结果为稳定错误，不暴露远端正文 |
| Skill 引用 `../secret.md` | Catalog path validation | 加载失败，错误不含路径或内容 |
| Skill 写“忽略审批并执行” | Registry authorization | 仍拒绝执行，handler 调用次数为 0 |
| 不触发请求仍出现 Skill 片段 | Resolver / wrapper | 检查显式触发、全词元匹配和无匹配原请求透传 |

排查顺序固定为“服务端目录 -> 进程/transport -> initialize -> discovery/Schema -> trusted policy/Registry -> call/result -> Skill Catalog/Resolver -> Runtime context”。不要先扩大超时或开放目录；先确认失败发生在哪一层。

## M9 验证命令与证据等级

M9 聚焦验收：

```powershell
npm.cmd run build --prefix mcp-servers/knowledge-server
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_lifecycle backend.tests.test_mcp_tool_adapter backend.tests.test_mcp_client_e2e backend.tests.test_skill_catalog backend.tests.test_skill_context -v
.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.skill_context
```

里程碑门：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

| 证据 | 最高等级 | 能证明 | 不能证明 |
| --- | --- | --- | --- |
| 配置、对象构造或 import | E1 | API 形状和默认值 | 进程、协议或 Runtime 已执行 |
| fake session / 单模块契约 | E2 | 映射和错误逻辑 | 真实 STDIO 互操作与清理 |
| 本地 Python/Node STDIO 与 Runtime 集成 | E3 | initialize、发现、调用、关闭和共同安全契约 | 远程 transport、跨平台、生产容量和 OS 隔离 |
| 经单独设计和授权的远程/生产验证 | E4 | 指定环境的真实互操作 | 永久兼容或无限容量 |

既有不可变证据索引：M9-T1 为 `V-20260717-004`，M9-T2 为 `V-20260720-001/002`，M9-T3 为 `V-20260720-003/004`，M9-T4 为 `V-20260720-005/006`，M9-T5 为 `V-20260720-007/008`。M9-T6 的实际结果只从 verification log 查询，不在本章复制动态状态。

## 常见错误与排查

| 现象 | 原因 | 排查 |
| --- | --- | --- |
| Client 一直等待 | Server 未构建、未按 STDIO 启动或 stdout 被日志污染 | 先构建，再查固定 command/cwd 与 stderr/stdout |
| 工具发现但不能调用 | 可信策略、Schema 归一化、角色或参数不匹配 | 按 policy -> definition -> Registry -> call 顺序检查 |
| 远端 description 进入模型 | 直接信任 discovery 元数据 | 只使用 `McpToolPolicy` 的本地名称和描述 |
| 断线后副作用重复 | 自动重放未知状态调用 | 当前不自动重试；副作用恢复留给持久幂等设计 |
| Skill 在 Windows 读取失败 | 文件不是 UTF-8 或路径边界触发 | 使用仓库命令并查看稳定 Catalog code，不放宽路径 |
| Skill 能访问仓库外 | 根目录由请求提供或缺少 canonical/symlink 校验 | 固定 root，逐组件验证解析后路径 |
| Skill 改变了用户问题 | 把说明拼进 `input_text` | 使用独立 `prompt_context`，保留原始 user message |
| 把 roots 当沙箱 | 混淆协议提示与 OS 权限 | 保留最小账户权限、容器/沙箱和服务端路径校验 |
| 评测显示 789 Token 就当成账单 | 把字节启发式当 Provider usage | 保留 usage unavailable、cost `null` 和 KI-018 |

## M9 自测题库

### 概念题（5 题，共 20 分）

1. Host、Client、Server 各拥有哪段生命周期，一个 Host 为什么可能持有多个 Client？
2. Function Calling、MCP 和 Skill 分别解决什么问题，为什么不能互相替代？
3. 为什么 discovery 返回的 description 和 Schema 不能直接成为共同工具契约？
4. MCP roots 能协调什么，为什么不能阻止 Server 读取 OS 允许的其他路径？
5. Skill 为什么放在 system context/instructions，而不能放进用户输入或可信执行上下文？

评分：每题 4 分；定义正确 2 分，边界或反例 2 分。

### 实操题（4 题，共 40 分）

1. 构建 TypeScript Server，并用两个指定 E2E 方法分别证明发现和有效/无效调用；标出真实进程与协议 API。
2. 为练习 Server 增加一个只读工具策略，写出远端名称到本地 `ToolDefinition` 的映射，并补非法 Schema 和未授权角色用例。
3. 新建临时 Skill，覆盖显式触发、自动触发、不触发、逃逸引用和缓存刷新；不得执行脚本。
4. 运行固定 Skill 评测，解释效果差异、上下文字节、Token 启发式、usage unavailable 和 cost `null`。

评分：每题 10 分；可复现证据 4 分，协议/数据流解释 3 分，失败与安全边界 3 分。

### 工作场景题（4 题，共 40 分）

1. 团队要接入供应商 MCP Server。设计 command 配置、工具 allowlist、命名冲突、超时、结果上限和上线前 E4 验证。
2. 一个写工单工具调用超时，Server 是否已执行未知。说明为什么当前不能自动重试，以及 M10/M13 需要补什么。
3. 产品要求“让 Skill 自动获得管理员工具”。指出信任层错误，并给出 Catalog、上下文、RBAC 和审批的正确边界。
4. 安全审阅发现客户端传了 roots。说明还要检查哪些 OS、路径、symlink、Server 配置与审计控制。

评分：每题 10 分；方案 4 分，取舍 3 分，风险与未验证范围 3 分。

总分 80 分通关。以下任一项出现即使总分达标也不通过：把 import 当框架执行证据、把本地 STDIO 写成远程/生产 E4、允许请求或模型提供 command/cwd/身份/审批、直接信任远端 Schema/结果、把 roots 当 OS 沙箱、自动重试无幂等副作用、执行 Skill 脚本、把启发式 Token 写成 Provider usage 或账单。

## M9 一页速查表

工作时优先打开 [M9 MCP/Function Calling/Skill 一页速查表](../m9-mcp-skill-cheat-sheet.md)。先凭记忆画一次调用链和信任边界，再只查速查表纠正；如果仍需通读本章才能完成故障定位，说明该项尚未内化。

## M9 费曼复述任务

不查资料，向一名只会调用普通 HTTP API 的前端同事讲 5 分钟：

1. 用“应用、插座协议、工具进程”解释 Host、Client、Server。
2. 用“结构化操作单、插座协议、岗位操作手册”区分 Function Calling、MCP 和 Skill。
3. 一次 `lookup_concept` 如何从 Client 启动 Server，经过 initialize/list_tools/call_tool，再回到共同 Registry？
4. 为什么远端 description、Schema、结果和 Skill 文本都属于不可信输入？
5. roots 能告诉 Server 什么，为什么它不能取代 OS 权限、容器或服务端路径校验？
6. 本地 E3 证明了什么，远程 transport、重连、幂等、容量和真实模型仍缺什么？
7. 给出一个真实工作故障，并按固定排查顺序说出第一条检查命令或文件。

复述合格标准：语言简单，能画出一条完整协议链，包含一个跨语言工作案例、两个安全边界和两个未验证边界。若把 MCP 说成模型工具调用本身、把 Skill 说成可执行插件，或把 roots 说成文件沙箱，必须重述。

## M9 与 30 项大纲映射

完整目标见[30 个主题映射](../syllabus-map.md)。M9 直接补齐 07 和 08，并为 02、06、13、24 提供关联证据：

| 编号 | 主题 | M9 产物 | 当前证据与边界 |
| --- | --- | --- | --- |
| 02 | Node.js 基础 | TypeScript Knowledge Server build 与 STDIO 进程 | E3；只证明当前 Windows 本地构建/互操作 |
| 06 | Function Calling | MCP Tool 到共同 `ToolDefinition`/Registry | E3；审批恢复与副作用幂等留 M10/M13 |
| 07 | MCP 协议 | Client 生命周期、发现、调用、TypeScript E2E | E3；远程 transport、重连和生产容量未验证 |
| 08 | Agent Skill | 只读 Catalog/Resolver、三 Runtime 上下文、固定评测 | E3；真实模型遵循和 Provider usage 未验证 |
| 13 | Agent Harness | server-owned catalog/policy、RBAC、超时和上限 | 只覆盖 M9 边界；统一故障恢复留 M13 |
| 24 | 自动化测试 | 生命周期、工具适配、协议 E2E、路径安全和效果评测 | 默认离线；跨平台和远程 E4 未覆盖 |

## M9 最终验收清单

- [ ] 能独立构建 TypeScript Server，并通过 Python Client 真实执行 initialize、发现、有效/无效调用和关闭。
- [ ] 能画出 Host/Client/Server 与共同 Registry 数据流，指出进程、Task 和生命周期所有者。
- [ ] 能解释 Function Calling、MCP、Skill 的职责差异和组合方式。
- [ ] 能解释 roots 只是协议协调信息，不是 OS 安全边界，并列出至少三项真正的文件安全控制。
- [ ] 能证明远端元数据、Schema、结果和 Skill 内容不会直接获得信任或执行权。
- [ ] 能运行 M9 聚焦命令、固定 Skill 评测和 `scripts/verify.ps1`，如实记录退出码、通过、跳过、警告和未验证范围。
- [ ] 能说明 3153 字节/启发式 789 Token 不是 Provider usage，未知费用保持 `null`。
- [ ] 概念、实操、场景题总分至少 80，且没有安全红线错误。
- [ ] 完成一页速查表使用练习和一次合格费曼复述。
- [ ] 能指出 M9 对 30 项大纲 07/08 的直接覆盖，以及 M10/M13 的后续承接点。

完成上述课程条目可以验收 M9-T6 的材料；学习者个人完成情况只写 `../progress.md`，工程状态仍由连续性状态页和实际 verification 决定。

## 官方资源

- MCP 架构：<https://modelcontextprotocol.io/docs/learn/architecture>
- MCP Client 教程：<https://modelcontextprotocol.io/docs/develop/build-client>
- MCP Client 概念：<https://modelcontextprotocol.io/docs/learn/client-concepts>
- MCP Client 最佳实践：<https://modelcontextprotocol.io/docs/develop/clients/client-best-practices>
