# 验证证据日志

本文件只追加实际执行结果。失败、跳过、警告和未验证范围与成功结果同等重要。

## 记录规则

- ID 格式：`V-YYYYMMDD-NNN`。
- 每条记录绑定一个或多个稳定任务 ID。
- 命令必须是实际执行命令，不把计划命令写成已验证。
- 在线验证标明是否产生费用，不记录密钥或原始敏感输入。
- 历史结果不改写；环境或结果变化时新增记录。

## V-20260716-001：C0 离线基线与文档漂移复核

- 任务：`C0-T3`、`C0-T4`
- 时间：2026-07-16 11:25–11:40，Asia/Shanghai
- 计划版本：2.0
- 验证目标：基于 `acb12c0` 的工作区；验证期间仅包含 C0 计划与文档修改，尚未修改业务代码
- 模式：offline；未读取 API Key，未访问模型服务，费用为 0

### 环境

| 项目 | 实际值 |
| --- | --- |
| 项目虚拟环境 Python | 3.12.10 |
| Node.js | v22.16.0 |
| npm | 10.9.2 |
| Git | 2.38.1.windows.1 |
| Docker Client | 29.3.1 |
| Docker Engine | 未运行，无法连接 `docker_engine` named pipe |

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `.\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests -v` | 0 | 98 项通过，1 项跳过，0 项失败；耗时 1.740 秒 |
| `.\.venv\Scripts\python.exe -m pip check` | 0 | `No broken requirements found.` |
| `npm.cmd run build --prefix frontend` | 0 | `vue-tsc -b && vite build` 通过；Vite 8.1.4 转换 18 个模块 |
| `npm.cmd run build --prefix mcp-servers/knowledge-server` | 0 | TypeScript `tsc` 构建通过 |
| `docker compose -f deploy/compose.yaml config --quiet` | 0 | Compose 配置语法通过；不代表镜像或容器运行通过 |
| `.\.venv\Scripts\python.exe -S -m unittest backend.tests.test_manual_agent_loop -v` | 0 | 禁用 `site-packages` 后 7 项 M1 测试全部通过 |
| `.\.venv\Scripts\python.exe -S -m backend.app.demo` | 0 | 依次输出 `run.started`、`tool.started`、`tool.completed`、`run.completed` |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 首轮最终版检查通过：52 个稳定任务、38 个 Markdown 文件；首份 handoff 创建后需再次检查 |
| `git diff --check` | 0 | 修正两处行尾空格后通过；仅有 Git 的 LF/CRLF 提示 |

### 失败尝试、警告与跳过

- `python -S ...` 通过 PATH 首先命中 `C:\Users\gorma\AppData\Local\Microsoft\WindowsApps\python.exe`，当前受管会话返回“指定的登录会话不存在”，退出码 1。`Get-Command python -All` 同时确认真实 Python 位于 PATH 后方；文档已增加仓库 `.venv` 解释器回退方式，且回退验证通过。
- `py -0p` 返回 `No installed Pythons found!`；本项目不把 Windows Python Launcher 作为前置条件。
- 后端测试跳过 `test_rejects_parent_traversal_and_symbolic_link_escape`，原因是当前 Windows 环境无法创建符号链接，异常类型为 `OSError`。
- 后端测试出现 `StarletteDeprecationWarning`：当前 `fastapi.testclient` 仍通过旧的 Starlette/httpx 兼容路径；本轮不安装新依赖，后续由依赖升级任务处理。
- Docker 命令两次警告无法读取 `C:\Users\gorma\.docker\config.json`，但 Compose 配置解析退出码为 0。
- `docker version` 能读取 Client 29.3.1，但因 Docker Engine 未运行而退出码为 1；容器、PostgreSQL/pgvector 和 Nginx 均未验证。
- 连续性脚本首稿在 Windows PowerShell 5.1 下因 UTF-8 无 BOM 的中文字符串解码失败；脚本改为纯 ASCII 后通过。

### 结论

- `C0-T4` 达到 `verified`：离线基线、M1 标准库边界和文档漂移修正均有证据。
- `C0-T3` 的计划、ADR、状态和校验脚本达到 `code_complete`；创建首份 handoff 并执行提交后检查，才能把整个 C0 标记为 `verified`。
- `KI-012` 关闭；`KI-009` 保持 open，继续跟踪真实 Docker 运行验收。
- 未执行任何在线模型、在线 Embedding 或远程 Git 操作。

## V-20260716-002：C0 提交后连续性闭环

- 任务：`C0-T3`
- 时间：2026-07-16 11:40，Asia/Shanghai
- 计划版本：2.0
- 验证目标：计划基线提交 `6f8490a`，加首份 handoff 与状态更新的工作区
- 模式：offline；费用为 0

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、39 个 Markdown 文件；任务 ID、当前任务、accepted spec、相对链接和大纲映射全部通过 |
| `git diff --check` | 0 | 无空白错误；仅有 LF/CRLF 转换提示 |
| `git status --short` | 0 | 只有 status 与首份 handoff 文档修改，没有业务代码或未知产物 |

结论：`C0-T1` 至 `C0-T4` 全部达到 `verified`，下一任务为 `M8-T1`。

## V-20260716-003：M8-T1 Settings 与 ApplicationContainer

- 任务：`M8-T1`
- 时间：2026-07-16 11:42–12:16，Asia/Shanghai
- 计划版本：2.0
- 验证目标：实现提交 `c8b968b`，加 status 与 handoff 的连续性工作区
- 模式：offline；未读取真实 API Key，未创建 Provider Runner，未访问模型服务，费用为 0

### 环境与依赖决策

| 项目 | 实际值 |
| --- | --- |
| Python | 3.12.10 |
| Pydantic | 2.13.4 |
| Node.js/npm | v22.16.0 / 10.9.2 |
| 新增或安装依赖 | 无 |
| `backend/requirements-m2.txt` | 未修改；`pip check` 通过 |
| `pydantic-settings` / `python-dotenv` | 未直接导入，不自动加载 `.env` |

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_settings backend.tests.test_container backend.tests.test_api backend.tests.test_identity -v` | 0 | 审查补测后 46 项全部通过 |
| `.\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests -v` | 0 | 121 项运行，120 项通过，1 项跳过，0 失败；耗时 2.162 秒 |
| `.\.venv\Scripts\python.exe -m pip check` | 0 | `No broken requirements found.` |
| `npm.cmd run build --prefix frontend` | 0 | Vue TypeScript 检查与 Vite 8.1.4 生产构建通过，转换 18 个模块 |
| `npm.cmd run build --prefix mcp-servers/knowledge-server` | 0 | TypeScript `tsc` 构建通过 |
| `docker compose -f deploy/compose.yaml config --quiet` | 0 | Compose 配置语法通过；不代表容器运行通过 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 提交后 handoff 工作区检查通过：52 个稳定任务、41 个 Markdown 文件 |
| `git diff --check` | 0 | 无空白错误；仅有 LF/CRLF 转换提示 |

### 行为与安全证据

- 默认真实环境读取路径在同时存在测试 Key 与模型名时仍得到 `manual + mock + online=false`，并通过 `socket.create_connection` 与 `socket.socket.connect` 双守卫确认 Container 创建未发网络连接。
- OpenAI 只有 `agents_sdk | langgraph + provider=openai + online=true + Key + model + bounded budget` 才形成有效 Settings；所有缺项和矛盾组合 fail closed。
- Settings、JSON dump、safe summary、Container repr 和配置异常均不包含测试 Key 原值。
- Key 与模型名拒绝控制字符、内部空白和异常长度；不绑定 `sk-` 前缀或当前模型白名单。
- Run 总超时、模型超时、模型调用数、模型重试、步骤、Token 与费用采用独立有界字段；敏感 Trace 配置为 true 时拒绝启动。
- `create_app()` 的新 Container/Settings 路径和旧四参数关键字/位置参数路径均通过；两套装配混用明确拒绝。
- 认证 JSON 仍由原 Authenticator 读取；配置失败发生在知识 seed 等副作用之前。
- 敏感模式扫描只命中空 `OPENAI_API_KEY=` 测试断言和动态认证配置示例，人工复核没有真实 API Key、Bearer Token 或密码。

### 失败尝试、警告与未验证范围

- 测试先行首次运行因 `backend.app.settings`、`backend.app.container` 尚不存在产生 2 个预期 ImportError；实现后转绿。
- 审查补测首次运行因测试补丁缩进错误产生 `IndentationError`；修正后 46 项定向和 121 项全量回归通过。
- 全量测试继续出现既有 `StarletteDeprecationWarning`；本任务没有擅自安装 `httpx2` 或升级依赖。
- `test_rejects_parent_traversal_and_symbolic_link_escape` 因当前 Windows 无符号链接能力跳过，与 C0 基线一致。
- Docker 仍警告无法读取用户级 config；Engine、镜像、容器、PostgreSQL/pgvector 和 Nginx 未验证，由 `KI-009` 跟踪。
- Settings 预算尚未接入实际 Runtime 消耗；属于 M8-T3/M8-T4，不把本次配置测试描述成运行时预算完成。
- M8-T4 真实 Runner 与 M8-T6 在线冒烟尚未实现或执行。

### 结论

- `M8-T1` 达到 `verified`；实现与验证锚点为 `c8b968b`。
- `KI-001`、`KI-003` 保持 open；本任务没有用配置存在冒充真实 Runner 或 LangChain 完成。
- 下一任务为 `M8-T2`，不得提前把 M8 整体标记为完成或 accepted。

## V-20260716-004：M8-T2 持久 Run 与 Store 契约

- 任务：`M8-T2`
- 时间：2026-07-16 12:18–13:11，Asia/Shanghai
- 计划版本：2.0
- 验证目标：实现提交 `4ac81b4`
- 模式：offline；未读取真实 API Key，未创建在线 Runner，未访问模型服务，费用为 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_run_domain backend.tests.test_run_store_contract -v` | 0 | 32 项领域与 Store 测试全部通过 |
| `.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_run_domain backend.tests.test_run_store_contract backend.tests.test_settings backend.tests.test_container backend.tests.test_api backend.tests.test_run_service -v` | 0 | 中途兼容门 70 项全部通过；之后的补测由全量验证覆盖 |
| `.\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests -v` | 0 | 最终 156 项通过，1 项既有 Windows 符号链接能力测试跳过，0 失败 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1` | 0 | 再次完成 156/1 后端回归、Controlled Code-Agent Demo、pip check、Vue 构建、MCP 构建和 Compose 配置 |
| `.\.venv\Scripts\python.exe -m pip check` | 0 | `No broken requirements found.`；本任务未新增或安装依赖 |
| `npm.cmd run build --prefix frontend` | 0 | `vue-tsc -b && vite build` 通过；Vite 8.1.4 转换 18 个模块 |
| `npm.cmd run build --prefix mcp-servers/knowledge-server` | 0 | TypeScript `tsc` 构建通过 |
| `docker compose -f deploy/compose.yaml config --quiet` | 0 | Compose 配置语法通过；不代表容器运行通过 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、42 个 Markdown 文件；提交前链接和状态检查通过 |
| `git diff --check` / `git diff --cached --check` | 0 | 无空白错误；只有 Git 的 LF/CRLF 转换提示 |
| `.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_run_domain backend.tests.test_run_store_contract -q` | 0 | 实现提交 `4ac81b4` 后 33 项快速回归通过 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | handoff 加入后 52 个稳定任务、43 个 Markdown 文件全部通过 |

### 行为、并发与安全证据

- 新 Run 状态固定为 queued、running、waiting_approval、completed、failed、cancelled；合法边、非法边、同状态转换和终态不可回退均有测试。
- `(owner_id, idempotency_key_digest)` 幂等作用域在 20 路并发创建中只有一个赢家；同 Key 不同请求并发产生稳定冲突，不覆盖原 Run，也不泄漏 Key 或输入。
- 版本 CAS 使 completed 与 cancelled 竞争只有一个成功；错误 owner 与不存在 Run 使用一致的隐藏语义。
- 50 路成功事件追加产生唯一递增序号；内存实现额外证明全部提交时精确为 1–50。相同 event ID 并发只创建一条，改内容稳定冲突。
- 终态检查与 append 使用固定 Run lock → Event lock 顺序。独立确定性反例复核确认旧 TOCTOU 已关闭，公共 API 没有反向锁链或死锁环。
- 事件和工具数据拒绝非字符串 Key、NaN/Infinity、非法 Unicode、循环、超深/超多节点与超过 64,000 字节的数据；Store 写入和每次返回均深度隔离。
- Tool 审批拒绝可以在未执行时进入 failed；工具时间不能倒退。副作用记录创建时即要求幂等摘要，持久化还原也不能绕过。
- Usage 按每次模型调用建模，未知费用保持 `None`，已知费用必须为 `Decimal` 并带来源；float 金额和 bool Token 被拒绝。
- Run/Tool 提供显式 `safe_summary()`；原始输入、Key、答案、工具参数、原始结果和公开错误内容不进入安全投影。
- 敏感模式扫描只命中既有空 `OPENAI_API_KEY=` 断言和本地教学 Token 示例，人工复核没有真实密钥、Token 或密码。
- 新 Store 已进入 Container，但旧 `run_service`、旧 API 和旧 SSE 不双写；`main.py` 用 `LegacyRunRecord` 明确旧类型边界。

### 审查中发现并修复

- 首版 Tool 状态图允许 waiting_approval → failed，但不变量错误地要求 failed 必须有 started_at；补审批拒绝测试并修复。
- 首版 Tool 没有 updated_at，等待审批后时间可倒退；增加单调更新时间并补反例。
- 首版副作用工具可创建无幂等键的死记录；改为创建和持久化还原都 fail closed。
- 首版非法 Unicode 可能逸出 `UnicodeEncodeError`；规范 JSON、请求摘要和文本边界现在统一转换为稳定 `ValueError`。
- 首版 EventStore 在读取 Run 后再取 Event 锁，终态转换可穿过检查；改为同一临界区的 Run → Event 固定锁序并复测。
- 首版分页先复制全部剩余事件再切片；改为 `islice` 后再生成快照，限制锁占用与复制量。
- 首版合同测试绑定内存对象身份；已抽成适配器无关 mixin，值相等断言可由 M11 PostgreSQL 复用。

### 警告与未验证范围

- 全量测试仍出现既有 Starlette/httpx 弃用警告；本任务未擅自安装 `httpx2` 或升级依赖。
- Windows 符号链接安全测试继续因环境能力跳过，与 C0/M8-T1 基线一致。
- Docker 仍警告无法读取用户级 `C:\Users\gorma\.docker\config.json`；Engine、镜像、容器、PostgreSQL/pgvector 和 Nginx 未验证。
- 内存锁只承诺单进程、单 event loop；不能替代多 worker 或数据库唯一约束。
- `RunStore.transition()` 与 `EventStore.append()` 仍不是通用原子 Unit of Work。`KI-015` 保持 open，由 M8-T3 固定用例契约、M11 PostgreSQL 同事务关闭。
- M8-T3 Runtime/Coordinator、M8-T4 真实 Runner 与 M8-T6 在线冒烟尚未实现或执行。

### 结论

- `M8-T2` 达到 `verified`；实现与验证锚点为 `4ac81b4`。
- 新领域模型、异步 Store 扩展缝和可复用合同测试可以进入 M8-T3；旧教学 API 保持兼容。
- 下一任务为 `M8-T3`，不得把 Store 基础描述成 Runtime、真实模型或数据库事务已经完成。

## V-20260716-005：M8-T3 异步 Runtime 与 RunCoordinator

- 任务：`M8-T3`
- 时间：2026-07-16 13:15–14:24，Asia/Shanghai
- 计划版本：2.0
- 验证目标：实现提交 `b171ad0`，加 ADR、跟练、规范与连续性文档工作区
- 模式：offline；未读取真实 API Key，未创建在线 Provider Runner，未访问模型服务，费用为 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_runtime_contract backend.tests.test_run_coordinator backend.tests.test_run_store_contract -q` | 0 | 实现提交后 60 项 Runtime、Coordinator 与 Store 核心回归通过 |
| `.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_runtime_contract backend.tests.test_run_coordinator backend.tests.test_run_store_contract backend.tests.test_container backend.tests.test_api backend.tests.test_run_service backend.tests.test_manual_agent_loop backend.tests.test_observability -q` | 0 | 提交前 107 项新旧链兼容回归通过 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1` | 0 | 197 项后端测试通过、1 项既有 Windows 环境跳过；Controlled Code-Agent Demo、pip check、Vue、MCP 与 Compose 配置全部通过 |
| `.\.venv\Scripts\python.exe -m pip check` | 0 | 由统一验证执行；`No broken requirements found.`，本任务未新增或安装依赖 |
| `npm.cmd run build --prefix frontend` | 0 | 由统一验证执行；`vue-tsc -b && vite build` 通过，Vite 8.1.4 转换 18 个模块 |
| `npm.cmd run build --prefix mcp-servers/knowledge-server` | 0 | 由统一验证执行；TypeScript `tsc` 通过 |
| `docker compose -f deploy/compose.yaml config --quiet` | 0 | 由统一验证执行；Compose 配置语法通过，不代表容器实际运行 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | handoff 前检查通过：52 个稳定任务、44 个 Markdown 文件 |
| `git diff --check` | 0 | 无空白错误；只有 Git 的 LF/CRLF 转换提示 |

### Runtime、持久事件与安全证据

- `RuntimeRequest/Control/Event/Result` 和 async `AgentRuntime` 与 SDK 解耦；结果只允许一致的 completed、failed、cancelled 终态。
- ManualRuntime 每次创建新同步 Loop，在 worker thread 中运行；旧结果与答案保持一致，旧生命周期被过滤，工具过程事件只保留审核白名单。
- 测试秘密值确认输入、工具参数、工具结果、原始错误和异常文本不进入 Runtime repr、持久事件或公开失败。
- 未知旧事件 fail closed；sink 失败不重跑同步 Loop，避免重复工具副作用。
- 取消 worker 先设置共享 token，并只等待有界清理宽限；阻塞线程不能无限击穿 Coordinator deadline，后台结果/异常会被消费。
- PersistentEventEmitter 先 await Store，再做有界 notifier；通知失败或超时不回滚事件、不改变 Run，精确重放不重复通知。

### 生命周期、幂等与并发证据

- `StartCommit` 在同一 Run→Event 锁对内提交 running 与 `run.started`；发布前故障注入证明 Run 保持 queued 且事件为空。
- `TerminalCommit` 在同一临界区提交终态、answer/failure 与匹配事件；发布前故障注入证明两边均不可见。
- 普通 append 拒绝 Coordinator 拥有的 started/completed/failed/cancelled 生命周期，不能绕过一次提交入口。
- 同终态命令顺序及并发重放只有一次 `created=true`、一个 sequence；改 event data 或 outcome 为稳定 `event_conflict`。
- complete 与 cancel 竞争同一 version 只有一个持久赢家；终态 event ID 包含目标状态，失败方读取赢家而不覆盖。
- barrier 测试覆盖“取消发生在 token 检查与 append 之间”：晚到过程事件被终态检查拒绝，execute 返回 durable cancelled 而非 Store 异常。
- 同 Coordinator 并发 execute 共享一个 shielded task；取消一个 waiter 不取消执行。两个 Coordinator 同时读取 queued 时只有 start claim 的创建者执行 Runtime，另一方等待相同 durable 结果。
- 过程 Store unavailable 不通知、不伪造 failed，Run 明确保留 running 供恢复流程处理；该待办登记为 `KI-016`。

### 旧链兼容与默认离线证据

- Container 默认组合为匹配的内存 Store、ManualRuntime/MockModel 和 RunCoordinator；构造路径继续通过 socket 双守卫，无网络连接。
- 默认 Coordinator 程序化执行能得到 `run.started -> run.completed`，并消费 max steps、model retries 与执行 deadline。
- 旧 POST/GET Run 响应字段精确保持 `id/session_id/status/answer/event_types/error`；旧 HTTP/SSE 继续使用 legacy run_service，新 RunStore/EventStore 为空，没有双写。
- 本任务未修改真实 Agents SDK、LangGraph 或在线配置门，也未把 fake/Mock 结果当作在线验证。

### 审查中发现并修复

- 首版只原子提交终态，start 仍是 transition+append；补 StartCommit、故障测试和普通 lifecycle append 拒绝。
- 首版 active cancel 只设置 token，可能返回 true 后仍 completed；改为 cancelled TerminalCommit 与完成共享 CAS，并补确定性 barrier。
- 首版所有终态共用 event ID，竞争可能产生 event conflict；ID 改为包含目标状态。
- 首版 ManualRuntime 取消后无界等待 worker；改为有限 grace 和后台结果消费，并补阻塞 worker 反例。
- 首版 notifier 无上界；增加独立短超时，启动等待会消耗执行 deadline，失败保持最佳努力语义。
- 首版 cancel 可能穿过 emit token 检查再撞终态 append；增加 durable winner 折叠和 blocked append 竞争测试。
- 首版跨 Coordinator 的 start 精确重放仍会再次执行 Runtime；改为只有 `created=true` 获得执行权，重放者等待 Store 赢家。

### 警告与未验证范围

- 全量测试继续出现既有 Starlette/httpx 弃用警告；未擅自安装 `httpx2` 或升级依赖。
- notifier 故障测试预期记录三次安全 `run event notification failed`，日志不包含异常文本或事件数据。
- Windows 符号链接安全测试继续因环境能力跳过，与前序基线一致。
- Docker 仍警告无法读取用户级 `C:\Users\gorma\.docker\config.json`；Engine、镜像、容器、PostgreSQL/pgvector 和 Nginx 未验证。
- PostgreSQL 同事务、多进程 lease、连接结果未知与重启恢复未验证；`KI-015` 只达到 mitigated，不能关闭。
- ManualRuntime 完成同步 Loop 后才回放进度，线程不能硬取消；`KI-017` 保持 open。
- waiting approval/resume、模型调用数、单次模型 timeout、Token、usage 和费用预算尚未接入新 Runtime；由 M8-T4/M10 继续。
- 真实 SDK Runtime、在线模型与 M8-T6 付费冒烟尚未实现或执行。

### 结论

- `M8-T3` 达到 `verified`：实现锚点为 `b171ad0`，文档与 handoff 由后续本地提交固定。
- `KI-015` 降为 mitigated；新增 `KI-016` 与 `KI-017`，避免把内存一次提交或同步适配器描述成生产恢复与真流式能力。
- 下一任务为 `M8-T4`：先基于已锁定依赖和当前官方文档写 fake runner/event fixture 与 OpenAI Agents Runtime 离线契约；没有新的单次授权不得执行在线调用。

## V-20260716-006：M8-T4 OpenAI Agents SDK Runtime 离线契约

- 任务：`M8-T4`
- 时间：2026-07-16 14:25–17:46，Asia/Shanghai
- 计划版本：2.0
- 验证目标：实现提交 `ac24dda`；文档、handoff 与最终状态由后续本地提交固定
- 模式：offline；未读取真实 API Key，未访问模型服务，未执行 M8-T6 在线冒烟，在线费用为 0
- 依赖事实：Python 3.12.10、Node.js v22.16.0、`openai-agents==0.18.2`、`openai==2.45.0`；本任务没有新增或安装依赖

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime -v` | 0 | 最终 33 项 SDK Runtime、工具桥、Coordinator 集成专项测试全部通过 |
| `.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime backend.tests.test_runtime_contract backend.tests.test_run_coordinator backend.tests.test_tool_security backend.tests.test_container backend.tests.test_settings backend.tests.test_framework_runtimes backend.tests.test_api backend.tests.test_run_service -v` | 0 | 结构化分段补强前的兼容门 123 项全部通过；之后由最终专项与全量验证覆盖新增修改 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1` | 0 | 最终 231 项后端测试通过、1 项既有 Windows 环境能力测试跳过；Controlled Code-Agent Demo、pip check、Vue 生产构建、MCP TypeScript 构建和 Compose 配置全部通过 |
| `.\.venv\Scripts\python.exe -c "import importlib.metadata as m; ..."` | 0 | 确认本地锁定版本为 `openai-agents=0.18.2`、`openai=2.45.0` |
| `git diff --check` / `git diff --cached --check` | 0 | 无空白错误；仅出现 Git 的 LF/CRLF 转换提示 |
| `.\.venv\Scripts\python.exe -B -m compileall -q backend\app backend\tests` | 1 | 辅助检查因既有 `__pycache__` 目录拒绝写入报 `WinError 5`；没有删除缓存或改权限，模块已由 231 项测试实际导入执行 |

### Runtime、结构化流与 SDK 契约证据

- `OpenAIAgentsRuntime` 只依赖公开 Runner Protocol；生产路径调用 `Runner.run_streamed()`，测试注入 0.18.2 兼容 fake stream，不使用 SDK 私有 run-loop。
- 每 Run 显式创建 `AsyncOpenAI(max_retries=0)` 和 `OpenAIResponsesModel`，并有界关闭 client；Container 构造时 patch client factory 与 socket 双守卫，证明不创建 client、不联网。
- 每次 RunConfig 显式设置 `tracing_disabled=True`、`trace_include_sensitive_data=False`、显式 model、include usage、输出上限和唯一 SDK retry 层。
- Provider strict schema 不携带 `minLength/maxLength`；空白和最终 UTF-8 字节上限仍由 Runtime 校验，降低首个在线请求因 schema 子集差异返回 400 的风险。
- 结构化 raw JSON delta 经过跨 chunk 增量解码，只持久化 `answer` 正文。转义键、转义字符和 Unicode 代理对均有反例；安全 `segment` 区分多轮结构化对象，最终 typed output 必须与最后 segment 一致。
- Runtime 只映射审核过的文本、工具开始/完成/失败和 Run aggregate usage；未知顶层 wrapper、handoff、扩展工作流、未闭合工具与不一致终态 fail closed，Provider raw 对象与异常文本不越界。

### 工具、身份与持久安全证据

- 每 Run 建立不可共享的可信 context、定义快照和隔离 ToolRegistry；Schema 重新校验名称、根关键字、深度、节点与 UTF-8 字节边界。
- M8-T4 只暴露低风险、无需审批、无副作用工具。高风险、需审批或有副作用的定义在 M10 interruption/resume 完成前一律省略。
- 工具执行继续经过角色和参数 Schema；SDK call ID 有界，参数、原始结果和异常文本不进入持久事件，custom data 只保留 `ok/error_code`。
- 循环、过深、过多节点、非有限数、非法 Unicode、单值或累计超过 64 KB 的输出均返回稳定 `tool_output_invalid`；直接累计大字符串回归已覆盖。
- Coordinator 在 active 执行前强制 `execution_context.principal_id == Run.owner_id`；身份不一致测试证明 Runtime 与 Store 都没有被调用。

### 取消、错误、usage 与预算证据

- token 取消、外层 task 取消、流处理失败和 sink 失败都在同一 stream 实例上 immediate cancel，并继续 drain 原迭代器；晚到事件被抑制，stalled consumer 使用两段有限清理。
- Event sink/Store 异常不被重分类为 Provider 错误；与 token 或外层取消竞态时 Store 失败优先传播，避免隐藏持久化故障。
- SDK/Provider timeout、认证、限流、连接、5xx、bad request、MaxTurns、guardrail 与行为错误映射为稳定 code/category/retryable，不公开 `str(exception)`。
- `model.usage` 明确为 `scope=run` 聚合；费用保持 `None + unknown`，不伪造成单次 `UsageRecord` 或零费用。
- `max_turns=min(max_steps,max_model_calls)` 与每请求 `max_output_tokens` 是前置上限；requests/input/output aggregate 在流结束后核对。SDK retry 可能先使 requests 超额，输入 Token 只能事后发现，`max_cost_usd` 尚未执行，HTTP timeout 也不是整个 Run 的硬墙钟；由 `KI-018` 跟踪。

### 独立复审

- SDK API 复审核对本地 0.18.2 的 `Runner/RunConfig/FunctionTool` 签名、事件字段和 `AsyncOpenAI` 生命周期；最终未发现阻断项。
- Runtime 契约复审重点检查较紧 `max_turns`、外层取消与 Store 失败竞态、结构化终态和同迭代器 drain；阻断项与高风险项清零。
- 工具/安全复审检查审批跨 Run、同步副作用、owner/principal、Schema TOCTOU、累计输出、call ID、Container 门禁和 client 延迟创建；阻断项与高风险项清零。

### 警告、失败尝试与未验证范围

- 全量测试仍有既有 Starlette/httpx 弃用警告；没有擅自安装 `httpx2` 或升级依赖。
- notifier 负向测试按预期记录安全的 `run event notification failed`；日志没有事件数据或原始异常文本。
- Windows 符号链接测试因当前环境能力跳过；与前序基线一致。
- Docker Compose 仅配置语法通过，且仍警告无法读取用户级 Docker config；Engine、镜像、容器、PostgreSQL/pgvector 和 Nginx 未验证。
- `compileall` 失败是缓存目录写权限问题，不将其隐藏成通过，也不把它误报为语法错误；实际测试导入是本次 Python 可执行证据。
- 同步只读工具使用 `asyncio.to_thread()`；取消后不能硬停止底层线程，可能继续占用默认 executor，由 `KI-017` 跟踪。
- Provider strict schema 接受度、真实 streaming、真实工具调用、真实 usage、模型质量、在线费用和 Provider 侧资源清理由 M8-T6 单次授权冒烟验证。

### 结论

- `M8-T4` 达到 `code_complete`，实现锚点为 `ac24dda`；不得写成在线 `verified`。
- `KI-001` 降为 mitigated；`KI-017` 扩展同步工具线程边界；新增 `KI-018` 记录请求/Token/费用与全程 timeout 的真实治理缺口。
- 下一任务为 `M8-T5`：保持 offline，完成 Manual、Agents SDK、LangGraph 三 Runtime 契约和 LangChain 最小对照；M8-T6 仍需用户新的单次在线授权。

## V-20260716-007：模型切换与课程高效交付协议

- 任务：C0 连续性维护；当前业务任务仍为 `M8-T5 / planned`
- 时间：2026-07-16 19:01–19:06，Asia/Shanghai
- 计划版本：2.0
- 验证目标：基线 HEAD `ed5ad9c` 上的课程交付协议、模型切换 handoff 和入口导航工作区；提交由后续本地 commit 固定
- 模式：offline；未读取真实 API Key，未访问模型服务，费用 0
- 依赖：没有新增、安装、升级或删除依赖

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` | 0 | 修改前工作区无输出；没有未提交的 M8-T4 或 M8-T5 业务修改 |
| `git diff --check` | 0 | 无空白错误；仅有既有 LF/CRLF 转换提示 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、49 个 Markdown 文件；任务 ID、当前任务、accepted spec、相对链接和大纲映射全部通过 |
| `rg -n "TBD\|TODO\|PLACEHOLDER\|待补\|待定\|以后填写" AGENTS.md README.md docs\implementation-plan.md docs\continuity\README.md docs\continuity\status.md docs\continuity\course-delivery-playbook.md docs\continuity\handoffs\2026-07-16-model-switch-course-delivery.md` | 1 | 预期无匹配；协议、交接和入口文件不存在占位符 |

### 内容一致性与复审

- 用户已确认采用“仓库入口 + 永久 playbook + 动态 status + 不可变 handoff”的模型切换方案。
- Playbook 固定课程质量底线、A/B/C 任务等级、E0–E4 证据等级、时间盒、定向/全量验证触发条件和权限门。
- 实施计划只调整通用交付节奏和完成定义的聚合位置；没有重编号 52 个稳定任务，也没有改变 M8-T5 的产物与验收契约。
- 一次独立聚焦复审发现纯文档 B 类任务与 6–12 个业务用例表述冲突，已改为纯文档只做内容、链接、连续性和 diff 检查；复审指出的验证记录缺口由本条关闭。
- M8-T4 的 `ac24dda`、`V-20260716-006` 和 `code_complete` 边界保持不变；本轮没有重跑 231 项全量回归，因为没有代码、依赖、构建配置或公共接口变化。

### 结论

- 模型切换协议达到文档级验证门；本轮只固定后续生产方式，不提升任何业务任务状态。
- 当前任务继续是 `M8-T5 / planned`，下一步先设计三 Runtime 的共享成功/失败 fixture；不得重做 M8-T4、运行 M8-T6 或提前实现 M10–M13。

## V-20260716-008：M8-T5 三 Runtime 契约与 LangChain 对照

- 任务：`M8-T5`
- 时间：2026-07-16 22:07，Asia/Shanghai
- 计划版本：2.0
- 验证目标：基线 HEAD `f83cbbc` 上的 M8-T5 工作区；提交由后续本地 commit 固定
- 模式：offline；未读取真实 API Key，未访问模型服务，未执行 M8-T6，费用 0
- 依赖事实：Python 3.12.10、`langchain==1.3.13`、`langgraph==1.2.9`、`openai-agents==0.18.2`；没有新增、安装、升级或删除依赖

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 接手恢复检查通过：52 个稳定任务、49 个 Markdown 文件 |
| `.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime backend.tests.test_runtime_contract backend.tests.test_run_coordinator -q` | 0 | handoff 最小恢复集 64 项通过；三条 notifier 失败日志来自既有负向用例 |
| `.\.venv\Scripts\python.exe -X utf8 -B .\labs\langchain-agent\demo.py` | 0 | 实际输出一次 `add_numbers`、`ToolMessage`、四段消息序列和最终答案 5 |
| `.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_runtime_comparison backend.tests.test_langchain_agent_lab backend.tests.test_runtime_contract backend.tests.test_openai_agents_runtime backend.tests.test_run_coordinator backend.tests.test_container backend.tests.test_framework_runtimes -v` | 0 | 最终定向回归 89 项全部通过 |
| `.\.venv\Scripts\python.exe -S -B -m unittest backend.tests.test_manual_agent_loop -v` | 0 | 禁用 `site-packages` 后 7 项 M1 测试通过，证明 LangGraph 未污染手写 Loop 顶层导入 |
| `.\.venv\Scripts\python.exe -S -B -m backend.app.demo` | 0 | 禁用 `site-packages` 后 M1 Demo 仍依次输出 start、tool start/completed 与 run completed |
| `.\.venv\Scripts\python.exe -B -c "import importlib.metadata as m, sys; ..."` | 0 | 确认 Python 与三项锁定框架版本 |
| `git diff --check` | 0 | 代码与阶段文档修改无空白错误；仅有既有 LF/CRLF 转换提示 |
| `rg -n "OPENAI_API_KEY\|api[_-]?key\|sk-[A-Za-z0-9]" ...` | 1 | 预期无匹配；本任务代码、测试和 lab 未写入 Key 或疑似密钥 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1`（文档闭环后） | 0 | 52 个稳定任务、50 个 Markdown 文件；任务 ID、当前任务、accepted spec、相对链接和大纲映射全部通过 |
| `git diff --check`（文档闭环后） | 0 | 最终工作区无空白错误；仅有既有 LF/CRLF 转换提示 |

### 共享契约与真实框架路径

- 同一成功 fixture 对 Manual、Agents SDK 和 LangGraph 使用相同输入、`add_numbers` 定义与参数；三者均完成并产生 `tool.started -> tool.completed`，handler 各执行一次。
- 同一失败 fixture 缺少必需参数 `b`；三者均产生 `tool.failed(error_code=invalid_arguments)`，handler 均未执行，并返回相同安全 fallback 结果。
- Agents SDK fixture 通过实际 `build_sdk_tools()`、`FunctionTool.on_invoke_tool()` 和 Runtime 事件映射；fake Runner 只替代 Provider/SDK 外部执行边界。
- LangGraph Runtime 通过公开 `StateGraph.compile().ainvoke()` 执行模型节点、工具节点和条件边，并可由现有 Container 在 `langgraph + mock` 配置下选择。
- LangChain lab 通过公开 `create_agent()` 与 `agent.invoke()` 进入 ToolNode；确定性 ChatModel 只替代外部 Provider，工具绑定、消息循环和执行由框架完成。

### 安全、失败与范围证据

- 共享工具事件不包含 arguments、value 或 error_message；Agents SDK 额外 usage/输出事件继续遵守 M8-T4 白名单。
- LangGraph 在模型错误时只返回稳定 `model_execution_failed`，预取消不构造 model/tool，Event sink 故障原样传播，不伪装为模型失败。
- LangGraph Runtime 使用显式模块导入，不从 `backend.app.agent` 顶层导出；M1 的 `python -S` 测试与 Demo 证明标准库学习路径未新增 LangGraph 依赖。
- LangChain socket 双守卫测试通过；非有限或布尔操作数在 Agent 执行前被拒绝。
- 新增 9 个高价值测试方法，并通过参数化子用例覆盖三 Runtime 的成功、失败、脱敏、取消、模型错误、Store 失败、LangChain 工具调用、零网络与输入边界。

### 警告、失败尝试与未验证范围

- FastAPI 定向回归仍出现既有 Starlette/httpx 弃用警告；没有安装 `httpx2` 或升级依赖。
- 首次直接运行 lab 时 PowerShell 控制台把中文显示为乱码，命令本身退出码为 0；使用 Python `-X utf8` 重跑后输出可读，测试中的 Unicode 断言始终通过。
- 没有运行 `scripts/verify.ps1` 全量门：本任务未改变依赖、锁文件、前端、HTTP API、跨前后端契约或发布配置，定向 89 项已覆盖修改边界。
- fake Runner、MockModel 与确定性 ChatModel 只能证明 E2/E3 离线调用链，不能证明 Provider streaming、工具调用、usage、费用或资源清理。
- LangGraph checkpoint、interrupt、resume 和重启恢复仍属于 `KI-004` / M10；LangChain 不进入主 `AgentRuntime` 或 `RunCoordinator`。
- Docker、PostgreSQL/pgvector、Nginx 和真实在线模型均未验证。

### 结论

- `M8-T5` 达到 `verified`：三 Runtime 共享契约为 E3，LangChain 独立调用链为 E2，框架取舍与运行命令已落盘。
- `KI-003` 关闭；`KI-001` 的离线代码对照部分完成，但真实 Provider 证据仍缺，因此保持 mitigated 并继续由 M8-T6 接管。
- 下一任务是 `M8-T6`；可以准备 fail-closed 在线脚本，但没有用户新的单次授权时不得读取 Key 或执行真实模型调用。

## V-20260717-001：M8-T6 在线冒烟门禁离线代码完成

- 任务：`M8-T6`
- 时间：2026-07-17 09:57，Asia/Shanghai
- 验证目标：HEAD `e03f8d6` 上的 M8-T6 工作区；该 HEAD 同时确认了 M8-T5 的实际实现提交
- 模式：offline；没有读取真实 API Key、访问模型服务或执行付费调用，费用 0
- 依赖事实：复用现有 `openai-agents==0.18.2` 与 Python 3.12.10；没有新增、安装、升级或删除依赖

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 接手时工作区干净；HEAD 为 M8-T5 实现提交 `e03f8d6`，由此发现并登记 `KI-019` 连续性漂移 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 接手恢复检查通过：52 个稳定任务、50 个 Markdown 文件 |
| `.\.venv\Scripts\python.exe -X utf8 -B .\labs\langchain-agent\demo.py` | 0 | handoff Demo 恢复通过：答案 5、一次工具调用和完整消息序列 |
| `.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_runtime_comparison backend.tests.test_langchain_agent_lab backend.tests.test_runtime_contract backend.tests.test_openai_agents_runtime backend.tests.test_run_coordinator backend.tests.test_container backend.tests.test_framework_runtimes -q` | 0 | handoff 最小恢复集 89 项通过；既有警告和三条 notifier 负向用例日志不变 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_online_smoke -v` | 0 | 最终 12 项新增离线门禁、纵切、脱敏与 PowerShell 包装测试通过 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_online_smoke backend.tests.test_settings backend.tests.test_container backend.tests.test_runtime_contract backend.tests.test_openai_agents_runtime backend.tests.test_run_coordinator -v` | 0 | 102 项定向回归通过；既有 Starlette/httpx 弃用警告和三条 notifier 负向用例日志不变 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-online.ps1 -Suite M8`（不带授权） | 64 | `powershell.exe` 原始进程由自动化测试确认返回 64，并在启动 Python 前拒绝；统一命令宿主直接展示时把非零状态归一为 1 |
| `rg -n 'sk-...|Bearer ...|OPENAI_API_KEY=...' backend/app/online_smoke.py backend/tests/test_online_smoke.py scripts/verify-online.ps1` | 1 | 预期无匹配；测试凭据每次随机生成，代码和脚本没有固定 Key、Bearer Token 或疑似真实密钥 |
| `git diff --check` | 0 | 无空白错误；仅有既有 LF/CRLF 转换提示 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1`（文档闭环后） | 0 | 52 个稳定任务、51 个 Markdown 文件；当前任务、状态、相对链接和 handoff 均通过 |
| `git diff --check`（文档闭环后） | 0 | 最终工作区无空白错误；仅有既有 LF/CRLF 转换提示 |

### 门禁与纵切证据

- `scripts/verify-online.ps1` 独立于默认 `verify.ps1`；缺少 `-Authorized` 时第一步退出，不检查项目 Python，也不读取任何 Provider 环境配置。
- Python 入口再次要求 `--authorized`，然后才解析 `Settings`；测试使用不可读取的 Mapping 证明未授权路径不会访问环境或调用 executor。
- 完整配置固定要求 `agents_sdk + openai + online=true + OPENAI_API_KEY + OPENAI_MODEL`；真实脚本另要求 M8 suite、调用者提供输入/输出 token 估算费率，以及低 step、调用次数、token、重试、超时和成本上限。
- 离线 Fake Runtime 通过实际 `RunRecord -> RunStore -> RunCoordinator -> EventStore` 纵切，产出持久 `run.started`、流式 delta、匹配的 `add_numbers` start/completed、正 usage 与 `run.completed`；这属于 E3 集成证据，不是 Provider E4 证据。
- 成功摘要只含 suite、Run ID、状态、模型、时长、流分段数、工具完成标记、token usage、估算费用、费率来源、事件数和退出码；不含 prompt、answer、工具参数、工具结果或 Key。
- 费用按调用者显式提供的每百万 token 费率估算，并标记 `operator_supplied_per_million_token_rates`；它不是账单事实，也不替代 `KI-018` 所需的可版本化定价源和持久成本账本。

### 失败尝试、警告与未验证范围

- 新增测试首轮为 11 通过、1 失败：Windows 默认执行策略在脚本逻辑前返回 1；测试改为仓库统一的 `-ExecutionPolicy Bypass` 后 12 项全部通过，没有改写系统执行策略。
- 一次疑似凭据扫描因 PowerShell 嵌套引号解析失败；改用单引号正则重跑后预期无匹配。
- 没有用户新的单次授权，因此未运行带 `-Authorized` 的脚本，未读取真实 Key、未验证 Provider strict schema、真实 streaming、真实工具调用、真实 usage、模型质量、费用或资源清理。
- 没有运行 `scripts/verify.ps1` 全量门：本任务没有修改依赖、锁文件、HTTP API、前端、跨前后端公共契约或发布配置，102 项定向回归覆盖修改边界。
- `KI-018` 保持 open：当前 runner 只能在 usage 返回后计算本次估算费用，不能提供逐调用硬成本阻断、版本化定价或持久账本。

### 结论

- `M8-T6` 达到 `code_complete`：独立脚本、双重授权门、低预算策略、安全摘要和离线测试已落盘；真实在线 E4 未授权且未执行，因此不得标为 `verified`。
- `KI-019` 的提交事实漂移由本条记录 `e03f8d6` 后关闭；`KI-001` 保持 mitigated，等待一次新的明确授权完成线上 E4。
- 下一任务可进入 `M8-T7` 里程碑跟练与验收汇总，并明确引用 M8-T6 的 `code_complete / online not authorized` 状态；不得把在线缺口包装成通过。

## V-20260717-002：M8-T6 实现提交后恢复锚点

- 任务：`M8-T6`
- 时间：2026-07-17 10:08，Asia/Shanghai
- 验证目标：实现提交 `bd6c09a`（`feat: add guarded online smoke runner`）
- 模式：offline；没有读取真实 API Key、访问模型服务或执行付费调用，费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` | 0 | 实现提交后工作区干净 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_online_smoke -q` | 0 | 提交后最小恢复集 12 项全部通过 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、51 个 Markdown 文件通过 |

### 结论

- M8-T6 实现提交固定为 `bd6c09a`；`V-20260717-001` 的 102 项定向回归、零费用边界与 `code_complete` 结论不变。
- 当前任务保持 `M8-T7 / planned`；真实在线 E4 仍需用户新的单次明确授权。

## V-20260717-003：M8-T7 跟练材料与离线里程碑验收

- 任务：`M8-T7`
- 时间：2026-07-17 10:48，Asia/Shanghai
- 验证目标：HEAD `6e86e1e` 上的 M8-T7 纯文档工作区；提交由后续本地 commit 固定
- 模式：offline；没有读取真实 API Key、访问模型服务或执行付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；沿用 Python 3.12.10、`openai-agents==0.18.2`、现有 Vue/MCP 锁定环境

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 接手时工作区干净；M8-T6 实现 `bd6c09a` 与文档锚点 `6e86e1e` 存在 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_online_smoke -q` | 0 | handoff 最小恢复集 12 项通过 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_online_smoke backend.tests.test_settings backend.tests.test_container backend.tests.test_runtime_contract backend.tests.test_openai_agents_runtime backend.tests.test_run_coordinator -q` | 0 | handoff 定向恢复集 102 项通过；既有 Starlette/httpx 弃用警告和三条 notifier 负向日志不变 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-online.ps1 -Suite M8`（不带授权） | 64 | 自动化已确认原始 `powershell.exe` 进程在进入 Python 前返回 64；统一命令宿主显示非零为 1，未读取 Provider 环境配置 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_stream_and_post_stream_errors_use_safe_stable_mapping -v` | 0 | 教程中的 Provider 稳定错误定位命令 1 项通过 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_runtime_comparison backend.tests.test_langchain_agent_lab backend.tests.test_framework_runtimes -v` | 0 | 修正后的三 Runtime、LangChain 与框架对照命令 12 项通过 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1` | 0 | 授权重跑后全量离线门通过：后端 252 项通过、1 项既有 Windows symlink 跳过；Code-Agent Demo、`pip check`、Vue 18 模块生产构建、MCP TypeScript 构建和 Compose 配置全部通过 |
| `rg` 检查 M8-T7 必需章节 | 0 | 跟练、Provider 故障、验证/E4、三类自测、速查表、费曼、30 项映射和最终验收章节均存在 |
| `rg -n "TBD|TODO|PLACEHOLDER|待补|待定|test_langchain_comparison" ...` | 1 | 预期无匹配；不存在占位符或已删除的错误测试模块名 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、52 个 Markdown 文件；相对链接、当前任务和 handoff 规则通过 |
| `git diff --check` | 0 | 无空白错误；只有既有 LF/CRLF 转换提示 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1`（handoff 后） | 0 | 52 个稳定任务、53 个 Markdown 文件；新增 handoff 与恢复链接通过 |

### 课程与验收证据

- M8 阶段文档现在包含四次递进跟练，每次均给出时间、目标、实际命令、产物、工作映射、通关标准和常见错误；不会重写已经稳定的 T1-T5 实现细节。
- 默认离线分支与经授权 E4 分支分开：教程列出完整在线门、低预算和费率参数，但明确禁止未授权读取 Key 或执行模型。
- Provider 故障演练固定按 Settings、Coordinator、Runtime、Store/Event、重试与副作用顺序定位；公开证据只使用稳定 code/category/retryable。
- 自测分为 5 道概念题、4 道实操题、4 道工作场景题，含 100 分评分和安全红线；费曼任务覆盖讲解、主链、框架取舍、故障与未验证边界。
- 新增独立一页速查表，压缩 Agent/Runner/Runtime/Coordinator/Store 职责、门禁、状态/事件、四框架、白名单、预算、错误、取消、命令和排查顺序。
- M8 与 30 项大纲映射明确列出 01、03、05、06、09、10、11、23、24 的当前证据和 M10/M12/M13 承接点，并链接全局主题映射。

### 失败尝试、警告与未验证范围

- 两个关联 ADR 的首次读取使用了错误文件名，返回 path not found；列出 decisions 目录后按真实文件名读取，内容无漂移。
- 30 项映射首次探测了不存在的 `docs/curriculum-outline.md`；随后定位到真实 `docs/syllabus-map.md`，未新增重复大纲。
- 一次多文件 `apply_patch` 因 hunk 结构无效未应用；拆成两个最小补丁后成功，未产生部分修改。
- 全量门首次在 Vue 写 `frontend/tsconfig.app.tsbuildinfo` 时被沙箱以 EPERM 拒绝；此前后端 252/1、Code-Agent Demo 和 `pip check` 已通过。取得仅工作区验证授权后重跑同一脚本，所有步骤通过，且构建未留下任务外改动。
- 全量后端仍有既有 Starlette/httpx 弃用警告、Windows symlink 跳过、预期 HTTP/observer/notifier 负向日志；没有安装 `httpx2` 或修改环境能力。
- 没有运行带 `-Authorized` 的 online smoke；Provider strict schema、真实 streaming、真实工具调用、真实 usage、在线费用和资源清理仍无 E4 证据。
- Compose 只验证配置展开，不代表 Docker Engine、镜像、容器、PostgreSQL/pgvector 或 Nginx 已运行。

### 结论

- `M8-T7` 达到 `verified`：阶段跟练、真实工作映射、故障演练、三类自测、一页速查表、费曼任务、30 项映射和离线全量门均有证据。
- M8 的离线课程与工程产物达到 `code_complete`；M8-T4/M8-T6 和整个 M8 仍缺真实在线 E4，不得标为 `accepted` 或在线 `verified`。
- `KI-001` 保持 mitigated、`KI-018` 保持 open；下一任务可按计划进入 `M9-T1 / planned`，不重做 M8 或提前实现 M10。

## V-20260717-004：M9-T1 MCP Client 配置与生命周期

- 任务：`M9-T1`
- 时间：2026-07-17 11:27，Asia/Shanghai
- 验证目标：HEAD `ba7adf9` 上的 M9-T1 工作区；提交由后续本地 commit 固定
- 模式：offline；只启动本地 Python MCP STDIO Server，没有读取真实 API Key、访问网络服务或执行付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；使用已锁定 Python 3.12.10、`mcp==1.28.1`、FastAPI 与 TestClient 环境

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 接手时工作区干净；M8-T7 提交 `ba7adf9` 存在 |
| M8-T7 handoff 的 Provider 错误、框架对照和连续性恢复命令 | 0 | 1 项、12 项通过；连续性为 52 个稳定任务和 53 个 Markdown 文件，未发现漂移 |
| 本地 `inspect` 检查 `mcp==1.28.1` 的 `stdio_client`、`ClientSession.initialize()` 与 context manager | 0 | 确认使用公开 SDK 路径，并识别 context manager 必须在同一 Task 退出的约束 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_settings backend.tests.test_mcp_client_lifecycle backend.tests.test_container -v` | 0 | 首轮 36 项通过，但取消用例出现 4 个 ResourceWarning；该轮不作为最终清理证据 |
| 同一 36 项命令加 `-W always::ResourceWarning` | 0 | 改为每 Server 独立 worker 后 36 项通过，无 ResourceWarning；非法协议日志只保留固定摘要 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_lifecycle backend.tests.test_settings backend.tests.test_container backend.tests.test_api backend.tests.test_online_smoke -q` | 0 | 最终 68 项定向回归通过；覆盖 Settings、Container、FastAPI、既有 API 与离线 online-smoke，无资源泄漏警告 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_lifecycle -q` | 0 | 9 项 M9-T1 聚焦测试通过：真实 SDK 初始化/关闭、空选择、允许目录、进程缺失、超时、协议错误、取消和部分启动回滚 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、54 个 Markdown 文件；新增 ADR 和阶段链接通过 |
| `git diff --check` | 0 | 无空白错误；只有既有 LF/CRLF 转换提示 |

### 实现与安全证据

- `Settings.mcp` 只解析 Server ID 和 100–30000 ms 的启动超时；默认 ID 为空，普通应用启动不创建 MCP 进程。
- 不可变 `McpServerConfig` 目录独占 command、args 和绝对 cwd；未知 ID 在进程启动前以 `server_not_allowed` 拒绝，请求层没有启动配置字段。
- FastAPI lifespan 真实执行 `stdio_client -> ClientSession -> initialize()`；本地 `python-knowledge` Server 进入真实 JSON-RPC 初始化链，不是 import 或对象构造证据。
- 每个连接由独立 worker 在同一 Task 中进入和退出 SDK context manager。Manager 超时或取消只发停止信号并等待清理；后启动 Server 失败时已初始化连接也被关闭。
- 进程缺失、超时和协议错误只返回稳定 code 与安全 Server ID。stderr 被隔离，无效 JSON-RPC 的 SDK 堆栈被改写为固定摘要，不暴露原始行或异常文本。
- 证据等级为本地协议与应用生命周期 E3；没有网络或远程 Server E4，也没有工具发现/调用证据。

### 失败尝试、警告与未验证范围

- 首次 `apply_patch` 因新父目录不存在而未应用；随后 `New-Item` 在沙箱中被拒绝，经工作区写权限授权后只创建 `backend/app/integrations/mcp` 目录，再重放补丁成功。
- 一次用于诊断清理异常的内联 Python 命令因 `-c` 引号解析失败；改为 PowerShell here-string 管道后执行成功，没有写临时源码文件。
- 首轮取消测试虽然退出码为 0，但有 4 个 anyio MemoryObjectStream 未关闭警告；未把该结果当作通过证据，改用专属 worker 后以 ResourceWarning 开启模式复验通过。
- 既有 Starlette/httpx 弃用警告仍存在；没有安装 `httpx2` 或升级依赖。
- 未执行 `scripts/verify.ps1` 全量门：本任务未修改依赖/锁文件、HTTP Schema、前端或跨前后端接口，68 项定向回归覆盖 Settings、Container、lifespan 和现有 API 边界。
- 未实现 `list_tools`、Schema/RBAC/命名冲突、`call_tool`、断线重连、调用幂等或 TypeScript Server E2E；分别由 M9-T2、M9-T3 接管，`KI-002` 不能关闭。

### 结论

- `M9-T1` 达到 `verified`：服务端允许配置、真实 SDK STDIO 初始化、FastAPI lifespan、稳定失败、正常关闭、取消和部分回滚均有离线可复现证据。
- `KI-002` 保持 open 但已完成 Client 生命周期部分；下一任务进入 `M9-T2 / planned`，只实现工具发现与共同 ToolDefinition 映射，不提前执行 M9-T3 TypeScript E2E 或 Skill。

## V-20260720-001：M9-T2 工具发现与共同 ToolDefinition 映射

- 任务：`M9-T2`
- 时间：2026-07-20 10:15，Asia/Shanghai
- 验证目标：HEAD `f8b59d2` 上的 M9-T2 工作区；提交由后续本地 commit 固定
- 模式：offline；只启动本地 Python MCP STDIO Server，没有读取真实 API Key、访问网络服务或执行付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；使用已锁定 Python 3.12.10、`mcp==1.28.1`、`openai-agents==0.18.2` 与 LangGraph 环境

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 初始工作区干净且 M9-T1 实现提交 `f8b59d2` 存在；窗口恢复时 9 个 M9-T2 工作区文件与记录一致 |
| M9-T1 handoff 最小恢复命令 | 0 | 9 项生命周期测试通过且无 ResourceWarning；连续性为 52 个稳定任务、55 个 Markdown 文件，未发现漂移 |
| 本地 MCP SDK `list_tools` / `call_tool` 探针 | 0 | 确认 `mcp==1.28.1` 公开分页与调用 API；真实结果含 SDK 生成的 title 元数据、TextContent 与 structuredContent，适配器据此归一化 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_tool_adapter -v` | 0 | 7 项 M9-T2 聚焦测试通过：可信映射、非法/重复/缺失发现、真实调用、三 Runtime、RBAC、超时、错误/上限、allowlist 与冲突 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_tool_adapter backend.tests.test_mcp_client_lifecycle backend.tests.test_settings backend.tests.test_tool_security backend.tests.test_manual_agent_loop backend.tests.test_runtime_comparison backend.tests.test_openai_agents_runtime backend.tests.test_framework_runtimes backend.tests.test_container backend.tests.test_api -q` | 0 | 126 项定向回归通过；覆盖 MCP 生命周期、设置、工具安全、Manual、Agents SDK、LangGraph、容器与 API，无 ResourceWarning |
| `git diff --check` | 0 | 无空白错误；只有既有 LF/CRLF 转换提示 |

### 实现与安全证据

- 冻结 `McpToolPolicy` 由服务端配置独占本地名称、可信描述、角色、风险、副作用与审批策略；远端描述、title、默认值和示例不进入共同工具提示。
- 连接 worker 在拥有 SDK context 的同一 Task 中分页执行 `list_tools` 和 `call_tool`；发现最多 8 页/256 工具，游标、Schema、参数和结果都有结构与字节上限。
- 只映射策略 allowlist 中的远端工具；重复远端名称、缺失配置工具、非法 Schema、跨 Server 本地名称冲突和直接调用未列入工具均稳定失败。
- 归一化后的共同 `ToolDefinition` 沿用 Registry 的参数校验、RBAC 和审批边界；同一定义已实际通过 ManualAgentLoop、OpenAI Agents SDK FunctionTool 与 LangGraphRuntime 执行。
- 调用超时独立配置为 100–30000 ms，默认 5000 ms，不自动重试；结构化结果优先，只接受有界文本回退，远端异常、原始参数和超限结果不进入公共错误。
- 证据等级为本地 Python MCP STDIO 协议与三 Runtime 集成 E3，不是 TypeScript Server E2E 或远程/生产 E4。

### 失败尝试、警告与未验证范围

- 初版专项 6 项测试通过后，代码审阅发现公开 `call_tool` 可绕过映射层直调未列入策略的远端工具；新增边界校验和第 7 项真实 STDIO 用例后复验通过，未接受初版作为最终证据。
- 一次按常见 `pyproject.toml`/requirements 通配路径搜索格式化配置失败；随后从实际文件清单确认仓库没有该配置，未安装或引入格式化工具。
- 测试输出有既有 Starlette/httpx 弃用警告与 Windows asyncio debug 慢任务信息；没有 ResourceWarning、失败或资源泄漏证据，未升级依赖。
- 未执行 `scripts/verify.ps1` 全量门：没有依赖/锁文件、共享 ToolDefinition 公共契约、HTTP Schema、前端或跨前后端接口变化，126 项定向回归覆盖本任务边界。
- 未构建或执行 TypeScript Knowledge Server E2E，也未验证远程 transport、断线重连、健康检查、调用幂等、副作用恢复或生产容量；这些不能由 Python fixture 证据替代。

### 结论

- `M9-T2` 达到 `verified`：真实工具发现、可信映射、共同 Registry、三 Runtime 调用、RBAC、冲突、超时和安全结果均有离线可复现证据。
- `KI-002` 保持 open，但 Python Client 发现/调用部分已完成；下一任务进入 `M9-T3 / planned`，只补 TypeScript Knowledge Server 协议 E2E，不提前执行 Skill 或 M10。

## V-20260720-002：M9-T2 实现提交后恢复锚点

- 任务：`M9-T2`
- 时间：2026-07-20 10:25，Asia/Shanghai
- 验证目标：实现提交 `40b1257`（`feat: add MCP tool adapter`）
- 模式：offline；只启动本地 Python MCP STDIO Server，没有读取真实 API Key、访问网络服务或执行付费调用，费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` | 0 | 实现提交后工作区干净 |
| `git log -3 --oneline` | 0 | `40b1257` 位于 `f8b59d2` 之后，提交边界正确 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_tool_adapter -q` | 0 | 提交后最小恢复集 7 项通过，无 ResourceWarning；仅有 Windows asyncio 慢任务调试行 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、56 个 Markdown 文件通过 |

### 结论

- M9-T2 实现提交固定为 `40b1257`；`V-20260720-001` 的 126 项定向回归、E3 边界与 `verified` 结论不变。
- 当前任务为 `M9-T3 / planned`；只补 TypeScript Knowledge Server 协议 E2E，不重做 M9-T1/M9-T2，不提前进入 Skill 或 M10。

## V-20260720-003：M9-T3 TypeScript Server 协议端到端

- 任务：`M9-T3`
- 时间：2026-07-20 10:53，Asia/Shanghai
- 验证目标：HEAD `c3972b6` 上的 M9-T3 工作区；提交由后续本地 commit 固定
- 模式：offline；只启动本地 TypeScript MCP STDIO Server，没有读取真实 API Key、访问网络服务或执行付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；沿用锁定的 Python 3.12.10、`mcp==1.28.1`、Node 环境、`@modelcontextprotocol/sdk==1.29.0`、Zod 3.25.76 与 TypeScript 7.0.2

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 初始工作区干净；M9-T2 实现 `40b1257` 与验证锚点 `c3972b6` 存在 |
| M9-T2 handoff 最小恢复命令 | 0 | 7 项 MCP 工具适配测试通过且无 ResourceWarning；连续性为 52 个稳定任务、56 个 Markdown 文件，未发现漂移 |
| `npm.cmd run build --prefix mcp-servers/knowledge-server` | 0 | 使用现有 node_modules 与锁文件执行 `tsc`，构建 TypeScript Knowledge Server；没有安装依赖或留下 Git 改动 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_e2e -v` | 0 | 4 项真实 STDIO E2E 通过，覆盖 8 个关键行为：目录策略、initialize/list_tools、Schema、已知/未知调用、非法参数、allowlist 和关闭 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_e2e backend.tests.test_mcp_tool_adapter backend.tests.test_mcp_client_lifecycle backend.tests.test_settings backend.tests.test_container backend.tests.test_api -q` | 0 | 67 项定向回归通过；覆盖 TypeScript/Python MCP、生命周期、设置、Container/FastAPI 与 API，无 ResourceWarning |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、57 个 Markdown 文件；状态、链接和新增 handoff 通过 |
| `git diff --check` | 0 | 无空白错误；只有既有 LF/CRLF 转换提示 |

### 实现与协议证据

- 默认服务端目录新增 `typescript-knowledge`，固定执行 `node build/index.js`、Knowledge Server 绝对 cwd 和可信 `lookup_concept` 策略；默认 MCP 选择仍为空。
- E2E 真实启动构建后的 Node 子进程，通过 Python MCP SDK 完成 initialize、list_tools、共同 ToolDefinition 映射、call_tool 和 context 关闭，没有 import TypeScript 源码或直接调用知识字典。
- 已知 `mcp` 与未知概念均通过共同 ToolRegistry 返回有界 TextContent；远端 description/schema 提示元数据不进入可信定义。
- `{name: 42}` 实际送入 TypeScript Server 并由 Zod 拒绝；Client 只暴露 `remote_tool_error`。未列入策略的工具在调用前以 `tool_not_allowed` 拒绝，错误不含远端校验文本。
- 证据等级为当前 Windows 本地 Node/Python STDIO 互操作 E3，不是远程 transport、跨平台或生产 E4。

### 失败尝试、警告与未验证范围

- 两次组合 `rg` 搜索因 PowerShell 引号处理产生未闭合正则或错误文件参数；随后使用实际文件清单和逐文件读取完成审阅，没有修改文件或依赖。
- 测试输出有既有 Starlette/httpx 弃用警告与 Windows asyncio debug 慢任务信息；没有 ResourceWarning、测试失败或资源泄漏证据，未升级依赖。
- `status.md` 顶部“最近已确认实现提交”仍停在 M8 的 `bd6c09a`，但下方 M9-T1/T2 锚点正确；本轮按可复现提交证据将该动态字段修正为 `40b1257`。
- 未执行 `scripts/verify.ps1` 全量门：没有依赖/锁文件、构建配置、TypeScript 业务逻辑、共享 ToolDefinition 公共契约、HTTP Schema 或前端变化，67 项定向回归覆盖本任务边界。
- 未验证远程 MCP、HTTP/SSE transport、Linux/macOS、断线重连、健康检查、调用幂等、副作用恢复或生产容量；本地 Node 进程不能替代这些证据。

### 结论

- `M9-T3` 达到 `verified`：现有 TypeScript Knowledge Server 构建、初始化、发现、有效/无效调用和关闭均有真实 STDIO 可复现证据。
- `KI-002` 达到关闭条件并标记 `closed`；下一任务进入 `M9-T4 / planned`，只实现只读 Skill Catalog/Resolver，不提前执行上下文注入评测或 M10。

## V-20260720-004：M9-T3 实现提交后恢复锚点

- 任务：`M9-T3`
- 时间：2026-07-20 10:58，Asia/Shanghai
- 验证目标：实现提交 `5aba130`（`test: add TypeScript MCP protocol e2e`）
- 模式：offline；只构建并启动本地 TypeScript MCP STDIO Server，没有读取真实 API Key、访问网络服务或执行付费调用，费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` | 0 | 实现提交后工作区干净 |
| `git log -3 --oneline` | 0 | `5aba130` 位于 M9-T2 验证锚点 `c3972b6` 之后，提交边界正确 |
| `npm.cmd run build --prefix mcp-servers/knowledge-server` | 0 | 提交后 TypeScript build 通过，没有安装依赖或留下 Git 改动 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_e2e -q` | 0 | 提交后最小恢复集 4 项通过，无 ResourceWarning |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、57 个 Markdown 文件通过 |

### 结论

- M9-T3 实现提交固定为 `5aba130`；`V-20260720-003` 的 67 项定向回归、本地 STDIO E3 与 `KI-002 closed` 结论不变。
- 当前任务为 `M9-T4 / planned`；只实现只读 Skill Catalog/Resolver，不重做 MCP Client，不提前执行 M9-T5 或 M10。

## V-20260720-005：M9-T4 只读 Skill Catalog 与 Resolver

- 任务：`M9-T4`
- 时间：2026-07-20 11:16，Asia/Shanghai
- 验证目标：HEAD `83a5234` 上的 M9-T4 工作区；提交由后续本地 commit 固定
- 模式：offline；只读取仓库 Skill 与测试临时目录，没有读取真实 API Key、访问网络服务、执行 Skill 脚本或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；只使用 Python 3.12.10 标准库与现有 unittest 环境

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 初始工作区干净；M9-T3 实现 `5aba130` 与验证锚点 `83a5234` 存在 |
| M9-T3 handoff 最小恢复命令 | 0 | TypeScript build、4 项 MCP E2E 与 52 个稳定任务/57 个 Markdown 连续性检查通过，无 ResourceWarning 或漂移 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_skill_catalog -v`（首轮） | 0 | 9 项通过、1 项因 Windows 无法创建 symlink 跳过；该轮不作为最终符号链接拒绝分支证据 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_skill_catalog -v`（最终） | 0 | 10 项全部通过；真实加载现有 Skill/reference，并覆盖触发、缓存、frontmatter、逃逸、超限、UTF-8、symlink 拒绝分支和禁止脚本执行 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_skill_catalog backend.tests.test_code_agent -q` | 0 | 共运行 17 项：16 项通过、1 项既有 Code Agent Windows symlink 能力测试跳过；无失败 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、58 个 Markdown 文件；状态、链接和新增 handoff 通过 |
| `git diff --check` / 新增文件尾随空白 `rg` | 0 | 无空白错误；tracked 文件只有既有 LF/CRLF 转换提示 |

### 实现与安全证据

- `default_skill_catalog()` 固定扫描仓库 `skills` 根目录；可注入 root 的构造函数只供服务端装配与临时目录测试，不进入 HTTP、模型参数或 Skill 元数据。
- Catalog 使用严格的两字段标量 frontmatter 子集，不调用通用 YAML loader；标签、集合、未知/重复字段、目录名不一致、控制字符和超限内容均稳定拒绝。
- 只读取 `SKILL.md` 与正文显式引用的 `references/*.md`；现有 `research-summary` 和 `output-contract.md` 已真实加载，`agents/openai.yaml` 与测试 Python 文件未加载或执行。
- 文件读取在 canonical root 下逐组件拒绝 symlink，拒绝绝对/反斜杠/百分号/查询/`..` 引用，并限制 Skill 数、单文件、引用数、总字节和查询长度。
- 冻结 Skill/reference dataclass 与 tuple 构成不可变缓存快照；`load()` 重用快照，`refresh()` 才重新扫描。Resolver 支持 `$name` 显式触发和全部名称词元自动匹配，未知显式名 fail closed。
- 所有 Catalog/Resolver 异常只暴露稳定 code，不包含原始路径、查询、文件内容或解析异常。

### 失败尝试、警告与未验证范围

- 首次创建 `backend/app/skills` 被工作区沙箱拒绝；取得仅该目录创建授权后成功，没有写入工作区外文件。
- 当前 Windows 环境对测试临时文件 `symlink_to()` 返回 errno 22。最终测试保留真实创建尝试，并在环境不支持时受控覆盖同一 `Path.is_symlink()` 拒绝分支；真实 `../` 和嵌套路径逃逸仍由实际文件系统验证。
- 定向回归的 1 项 skip 来自既有 Code Agent symlink 能力测试；不是 M9-T4 新测试。不得把本轮证据描述为 Windows OS 级符号链接实测通过。
- 未执行 `scripts/verify.ps1` 全量门：没有依赖/锁文件、公共 Runtime 契约、HTTP Schema、前端或跨模块接口变化，10 项聚焦和 17 项路径安全定向集覆盖本任务边界。
- 未实现 Skill Runtime 上下文注入、触发效果/成本对照、热更新监听、跨进程缓存、文件变更原子快照或管理员写入流程；M9-T5 只接管上下文与评测，其余不属于当前课程纵切。

### 结论

- `M9-T4` 达到 `verified`：现有 Skill 真实加载、严格元数据、引用边界、缓存、显式/自动触发和稳定错误均有离线可复现证据。
- 下一任务进入 `M9-T5 / planned`，只实现有界 SkillContext 注入与固定效果/成本评测，不提前执行 M9-T6 里程碑验收或 M10。

## V-20260720-006：M9-T4 实现提交后恢复锚点

- 任务：`M9-T4`
- 时间：2026-07-20 11:21，Asia/Shanghai
- 验证目标：实现提交 `de8a63d`（`feat: add read-only skill catalog`）
- 模式：offline；只读取仓库 Skill 与测试临时目录，没有读取真实 API Key、访问网络服务、执行 Skill 脚本或产生付费调用，费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` | 0 | 实现提交后工作区干净 |
| `git log -3 --oneline` | 0 | `de8a63d` 位于 M9-T3 验证锚点 `83a5234` 之后，提交边界正确 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_skill_catalog -q` | 0 | 提交后最小恢复集 10 项通过，无 ResourceWarning |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、58 个 Markdown 文件通过 |

### 结论

- M9-T4 实现提交固定为 `de8a63d`；`V-20260720-005` 的 17 项定向集、symlink 证据边界与 `verified` 结论不变。
- 当前任务为 `M9-T5 / planned`；只实现有界 SkillContext 注入与固定离线评测，不重做 Catalog/Resolver，不提前执行 M9-T6 或 M10。

## V-20260720-007：M9-T5 Skill Runtime 上下文与离线评测

- 任务：`M9-T5`
- 时间：2026-07-20 14:12，Asia/Shanghai
- 验证目标：HEAD `c820c7e` 上的 M9-T5 工作区；提交由后续本地 commit 固定
- 任务等级：开始时按 handoff 预估为 B；只读设计发现需要扩展共享 `RuntimeRequest` 并接入三 Runtime 后，按协议上调为 A，时间盒 2–4 小时
- 模式：offline；只读取仓库 Skill、启动本地测试进程和执行本地构建，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；使用 Python 3.12.10、现有 LangGraph/OpenAI Agents SDK、Node/npm、Docker CLI 与仓库锁定依赖

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 初始工作区干净；M9-T4 实现 `de8a63d` 与验证锚点 `c820c7e` 存在 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_skill_catalog -q` | 0 | M9-T4 恢复集 10 项通过 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1`（恢复） | 0 | 52 个稳定任务、58 个 Markdown 文件通过，无漂移 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_skill_context -v` | 0 | 10 项新增关键测试全部通过；覆盖上下文上限、路径脱敏、触发、三 Runtime、权限/审批/Schema 与固定评测 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.skill_context` | 0 | 固定 LangGraph 离线评测 2/2 通过；触发上下文 3153 字节、启发式 789 Token，不触发增加 0 字节；Provider usage 不可用、美元成本 `null` |
| 12 模块 Runtime/Skill/Container/工具安全定向回归 | 0 | 151 项全部通过；只有既有 Starlette/httpx 弃用提示、测试预期 notifier 日志和一次 asyncio 慢回调诊断 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1`（首轮） | 1 | 后端 294 项中 292 项通过、1 项既有 Windows symlink 能力跳过、1 项 TypeScript MCP E2E 在 `manager.start()` 命中 `startup_timeout`；脚本按 fail-fast 停在后端门 |
| 单独重跑失败的 `test_calls_known_and_unknown_concepts_through_registry` | 0 | 1 项通过，真实本地 Node STDIO 进程正常初始化、调用和关闭，未修改代码或超时配置 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1`（第二轮） | 0 | 后端 294 项中 293 项通过、1 项既有 Windows symlink 能力跳过；Code Agent Demo、`pip check`、Vue production build、MCP TypeScript build 与 Docker Compose 配置门全部通过 |
| 最终边界收紧后的 Skill/Runtime/Manual/SDK/Container 定向回归 | 0 | 75 项全部通过；直接调用 Manual/SDK helper 也复用 32,000 字节与控制字符校验 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1`（最终工作区） | 1 | 后端 294 项中 293 项通过、1 项既有 symlink skip；Code Agent Demo 与 `pip check` 通过，随后沙箱拒绝写 `frontend/tsconfig.app.tsbuildinfo`，Vue 门以 `EPERM` 中断 |
| `npm.cmd run build`（`frontend`，仅为绕过工作区构建产物写权限而经批准在沙箱外重跑） | 0 | `vue-tsc -b && vite build` 通过，18 个模块完成生产构建；没有安装依赖 |
| `npm.cmd run build`（`mcp-servers/knowledge-server`） | 0 | TypeScript `tsc` build 通过 |
| `docker compose -f deploy/compose.yaml config --quiet` | 0 | Compose 配置通过；沙箱无法读取用户目录 Docker `config.json`，打印 access denied warning，但未连接 Engine |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1`（ADR/阶段文档后） | 0 | 52 个稳定任务、59 个 Markdown 文件通过 |
| `git diff --check` / 新增文件尾随空白 `rg` | 0 | 无空白错误；tracked 文件只有既有 LF/CRLF 转换提示 |

### 实现与安全证据

- `SkillContextBuilder` 从冻结 Resolver 快照生成确定性 JSON，最多 4 个 Skill、24,000 UTF-8 字节；reference 内容内嵌但源路径替换为稳定编号，片段明确不能改变身份、角色、审批、工具或 Schema。
- `RuntimeRequest.prompt_context` 隐藏 repr、最大 32,000 字节，并放在既有 `execution_context` 位置参数之后；兼容测试证明旧第三位置参数仍绑定可信工具上下文。
- 默认 Container 用 `SkillAwareRuntime` 包装内建 Manual、Agents SDK 与 LangGraph；无匹配时原请求对象原样传递，未知显式 Skill fail closed 且不调用 delegate。
- Manual 和 LangGraph 使用独立 system message，SDK 默认 factory 使用 agent instructions；三条路径都保留原始用户输入，工具定义对照不变。
- 恶意测试 Skill 明示要求绕过控制时，共同 Registry 仍分别返回 `permission_denied`、`approval_required` 和 `invalid_arguments`，三个 handler 均未执行。
- 固定效果评测真实执行 LangGraph `ainvoke()` Runtime 路径，但模型是确定性离线 fixture；证据等级为 E3 应用契约，不是 Provider E4。

### 失败、警告与未验证范围

- 全量首轮的 TypeScript MCP `startup_timeout` 在不改代码、不提高超时的单项重跑和全量重跑中均通过，判定为本地进程启动时序波动；保留首轮失败事实，不登记为稳定代码漂移。
- 最终工作区全量脚本的 Vue 步骤因沙箱拒绝写 TypeScript build info 而失败；相同 `npm.cmd run build` 经批准在沙箱外退出 0，后续 MCP build 和 Compose 配置也分别退出 0。不得把脚本退出 1 改写成单次完整通过。
- 全量仍有 1 项既有 Code Agent symlink 测试因 Windows 能力跳过；M9-T4 的 symlink 证据边界不变。
- Starlette/httpx 弃用提示、测试主动触发的 notifier warning 和 asyncio debug 慢回调不影响退出码；没有安装提示中的新依赖。
- 3153 字节和 789 Token 仅对应当前固定 `research-summary` 片段；Token 是 `ceil(UTF-8 bytes / 4)` 启发式。没有 Provider tokenizer、真实 usage、定价或账单证据，`KI-018` 保持 open。
- 没有执行真实模型，未验证在线指令遵循、Provider strict schema/streaming/usage、真实质量、费用或资源清理；没有实现 Skill 写接口、自动刷新、审批恢复、热加载或持久成本账本。

### 结论

- `M9-T5` 达到 `verified`：受控 Skill 上下文已进入默认三 Runtime 的真实应用路径，固定触发/不触发效果与提示开销可离线复现，权限、审批和工具 Schema 不变性有自动化证据。
- 下一任务进入 `M9-T6 / planned`，只汇总 M9 跟练、速查、自测、费曼材料和里程碑验收；不得提前进入 M10，也不得把本次离线 fixture 描述为真实模型证据。

## V-20260720-008：M9-T5 实现提交后恢复锚点

- 任务：`M9-T5`
- 时间：2026-07-20 14:22，Asia/Shanghai
- 验证目标：实现提交 `a6ff518`（`feat: inject bounded skill runtime context`）
- 模式：offline；只读取仓库 Skill 并执行本地 Python/LangGraph 路径，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` | 0 | 实现提交后工作区干净 |
| `git log -3 --oneline` | 0 | `a6ff518` 位于 M9-T4 验证锚点 `c820c7e` 之后，提交边界正确 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_skill_context -q` | 0 | 提交后最小恢复集 10 项通过，无 ResourceWarning |
| `.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.skill_context` | 0 | 固定评测 2/2 通过；触发 3153 字节/启发式 789 Token，不触发增加 0；Provider usage 不可用、美元成本 `null` |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、60 个 Markdown 文件通过 |

### 结论

- M9-T5 实现提交固定为 `a6ff518`；`V-20260720-007` 的 151 项定向回归、后端 294 项、构建/配置门、失败尝试和 E3 证据边界不变。
- 当前任务为 `M9-T6 / planned`；只盘点并汇总 M9 跟练与里程碑验收，不重做 M9-T1–M9-T5，不提前进入 M10。

## V-20260720-009：M9-T6 课程与里程碑验收

- 任务：`M9-T6`
- 时间：2026-07-20 14:40，Asia/Shanghai
- 验证目标：HEAD `19b5596` 上的 M9-T6 课程工作区；课程提交由后续本地 commit 固定
- 任务等级：B 类里程碑课程验收，时间盒 60-90 分钟；没有修改 Runtime、测试代码、依赖或公共契约
- 模式：offline；只读取仓库 Skill、启动本地 Python/Node STDIO 进程并执行本地构建，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；沿用现有 Python 3.12.10、Node/npm、MCP SDK、LangGraph、Vue 和 Docker CLI 环境

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 初始工作区干净；M9-T5 实现 `a6ff518` 与验证锚点 `19b5596` 存在 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_skill_context -q` | 0 | handoff 最小恢复集 10 项通过 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.skill_context`（恢复） | 0 | 固定评测 2/2；触发上下文 3153 字节/启发式 789 Token，不触发为 0；Provider usage 不可用、费用 `null` |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1`（恢复） | 0 | 52 个稳定任务、60 个 Markdown 文件通过，代码与记录无漂移 |
| `npm.cmd run build --prefix mcp-servers/knowledge-server` | 0 | 使用现有依赖完成 TypeScript `tsc` build，没有安装依赖 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_lifecycle backend.tests.test_mcp_tool_adapter backend.tests.test_mcp_client_e2e backend.tests.test_skill_catalog backend.tests.test_skill_context -v` | 0 | M9 聚焦 40 项全部通过；真实启动本地 Python/Node STDIO Server，覆盖 initialize、发现、调用、关闭、路径与上下文边界，无 ResourceWarning |
| `.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.skill_context`（里程碑） | 0 | 固定 LangGraph 离线评测再次 2/2；数值与恢复证据一致 |
| `rg` 检查 M9-T6 必需章节与一页速查表结构 | 0 | 对照、roots、四次跟练、三类题库、速查、费曼、30 项映射、最终清单和速查表八个章节均存在 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1`（沙箱内首轮） | 1 | 后端 294 项中 293 项通过、1 项既有 Windows symlink 能力跳过；Code Agent Demo 与 `pip check` 通过，随后 Vue 无法写 `tsconfig.app.tsbuildinfo`，以 `EPERM` 中断 |
| 同一 `scripts/verify.ps1` 经工作区构建权限批准后在沙箱外重跑 | 0 | 后端 294 项结果一致；Code Agent Demo、`pip check`、Vue 18 模块 production build、MCP TypeScript build 与 Docker Compose 配置门全部通过 |
| `git diff --check` / `scripts/check-continuity.ps1`（课程与连续性记录后） | 0 | 阶段/速查材料后为 52 个稳定任务、61 个 Markdown；最终 status/handoff 落盘后为 52/62，相对链接与映射通过；无空白错误，只有既有 LF/CRLF 转换提示 |
| `rg -n "TBD\|TODO\|PLACEHOLDER\|待补\|待定\|计划命令\|npm install" ...` | 1 | 预期无匹配；M9-T6 课程、速查、映射、status 和 handoff 不含占位符或安装指令 |

### 课程与验收证据

- 阶段 09 现按 M9-T1 至 M9-T5 串成四次、共 8-12 小时的跟练，包含真实工作映射、产物、通关标准和故障注入，不重复改写已验证 Runtime。
- 独立协议练习明确先构建 TypeScript Server，再由 Python `McpClientManager` 从服务端目录拉起 Node 进程，分别执行 discovery 和 call 测试；没有用直接 import 或依赖存在代替协议执行。
- MCP、Function Calling 与 Skill 对照表区分结构化调用、跨进程协议和任务上下文；共同 `ToolDefinition`/Registry 的安全复用与不负责范围均有说明。
- roots 章节明确声明本仓库当前未协商 roots，并说明 roots 是协议协调信息而非 OS 权限或沙箱；实际文件边界仍依赖服务端固定配置、canonical path、symlink 检查和最小 OS 权限。
- 新增独立一页速查表，包含两条主链、选择规则、信任边界、E1-E4、稳定错误、精确命令和五问自检。
- 题库包含 5 道概念题、4 道实操题、4 道工作场景题和 100 分评分规则；80 分通关，并设置 import 伪证据、roots 沙箱、信任远端数据、无幂等重试、Skill 执行和虚构 usage/cost 等安全红线。
- 费曼任务要求讲清完整协议链、三者差异、roots 边界和 E3 上限；阶段映射引用全局 30 项真相源，并把 M9-T6 纳入主题 07/08 的静态任务索引。

### 失败、警告与未验证范围

- ADR-0010 首次按摘要猜测的文件名读取失败；列出实际目录后使用 `ADR-0010-bounded-skill-runtime-context.md` 重读，内容与状态一致。ADR-0009 首次读取使用 PowerShell 默认编码而失真，改用 UTF-8 后正常；两者均未产生仓库修改。
- 最终状态复核发现 `status.md` 的“未验证范围”仍保留 M9-T4 时期“尚未注入 Runtime”的旧句，与 M9-T5 代码和 `V-20260720-007` 冲突；按可复现证据优先登记后在本任务状态闭环中删除该陈旧项。
- 全量首轮只因沙箱拒绝写工作区内 Vue `tsbuildinfo` 失败；没有把该退出 1 改写成成功。相同完整脚本在获准的沙箱外环境退出 0，不需要拆分推断。
- 全量仍有 1 项既有 Code Agent Windows symlink 能力测试跳过；M9-T4 的实际路径逃逸测试和受控 symlink 分支证据不变，不能宣称当前 OS 已完成真实 symlink 实测。
- 聚焦与全量输出有既有 Starlette/httpx 弃用提示、预期 notifier warning 和 Windows asyncio debug 进程诊断；没有 ResourceWarning 或失败，不安装提示中的新依赖。
- Compose 只验证配置展开，没有启动 Docker Engine、镜像、容器、远程 MCP 或生产 transport；没有验证 Linux/macOS、断线重连、健康恢复、调用幂等、副作用恢复或生产容量。
- Skill 评测仍使用确定性离线 fixture；没有真实模型指令遵循、Provider tokenizer/usage、定价或账单，`KI-018` 保持 open。
- 学习者个人尚未完成题库、速查练习或费曼复述；课程工程验收不会代替 `docs/progress.md` 中的个人勾选。

### 结论

- `M9-T6` 达到 `verified`：完整跟练、MCP/Function Calling/Skill 对照、roots 安全边界、三类考核、一页速查、费曼任务、30 项映射和里程碑离线全量门均有可复现证据。
- M9 工程与课程达到 `verified`；该状态只代表当前本地 E3 与课程门，不代表远程或生产 E4，也不代表学习者个人已经通关。
- 下一任务进入 `M10-T1 / planned`；只实现可持久 StateGraph 与 Checkpointer，不修改已验证 M9 Runtime，不提前实现 M10-T2 interrupt/resume。

## V-20260720-010：M9-T6 课程提交后恢复锚点

- 任务：`M9-T6`
- 时间：2026-07-20 14:45，Asia/Shanghai
- 验证目标：课程提交 `fdeb9b5`（`docs: complete M9 course acceptance`）
- 模式：offline；只构建并启动本地 Python/Node STDIO 路径、读取仓库 Skill，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 课程提交后工作区干净；`fdeb9b5` 位于 M9-T5 锚点 `19b5596` 之后 |
| `npm.cmd run build --prefix mcp-servers/knowledge-server` | 0 | 提交后 TypeScript `tsc` build 通过，没有安装依赖 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_lifecycle backend.tests.test_mcp_tool_adapter backend.tests.test_mcp_client_e2e backend.tests.test_skill_catalog backend.tests.test_skill_context -q` | 0 | M9 提交后恢复集 40 项通过，无 ResourceWarning；只有既有 Starlette/httpx 弃用提示 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.skill_context` | 0 | 固定评测 2/2；触发 3153 字节/启发式 789 Token，不触发为 0；Provider usage 不可用、费用 `null` |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、62 个 Markdown 文件通过 |

### 结论

- M9-T6 课程提交固定为 `fdeb9b5`；`V-20260720-009` 的 40 项聚焦、后端 294 项、全量构建/配置门、首次沙箱失败和 E3 边界不变。
- 当前任务为 `M10-T1 / planned`；不重做 M9，不提前实现 M10-T2 interrupt/resume，不把共享内存 checkpointer 描述成进程重启持久化。

## V-20260720-011：M10-T1 共享内存 Checkpoint 纵切

- 任务：`M10-T1`
- 时间：2026-07-20 15:16，Asia/Shanghai
- 验证目标：HEAD `c4d4efe` 上的 M10-T1 工作区；实现提交由后续本地 commit 固定
- 任务等级：A 类共享 Runtime/Coordinator 契约变更，时间盒 2–4 小时
- 模式：offline；只执行本地 LangGraph、Mock、Store、构建和配置路径，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；使用仓库现有 Python 3.12.10、LangGraph 1.2.9 与 langgraph-checkpoint 4.1.1

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 初始工作区干净；M9-T6 课程提交 `fdeb9b5` 与验证锚点 `c4d4efe` 存在 |
| M9-T6 handoff 恢复命令 | 0 | TypeScript build、M9 聚焦 40 项、固定 Skill 评测 2/2 与 52 个稳定任务/62 个 Markdown 连续性检查通过，无漂移或 ResourceWarning |
| 仓库虚拟环境中的 LangGraph `InMemorySaver` API 探针 | 0 | 不设置自定义顶层 namespace 时，失败节点前一 superstep 保存 `invocation_count=1`；使用相同 thread 的下一次 `ainvoke()` 恢复并推进到 2；`context_schema` 中的瞬时值未进入 checkpoint |
| `python -m unittest backend.tests.test_runtime_contract backend.tests.test_run_coordinator` | 1 | PATH 首先命中 WindowsApps `python.exe`，报“指定的登录会话不存在”，测试没有启动；改用仓库 `.venv` 后通过，未修改系统配置 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_runtime_contract backend.tests.test_run_coordinator -q` | 0 | 实现中途冒烟 31 项通过；三条 notifier 日志来自既有负向用例 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_checkpointing -v` | 0 | 10 项新增关键测试全部通过，覆盖稳定线程、跨 Runtime 恢复、用户隔离、缺失上下文、节点失败、版本/作用域拒绝、脱敏、真实 LangGraph 工具链与 Coordinator 注入 |
| 7 模块 Checkpoint/Runtime/Coordinator/Skill/Container 定向回归 | 0 | 73 项全部通过；只有既有 Starlette/httpx 弃用提示和 notifier 负向日志，无 ResourceWarning |
| `.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 7 项手写 Loop 测试通过，证明 checkpoint 模块未污染 M1 顶层导入 |
| `.\.venv\Scripts\python.exe -S -X utf8 -B -m backend.app.demo` | 0 | 禁用 `site-packages` 后 Demo 仍输出 start、tool start/completed 与 run completed |
| 摘要化 owner 上下文后的 Checkpoint/Skill/Coordinator 回归 | 0 | 39 项通过；原始 `owner_id` 不再进入 Runtime 请求上下文，只保留 owner/thread 摘要 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1`（沙箱内首轮） | 1 | 后端 304 项中 303 项通过、1 项既有 Windows symlink 能力跳过；Code Agent Demo 与 `pip check` 通过，随后 Vue 因沙箱拒绝写 `tsconfig.app.tsbuildinfo` 以 `EPERM` 中断 |
| 同一 `scripts/verify.ps1` 经工作区构建权限批准后在沙箱外重跑 | 0 | 后端结果一致；Code Agent Demo、依赖、Vue 18 模块 production build、MCP TypeScript build 与 Docker Compose 配置门全部通过 |
| `scripts/check-continuity.ps1` / `git diff --check` / 占位符扫描 | 0 | ADR、状态和 handoff 后为 52 个稳定任务、64 个 Markdown；相对链接与映射通过，无空白错误或占位符，只有既有 LF/CRLF 转换提示 |

### 实现与安全证据

- `RuntimeCheckpointContext.for_run()` 由 Coordinator 使用持久 Run 的可信 `owner_id` 和 `run_id` 派生固定 owner/thread 摘要；客户端没有 thread 注入入口，错 Run 上下文在 `RuntimeRequest` 构造时拒绝。
- `CheckpointedLangGraphRuntime` 独立包装现有 `AgentRuntime`，持有共享 `InMemorySaver` 并只编译一次真实 `StateGraph`；两个 Runtime 实例复用同一 saver 和 thread 时，第二次调用从 1 恢复并推进到 2。
- checkpoint schema 固定 `state_version=1`、owner scope、调用计数和标准化终态；未知版本、错 owner scope 和损坏计数 fail closed。当前迁移边界是“只接受当前版本”，没有静默猜测或原地升级。
- request、Skill prompt、事件 sink、取消控制和 delegate 通过 LangGraph `context_schema` 瞬时传递；自动化检查确认原始 owner、输入和 prompt 不进入 checkpoint 表示。
- delegate 节点异常只返回稳定 `checkpoint_node_failed`，不保留原始异常；前一 `advance` superstep 已被保存，后续同 thread 调用能恢复。`StoreError` 与外层任务取消继续原样传播，不触发隐藏重试。
- 真实纵切不是 import 证据：测试实际执行外层 checkpoint graph 的 `ainvoke()`，再调用现有 `LangGraphRuntime` 完成 `MockModel -> add_numbers -> tool events -> terminal result`。
- 现有简单 `LangGraphRuntime`、Container 默认 Runtime 选择与 M1 顶层导出保持不变；M10-T1 新 Runtime 只通过显式组合启用，不提前迁移默认主链。

### 失败、警告与未验证范围

- 首个 API 探针把 `checkpoint_ns="m10"` 当作顶层 namespace，`aget_state()` 返回 `ValueError: Subgraph m10 not found`；改为只设置 server-derived `thread_id` 后实际恢复通过，因此实现没有保留错误 namespace 方案。
- 一个早期 context 探针把测试 secret 同时写进 answer，无法区分 state 与 context 持久化；该轮判定为无效证据，改为固定安全 answer 后确认 context 未持久化。另一个无 entrypoint 的只读图探针报 `ValueError: Graph must have an entrypoint`，没有据此作结论。
- 全量首轮只因沙箱拒绝 Vue build info 写入而失败；没有把退出 1 改写成成功。相同完整脚本经批准在沙箱外退出 0。
- 全量仍有 1 项既有 Code Agent Windows symlink 能力测试跳过；既有 Starlette/httpx 弃用提示、notifier warning 和 Windows asyncio 调试诊断不影响退出码，没有安装提示中的依赖。
- `InMemorySaver` 只证明同一进程、共享对象、跨 invocation 恢复；没有验证进程重启、多进程、PostgreSQL、checkpoint 加密、容量或清理策略。真正重启持久化属于 M11。
- 没有实现或验证 interrupt、`Command(resume=...)`、审批状态机、重复 resume、副作用恰好一次、重规划或多 Agent；这些分别属于 M10-T2 及后续任务。
- 没有验证同一 thread 的跨进程并发写入；当前 Coordinator 单进程 singleflight 仍是并发边界。checkpoint 写入结果未知时不会自动重试有副作用 delegate。

### 结论

- `M10-T1` 达到 `verified`：稳定 graph state、服务端 owner/thread 绑定、共享内存 checkpointer、版本拒绝边界、跨 Runtime invocation 恢复、隔离和失败恢复均有真实 LangGraph 自动化证据。
- 下一任务进入 `M10-T2 / planned`，只设计并实现 interrupt/审批 resume 与重复恢复幂等；不得把本次内存证据描述成进程重启持久化，也不得提前进入 M10-T3 重规划。

## V-20260720-012：M10-T1 实现提交后恢复锚点

- 任务：`M10-T1`
- 时间：2026-07-20 15:22，Asia/Shanghai
- 验证目标：实现提交 `b6dfa0b`（`feat: add versioned LangGraph checkpoints`）
- 模式：offline；只执行本地 LangGraph、Skill 与标准库路径，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -3 --oneline` | 0 | 实现提交后工作区干净；`b6dfa0b` 位于 M9-T6 验证锚点 `c4d4efe` 之后 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_checkpointing backend.tests.test_skill_context -q` | 0 | handoff 最小恢复集 20 项通过，无 ResourceWarning |
| `.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过，LangGraph 模块仍未污染顶层导入 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、64 个 Markdown 文件通过 |

### 结论

- M10-T1 实现提交固定为 `b6dfa0b`；`V-20260720-011` 的 10 项专项、73 项定向回归、后端 304 项全量门、失败尝试和同进程证据边界不变。
- 当前任务为 `M10-T2 / planned`；不重做 checkpoint 纵切，不把 `InMemorySaver` 描述成进程重启持久化，不提前进入 M10-T3。

## V-20260720-013：M10-T2 服务端审批 Interrupt 与 Resume

- 任务：`M10-T2`
- 时间：2026-07-20 16:06，Asia/Shanghai
- 验证目标：HEAD `cdc9436` 上的 M10-T2 工作区；实现提交由后续本地 commit 固定
- 任务等级：A 类共享 Runtime/EventStore/Coordinator 契约变更，时间盒 2–4 小时
- 模式：offline；只执行本地 LangGraph、Mock、内存 Store、构建和配置路径，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；使用仓库现有 LangGraph 1.2.9 与 langgraph-checkpoint 4.1.1

### 恢复与设计核对

- 开始时 `git status --short` 干净；最近提交为 `cdc9436`、`b6dfa0b`、`c4d4efe`、`fdeb9b5`、`19b5596`、`a6ff518`，未重做 M10-T1。
- 按顺序阅读 AGENTS、continuity README/status/playbook、实施计划 M10-T2/M10-T3、Stage 10、ADR-0003/0006/0007/0011、最新 handoff、V-011/V-012 和后端规约；实际代码与记录一致，无需登记漂移。
- handoff 恢复集通过：Checkpoint/Skill 20 项、禁用 `site-packages` 的 M1 7 项、52 个稳定任务/64 个 Markdown；无 ResourceWarning。
- 只读核对已安装公共 API：`interrupt(value)` 和 `Command(resume=...)`；实际最小图证明首次返回 interrupt、snapshot 处于待执行节点，resume 后节点只执行一次，终态再次 resume 不重复执行。

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 初始工作区干净，当前基线 `cdc9436`，提交边界正确 |
| handoff 的 Checkpoint/Skill、M1 与连续性恢复命令 | 0 | 20 项、7 项、52 个任务/64 个 Markdown 通过，代码与记录无漂移 |
| `python -m unittest ...` | 1 | PATH 命中 WindowsApps `python.exe`，报“指定的登录会话不存在”；测试未启动，改用仓库 `.venv`，未改全局配置 |
| `.\.venv\Scripts\python.exe -m py_compile ...` | 1 | 沙箱拒绝写既有 `__pycache__` 临时 pyc；随后统一使用 `-B` 的真实 import/unittest 验证，不把该次记为通过 |
| `.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_langgraph_approval_resume backend.tests.test_run_store_contract`（首轮） | 1 | 40 项中 39 项通过；跨 Coordinator 重复 resume 的后到者读到 `running` 后误报非法转换，修复为等待持久终态 |
| 同一审批与 Store 专项重跑 | 0 | 40 项通过；增加 resume 重放和 pause/resume 故障原子性后最终为 41 项通过 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_approval_resume backend.tests.test_run_store_contract backend.tests.test_tool_security backend.tests.test_run_coordinator backend.tests.test_langgraph_checkpointing -q` | 0 | 83 项定向回归通过，无 ResourceWarning；三条 notifier 日志来自既有负向用例 |
| `.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q`（初轮） | 1 | 新审批 Runtime 曾从 `backend.app.agent` 顶层导出，禁用 site-packages 后因找不到 LangGraph 导入失败；移除顶层导出后重跑通过 |
| 同一 M1 隔离命令（修复后） | 0 | 手写 Loop 7 项通过，专用审批 Runtime 继续显式导入 |
| `.\.venv\Scripts\python.exe -B -W always::ResourceWarning -m unittest discover -s backend/tests -p "test_*.py"` | 0 | 文档前后端全量前的后端快照 314 项通过、1 项既有 Windows symlink 条件跳过；新增 Store 故障用例后统一脚本最终为 315 项通过、1 项跳过 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1`（沙箱首轮） | 1 | 后端 315 项、Code Agent Demo 与 `pip check` 通过；Vue 写 `tsconfig.app.tsbuildinfo` 被沙箱以 `EPERM` 拒绝，脚本真实退出 1 |
| 同一 `scripts/verify.ps1` 经工作区构建权限批准后重跑（通知竞态补丁前） | 0 | 后端 315 项通过、1 项既有 symlink 跳过；Code Agent Demo、依赖、Vue 18 模块 production build、MCP TypeScript build 与 Docker Compose 配置门全部通过 |
| 提交前通知竞态专项与 5 模块定向回归 | 0 | 新增“waiting 通知后立即 resume”用例；审批/Store 42 项、定向 85 项通过，无 ResourceWarning |
| 通知竞态补丁后再次受控运行同一 `scripts/verify.ps1` | 0 | 后端 316 项通过、1 项既有 symlink 跳过；Code Agent Demo、依赖、Vue、MCP TypeScript 与 Compose 配置门全部通过 |
| 普通 Runtime 上下文兼容性收口后的最终 `scripts/verify.ps1` | 0 | 只对审批 Runtime 绑定 Run；后端仍为 316 项通过、1 项既有 symlink 跳过，其余离线构建与配置门全部通过 |
| 最终专项、M1 与 `scripts/check-continuity.ps1` 恢复检查 | 0 | 审批/Store 42 项、M1 7 项、52 个稳定任务/66 个 Markdown 通过，无 ResourceWarning |

### 实现与安全证据

- `RuntimeResult` 保持终态；`RuntimeApprovalPause`、`RuntimeApprovalResume` 和 `ApprovalResumableRuntime` 显式扩展暂停/恢复契约。现有 Runtime 无需伪装 waiting 结果。
- `PauseCommit` 与 `ResumeCommit` 在固定 Run→Event 锁顺序下原子提交 `waiting_approval`/`running` 与对应生命周期事件；普通 append 拒绝绕过入口，故障注入证明发布前失败时两边均不改变。
- `ApprovalLangGraphRuntime` 真实执行 `prepare -> interrupt -> Command(resume) -> execute`。prepare 在暂停前固定服务端工具调用；恢复不会重新运行 planner，新 Runtime/Coordinator 实例复用同一 saver/store 后可继续。
- ApprovalRequest 绑定 Run、principal、call、tool 和规范参数摘要；原始参数只存服务端私有内存。checkpoint、Run 事件和 repr 脱敏测试均未出现测试 secret。
- `approve` 生成精确 Run-bound grant，最终仍由 `ToolRegistry` 消费一次；`reject`、服务端过期、错 call/tool/digest、Python 布尔 decision、并发跨 Coordinator 重复 resume 和终态重放均不重复调用 handler。
- 只有 `commit_resume(created=true)` 的赢家调用 Runtime；后到执行者等待持久终态。等待审批 Run 可以取消且不会执行工具。
- 新 LangGraph 模块只支持显式导入；修复后 `python -S` 的 M1 学习路径继续无第三方依赖运行。默认 Container、旧 HTTP/SSE、简单 LangGraph 和 Agents SDK Runtime 未迁移。

### 失败、警告与未验证范围

- 两个早期多行 API 探针分别因 PowerShell 引号产生 `SyntaxError: unterminated string literal` 和 `SyntaxError: invalid syntax`；最终用临时完整脚本执行真实图后删除临时文件，结论由专项自动化测试继续固定。
- 一次读取假定存在的 `backend/app/agent/base.py` 失败，随后用 `rg --files` 按真实结构定位到 `runtime.py`；一次 Windows wildcard `rg` 路径展开失败，改为真实文件路径，没有据此修改代码。
- 首个大补丁因导入上下文与实际文件不符被 `apply_patch` 整体拒绝；另一次导出补丁把名称落到 `__all__` 结束括号外，立即通过只读检查发现并修正，未进入测试或提交。
- 提交前审查发现 waiting 事件已通知、execute task 尚未退出时，立即 resume 会误共享旧 task 并只返回 waiting。为 active task 增加 execute/resume 阶段标记，resume 等待 execute 收尾后自动继续；新增通知窗口用例后专项、定向和全量均重跑通过。
- 全量首轮只因沙箱拒绝 Vue build info 写入而失败；保留退出 1，相同完整脚本经批准在沙箱外退出 0。既有 Starlette/httpx 弃用提示、notifier 负向日志和 Windows asyncio 调试诊断不影响退出码，没有安装提示中的依赖。
- 当前 saver、审批请求、私有参数和 Store 全是同进程内存对象。新 Runtime 实例恢复不是操作系统进程重启；没有 PostgreSQL、多进程、加密、容量、清理或持久私有参数证据。
- 自动化证明正常路径、拒绝路径和并发重复 resume 下 handler 最多执行一次；没有证明进程在工具副作用完成但 terminal commit 结果未知时的跨崩溃恰好一次。持久 ToolExecution 幂等、lease 与故障恢复由 M10-T5/M11 验收。
- 没有实现 M10-T3 动态重规划、M12 HTTP 审批端点、默认 Container 迁移、真实 Provider 或在线调用；这些不属于 M10-T2。

### 结论

- `M10-T2` 达到 `verified`：审批请求、真实 interrupt、服务端绑定决议、公开 Command resume、批准/拒绝/过期/篡改/重复恢复、Run 生命周期原子提交和同进程新实例恢复均有可复现 E3 证据。
- 下一任务进入 `M10-T3 / planned`，只实现动态计划、失败诊断与有界重规划；不得把 M10-T2 内存证据描述为进程重启，也不得提前进入 M10-T4 多 Agent。

## V-20260720-014：M10-T2 实现提交后恢复锚点

- 任务：`M10-T2`
- 时间：2026-07-20，Asia/Shanghai
- 验证目标：实现提交 `eba696b`（`feat: add server-bound approval resume`）
- 模式：offline；只执行本地 LangGraph、Store 与标准库路径，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -3 --oneline` | 0 | 实现提交后工作区干净；`eba696b` 位于 M10-T1 验证锚点 `cdc9436` 之后 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_approval_resume backend.tests.test_run_store_contract -q` | 0 | handoff 最小恢复集 42 项通过，无 ResourceWarning |
| `.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过，审批 Runtime 未污染顶层导入 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、66 个 Markdown 文件通过 |

### 失败尝试

- 提交后对照旧 handoff 格式时首次猜测文件名为 `2026-07-20-m10-t1-checkpointing.md`，`rg` 因文件不存在退出 1；随后用 `rg --files` 定位实际文件 `2026-07-20-m10-t1-checkpointed-langgraph.md` 并完成只读核对，没有修改结论。

### 结论

- M10-T2 实现提交固定为 `eba696b`；`V-20260720-013` 的审批/Store 42 项、定向 85 项、后端 316 项全量门、失败尝试和同进程证据边界不变。
- 当前任务为 `M10-T3 / planned`；不重做 checkpoint 或审批 resume，不把内存恢复描述成进程重启，不提前进入 M10-T4。

## V-20260722-001：M10-T3 有界动态计划与失败重规划

- 任务：`M10-T3`
- 时间：2026-07-22，Asia/Shanghai
- 验证目标：HEAD `545d5af` 上的 M10-T3 工作区；实现提交由后续本地 commit 固定
- 任务等级：A 类 checkpoint、错误分类与副作用禁重放边界，时间盒 2–4 小时
- 模式：offline；只执行本地 LangGraph、确定性 planner/executor、内存 Store 和标准库路径，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；使用仓库现有 Python 3.12.10、LangGraph 1.2.9 与 langgraph-checkpoint 4.1.1

### 恢复与设计核对

- 开始时 `git status --short` 干净；最近提交为 `545d5af`、`eba696b`、`cdc9436`、`b6dfa0b`、`c4d4efe`、`fdeb9b5`，未重做 M10-T1/T2。
- 按顺序阅读 AGENTS、continuity README/status/playbook、实施计划 M10-T3/M10-T4、Stage 10、ADR-0003/0006/0007/0011/0012、最新 handoff、V-013/V-014、后端规约和实际 Runtime/RunFailure/ToolResult/Coordinator 代码；代码与记录一致，无需登记漂移。
- handoff 恢复集通过：审批/Store 42 项、禁用 `site-packages` 的 M1 7 项、52 个稳定任务/66 个 Markdown；无 ResourceWarning。
- 设计固定为结构化 operation、服务端错误码白名单、auth/validation/approval/security/storage/cancellation 硬停止、独立步骤/重规划预算、忽略 step ID 的循环签名和副作用禁重放；默认 Container、多 Agent、PostgreSQL 与在线模型均排除。

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 初始工作区干净，基线 `545d5af`，提交边界正确 |
| handoff 的审批/Store、M1 与连续性恢复命令 | 0 | 42 项、7 项、52 个任务/66 个 Markdown 通过，代码与记录无漂移 |
| `.\.venv\Scripts\python.exe -B -c "import backend.app.agent.replanning_runtime"` | 0 | 新 Runtime 显式导入成功，没有修改 `backend.app.agent` 顶层导出 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_replanning -v` | 0 | 首轮 12 项通过；聚焦复审补齐已完成副作用禁重放和 durable Coordinator 纵切后最终 14 项通过 |
| 6 模块 79 项定向回归（首轮） | 1 | 78 项通过；既有 `test_pre_runtime_delay_consumes_the_total_execution_budget` 的毫秒级 deadline 断言一次读到 Runtime calls=1 |
| 同一 deadline 单用例 / `test_run_coordinator` 模块 | 0 | 单用例通过；Coordinator 19 项通过，未修改生产 Coordinator 或该测试 |
| 同一 6 模块 79 项组合重跑 | 0 | 79 项全部通过；既有三条 notifier 负向日志，不含原始异常文本 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_replanning backend.tests.test_langgraph_checkpointing backend.tests.test_langgraph_approval_resume backend.tests.test_run_coordinator backend.tests.test_runtime_contract backend.tests.test_tool_security backend.tests.test_run_store_contract backend.tests.test_skill_context backend.tests.test_framework_runtimes -q` | 0 | 最终 124 项重规划、checkpoint、审批、Coordinator、Runtime、工具、Store、Skill 与框架回归通过，无 ResourceWarning |
| `.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过，新 LangGraph 模块未污染顶层导入 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | ADR 加入后 52 个稳定任务、67 个 Markdown 文件通过；最终 handoff 加入后重跑为 52 个任务、68 个 Markdown 文件通过 |

### 实现与安全证据

- `ReplanningLangGraphRuntime` 真实执行 `plan -> execute -> diagnose -> replan` StateGraph；动态失败改路通过 `RunCoordinator`、EventStore 顺序事件和 completed Run，不是 import 或手写等价逻辑。
- checkpoint 保存 workflow kind/version、owner scope、operation、完成步骤、revision、执行/重规划次数、历史计划摘要、稳定失败和终态；测试 secret、planner/executor、工具参数和中间输出不进入 state。
- 只有 `retryable=true`、错误码命中服务端白名单、category 非硬拒绝且步骤无副作用时才重规划；错误的 retryable 标记不能绕过 auth 或白名单。
- 初始与替换计划均受剩余 step budget 约束；max replan、同路径换 step ID、重复完成 step 和重复已完成副作用均产生稳定停止结果。
- approval step 在 executor 前返回 `approval_step_requires_interrupt`，必须转入 M10-T2 审批 Runtime；planner 元数据不授权工具。
- 新 Runtime 实例复用共享 saver 时，终态不重跑 planner/executor，被任务取消的只读 pending step可恢复；pending 副作用返回 `side_effect_resume_unsafe` 并记录停止事件，handler 不被再次调用。

### 失败、警告与未验证范围

- 本轮工具会话未提供旧 `exec_command` 名称，首个只读 `git status` 工具调用未执行；改用本轮 `shell_command` 后按恢复顺序重跑成功。
- AGENTS 首次按 PowerShell 默认编码读取为乱码，随后显式 `-Encoding UTF8` 重读；一次猜错 ADR-0011 文件名、一次猜错 `domain/model.py`、一次针对不存在配置文件和 Windows wildcard 的 formatter 搜索退出 1，均通过 `rg --files`/符号搜索按实际结构修正，没有据此修改业务结论。
- 79 项组合首轮的既有 deadline 用例只失败一次；单用例、完整 Coordinator 模块和相同组合连续重跑均通过。保留该失败事实，不把它静默改写成首次成功，也没有为通过测试放宽 deadline。
- 恢复测试出现一次既有 asyncio 慢任务诊断；定向回归出现三条预期 notifier 失败日志。所有最终命令退出 0，无 ResourceWarning。
- 未运行 `scripts/verify.ps1` 全仓门：本任务新增显式 Runtime/测试/文档，没有修改依赖、锁文件、构建配置、默认 Container、前后端接口或既有共享 Runtime/Store Protocol；124 项风险定向集覆盖实际边界。
- planner/executor 是确定性离线 fixture，不能描述为真实模型规划质量、Provider 兼容、Token/费用或线上性能。`InMemorySaver` 仍不是进程重启、多进程或 PostgreSQL 证据。
- 没有持久 ToolExecution 结果仲裁、lease、结果未知恢复扫描、默认主链迁移、HTTP/SSE、多 Agent 或 M10-T5 故障注入；这些保持后续任务边界。

### 结论

- `M10-T3` 达到 `verified`：结构化计划、失败诊断、白名单重规划、步骤/重规划预算、循环检测、取消、审批/副作用停止、同进程 checkpoint 恢复和 durable Coordinator 纵切均有可复现 E3 证据。
- `KI-005` 更新为 mitigated；下一任务进入 `M10-T4 / planned`，只实现一种真实多 Agent 模式及单 Agent 对照，不提前执行 M10-T5。

## V-20260722-002：M10-T3 实现提交后恢复锚点

- 任务：`M10-T3`
- 时间：2026-07-22，Asia/Shanghai
- 验证目标：实现提交 `e27a8ef`（`feat: add bounded LangGraph replanning`）
- 模式：offline；只执行本地 LangGraph、确定性 fixture 和标准库路径，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -3 --oneline` | 0 | 实现提交后工作区干净；`e27a8ef` 位于 M10-T2 验证锚点 `545d5af` 之后 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_replanning -q` | 0 | handoff 最小恢复集 14 项通过，无 ResourceWarning |
| `.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过，重规划模块未污染顶层导入 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、68 个 Markdown 文件通过 |

### 结论

- M10-T3 实现提交固定为 `e27a8ef`；`V-20260722-001` 的专项 14 项、定向 124 项、失败尝试、全量门跳过理由和同进程 E3 边界不变。
- 当前任务为 `M10-T4 / planned`；不重做 checkpoint、审批或动态重规划，不提前进入 M10-T5，也不把确定性 fixture 描述为真实模型证据。

## V-20260722-003：M10-T4 Agents SDK Manager-as-Tools 对照

- 任务：`M10-T4`
- 时间：2026-07-22，Asia/Shanghai
- 验证目标：HEAD `ae9e3aa` 上的 M10-T4 工作区；实现提交由后续本地 commit 固定
- 任务等级：A 类角色工具隔离、调用预算与失败闭合边界，时间盒 2–4 小时
- 模式：offline；实际执行本地 OpenAI Agents SDK `Runner.run()`、`Agent.as_tool()`、确定性 Model 与共享 ToolRegistry，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；使用仓库现有 Python 3.12.10 与 openai-agents 0.18.2

### 恢复与设计核对

- 开始时 `git status --short` 干净；最近提交为 `ae9e3aa`、`e27a8ef`、`545d5af`、`eba696b`、`cdc9436`、`b6dfa0b`，未重做 M10-T1–T3。
- 按顺序阅读 AGENTS、continuity README/status/playbook、实施计划 M10-T4/M8-T4/M10-T3、Stage 10、ADR-0008/0013、最新 M10-T3 handoff、V-001/V-002、M8-T5 对照 handoff、后端规约和实际 SDK/ToolRegistry/fixture 代码；代码与记录一致，无需登记漂移。
- handoff 恢复集通过：重规划专项 14 项、禁用 `site-packages` 的 M1 7 项、52 个稳定任务/68 个 Markdown；无 ResourceWarning。
- 方案固定为独立 manager-as-tools：不改现有 `OpenAIAgentsRuntime` 对 handoff event 的 fail-closed 契约，不接入默认 Container；manager 只能调用 researcher/writer/reviewer，业务工具仍经共享 Registry 快照。

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 初始工作区干净，基线 `ae9e3aa`，提交边界正确 |
| handoff 的重规划、M1 与连续性恢复命令 | 0 | 14 项、7 项、52 个任务/68 个 Markdown 通过，代码与记录无漂移 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.multi_agent`（首次） | 1 | 固定案例在模块导入时先于 `_required_text` 定义构造，触发 `NameError`；前移纯校验函数后修复，Runner 尚未在该次失败中启动 |
| 同一 Demo（第二次） | 0 | 报告安全记录两组均为 `collaboration_execution_failed`；诊断确认 0.18.2 即使 RunConfig 禁用 Trace 仍先初始化默认 exporter，当前 SOCKS 代理缺可选 `socksio` |
| 只读 Runner 诊断探针 | 1 | 首个 `python -c` 多行探针因 PowerShell 引号产生 `SyntaxError`；改用 stdin 探针后复现上述 `ImportError`，没有安装依赖或修改代理 |
| 同一 Demo（禁用的进程本地无 exporter Trace provider 后） | 0 | 最终 3 例两组质量 1.0、失败率 0；manager 27 requests/324 fixture Token/424.656 ms/复杂度 12，单 Agent 9/108/138.526 ms/复杂度 3，结论 `single_agent` |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_multi_agent backend.tests.test_workflow_comparison_eval -v`（首轮） | 0 | 14 项通过；零网络守卫替换 `socket.socket` 类后触发 Windows Proactor 自管道类型错误日志，测试退出仍为 0但不接受该噪声 |
| 同一 14 项专项（修复守卫后） | 0 | 改为守卫 `create_connection`/`socket.connect`，14 项无异步错误日志、无 ResourceWarning 通过 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_multi_agent backend.tests.test_workflow_comparison_eval backend.tests.test_openai_agents_runtime backend.tests.test_runtime_comparison backend.tests.test_tool_security backend.tests.test_runtime_contract backend.tests.test_langgraph_replanning -q` | 0 | 最终 93 项 SDK、多 Agent、评测、工具安全、Runtime 与重规划定向回归通过，无 ResourceWarning |
| `.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过，新 SDK 模块保持显式导入 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 新 handoff 后 52 个稳定任务、69 个 Markdown 文件通过，当前任务已推进到 M10-T5 |

### 实现与安全证据

- `create_manager_as_tools_topology()` 使用公开 `Agent.as_tool()` 构造三个 specialist，公开 `Runner.run()` 实际进入 manager 与嵌套 Agent run；每例模型调用计数固定为 manager 4、researcher 2、writer 1、reviewer 2，不是 import、对象构造或手写等价逻辑。
- manager 只有三个 orchestration tool，researcher 只有事实查询，writer 无业务工具，reviewer 只有要求检查；manager 无直接业务工具。角色工具来自独立 `ToolRegistry` 快照，身份/角色和 Schema 在执行时重校验，高风险、审批和副作用工具不进入。
- manager `max_turns=6`，specialist `max_turns=3`；预算专项用 `max_turns=1` 实际得到 `MaxTurnsExceeded`。角色异常不转换为成功答案，评测只记录稳定 `collaboration_execution_failed`，原始异常不进入报告。
- 每例两种策略都实际执行一次 `lookup_course_fact` 和一次 `check_required_terms`。相同固定输入/事实/要求下质量与失败率相同，多 Agent 没有收益，按任务契约保留单 Agent。
- 每次 Runner 使用显式禁用 Trace 与敏感 Trace 数据的 RunConfig。独立离线评测进程安装无 exporter 的禁用 provider，零网络守卫通过；该 provider 不是应用组合配置，不能嵌入默认应用进程。
- 报告不输出事实、答案或异常文本；fixture usage 保持 SDK aggregate 形状，Token 和延迟 scope 明确标注，未猜测费用。
- `git diff --check` 与连续性检查在 handoff 落盘后执行；任务 ID、当前任务、相对链接和恢复入口保持一致。

### 失败、警告与未验证范围

- 首次 Demo 的定义顺序错误、第二次 Trace exporter/SOCKS 环境失败、首个诊断探针引号错误和首轮 socket 守卫的 Proactor 日志均保留如上；修复后 Demo、14 项专项和 93 项定向集连续退出 0，无警告。
- 确定性 Model 每次响应写入 8 input/4 output fixture Token，并增加 1 ms delay；SDK aggregate request/Token 是真实框架聚合，但不是 Provider tokenizer、账单或在线 usage，本地 elapsed 也不是生产网络延迟。
- 没有读取 Key、执行在线 Provider、计算真实费用、验证真实模型角色质量、并发容量或资源清理；费用仍未知而非 0，本轮“费用 0”只表示未发生付费调用。
- 没有修改依赖、锁文件、默认 Container、共享 Runtime/Store Protocol、前后端 API 或构建配置，因此未执行 `scripts/verify.ps1` 全仓门；93 项定向集覆盖实际代码边界。
- 没有实现 SDK handoff、默认 Runtime 迁移、RunCoordinator/EventStore 接线或 M10-T5 故障注入。现有 SDK Runtime 对后续 agent update 的拒绝语义不变，真实恢复/结果未知测试继续由 M10-T5/M11 承接。

### 结论

- `M10-T4` 达到 `verified`：真实公开 SDK manager-as-tools 调用链、独立角色指令/工具、共享 ToolRegistry 安全边界、turns 预算、零网络和同任务单 Agent 固定对照均有可复现离线证据。
- `KI-013` closed；固定集没有质量或失败率收益，结论保留单 Agent。下一任务进入 `M10-T5 / planned`，只做恢复与故障注入，不把本地 fixture 指标描述为在线证据，也不提前进入 M10-T6。

## V-20260722-004：M10-T4 实现提交后恢复锚点

- 任务：`M10-T4`
- 时间：2026-07-22，Asia/Shanghai
- 验证目标：实现提交 `abdc409`（`feat: compare manager-as-tools collaboration`）
- 模式：offline；只执行本地 Agents SDK、确定性 Model、ToolRegistry 与标准库路径，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -3 --oneline` | 0 | 实现提交后工作区干净；`abdc409` 位于 M10-T3 验证锚点 `ae9e3aa` 之后 |
| `.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.multi_agent` | 0 | 3 例两组质量 1.0、失败率 0，选择 single Agent；manager 27 requests/324 fixture Token/415.495 ms，单 Agent 9/108/138.762 ms |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_multi_agent backend.tests.test_workflow_comparison_eval -q` | 0 | handoff 专项 14 项通过，无 ResourceWarning 或异步错误日志 |
| `.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过，多 Agent 模块保持显式导入 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、69 个 Markdown 文件通过 |

### 结论

- M10-T4 实现提交固定为 `abdc409`；`V-20260722-003` 的 14 项专项、93 项定向回归、失败尝试、单 Agent 结论和离线 E2/E3 边界不变。
- 当前任务为 `M10-T5 / planned`；不重做 manager-as-tools，不接入默认 Runtime，不提前进入 M10-T6，也不把 fixture usage/延迟描述为 Provider 或生产证据。

## V-20260722-005：M10-T5 恢复与故障注入

- 任务：`M10-T5`
- 时间：2026-07-22，Asia/Shanghai
- 验证目标：HEAD `7538fb4` 上的 M10-T5 工作区；实现提交由后续本地 commit 固定
- 任务等级：A 类 checkpoint、审批副作用与恢复诊断边界，时间盒 2–4 小时
- 模式：offline；只执行本地 LangGraph、确定性 fixture、故障 saver、内存 Store 和 ToolRegistry，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；使用仓库现有 Python 3.12.10、LangGraph 1.2.9 与 langgraph-checkpoint 4.1.1

### 恢复与故障矩阵

- 开始时 `git status --short` 干净；最近提交为 `7538fb4`、`abdc409`、`ae9e3aa`、`e27a8ef`、`545d5af`、`eba696b`，未重做 M10-T1–T4。
- 按顺序阅读 AGENTS、continuity README/status/playbook、实施计划 M10-T5 及依赖、Stage 10、ADR-0011/0012/0013、最新 handoff、V-003/V-004、后端规约和实际 checkpoint/approval/replanning 代码与测试；代码和记录一致，无需登记漂移。
- handoff 恢复集通过：M10-T4 Demo 仍选择 single Agent，多 Agent专项 14 项、禁用 `site-packages` 的 M1 7 项、52 个稳定任务/69 个 Markdown 通过。
- 故障矩阵固定为 10 个场景：checkpoint 读取不可用/状态损坏；只读 step 中断/timeout；审批等待换实例/丢 checkpoint/取消；重规划 pending 副作用；审批后 checkpoint 写失败；副作用 timeout。PostgreSQL、进程重启、lease 和恢复扫描明确排除。
- 复审发现 Stage 10 曾把“多 Agent 取舍”误映射到 M10-T5，而实施计划和实际证据均为 M10-T4；先登记 `KI-020` 并修正映射，未改变任务编号或实现范围。

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 初始工作区干净，基线 `7538fb4`，提交边界正确 |
| M10-T4 handoff 的 Demo、14 项专项、M1 与连续性恢复命令 | 0 | 固定 3 例仍选择 single Agent；14 项、7 项、52 个任务/69 个 Markdown 通过，无 ResourceWarning |
| `rg`/`Get-Content` 两次只读路径探查 | 1 | 首次猜错三项测试文件名，第二次猜错 ADR 标题后缀；均用 `rg --files` 按真实文件名纠正，没有据此修改结论 |
| `... -m unittest backend.tests.test_langgraph_recovery_faults -v`（首轮） | 1 | 测试模块默认参数先于 `_approval_planner` 定义求值，导入时报 `NameError`；改为运行时解析后重跑 |
| 同一故障专项（第二轮） | 1 | 10 项中 8 项通过；终态事件字段断言应为既有 `failure_code`，单次 saver 写故障未阻断后续成功 checkpoint 写入 |
| 同一故障专项（夹具修正后） | 0 | 本 invocation 全程阻断写入、恢复前解除，真实保留结果未知窗口；10 项全部通过，无 ResourceWarning |
| `... -m unittest backend.tests.test_langgraph_approval_resume -q` | 0 | 既有审批正常、拒绝、过期、重复、换 Runtime 与取消 10 项通过 |
| checkpoint、approval、replanning 与 recovery 4 模块组合 | 0 | 44 项核心回归通过，无 ResourceWarning |
| `... -m unittest backend.tests.test_langgraph_checkpointing backend.tests.test_langgraph_approval_resume backend.tests.test_langgraph_replanning backend.tests.test_langgraph_recovery_faults backend.tests.test_run_coordinator backend.tests.test_run_store_contract backend.tests.test_tool_security backend.tests.test_multi_agent backend.tests.test_workflow_comparison_eval -q` | 0 | 最终 123 项 M10-T1–T5、Coordinator、Store、ToolRegistry 与多 Agent 对照定向回归通过；三行 notifier 失败日志来自既有负向用例 |
| `.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过，新测试和专用 LangGraph 模块未污染顶层导入 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 新 handoff 后 52 个稳定任务、70 个 Markdown 文件通过，当前任务推进到 M10-T6 |

### 实现与安全证据

- `_FailAfterEffectSaver` 在审批 handler 完成后阻断本 invocation 的 checkpoint 写入，使 graph 保持在 interrupt 前快照；解除故障后由新 Runtime 复用同一 saver/store 恢复，实际进入单次 grant 已消费分支。
- 已消费 grant 且 checkpoint 未终结时，审批 Runtime 返回 `side_effect_resume_unsafe`、发出 `approval.stopped`，handler 调用列表仍只有一项；不再把结果未知退化成可再次尝试的普通审批错误。
- 重规划 pending 副作用在任务取消后由新 Runtime 读取共享 saver，返回 `side_effect_resume_unsafe`、发出 `plan.stopped`，新 executor 调用数为 0。
- checkpoint 读取不可用时 delegate 调用数为 0；损坏重规划 checkpoint 通过真实 Coordinator 形成 `run.started -> run.failed`，planner/executor 均不运行。
- 只读 pending step 可由新 Runtime 恢复；只读 `tool_timeout` 只在白名单、retryable 和预算均满足时改路。副作用 step 即使返回可重试 timeout 也产生 `side_effect_replan_forbidden`/`plan.stopped`，planner 不再次调用。
- 审批等待可由共享 saver/store 的新 Runtime 恢复一次；换成空 saver 返回 `approval_checkpoint_missing`，取消 waiting Run 形成 `run.cancelled`，两者 handler 都不运行。

### 失败、警告与未验证范围

- 测试模块导入失败和第二轮两个夹具错误均如上保留；生产分支修复后，专项、44 项核心和 123 项定向集连续退出 0。
- `git diff` 与 formatter 搜索组合命令因仓库没有对应 formatter 配置而整体退出 1；其中 `git diff --check` 无 whitespace 报错，最终仍以实际测试、后续 diff 审查和连续性检查验收。
- `InMemorySaver` 故障只模拟同进程 checkpoint 写不可用，不是操作系统 kill、PostgreSQL、网络分区或多进程证据。单次 approval 消费证明 at-most-once；消费后、handler 前退出仍可能未执行，不能宣称 exactly-once。
- 未实现持久 ToolExecution 结果、lease、恢复扫描、私有参数重启恢复、默认 Container 或 HTTP/SSE 迁移；这些保持 M11/M12 边界。
- 未运行 `scripts/verify.ps1` 全仓门：没有依赖、锁文件、构建配置、默认组合根、前后端 API 或公共 Runtime/Store Protocol 变化；123 项定向集覆盖本任务风险，M10-T6 里程碑验收再执行完整门。
- 没有读取 Key、执行在线 Provider、产生费用或验证生产容量。所有结论最高为同进程本地 E3。

### 结论

- `M10-T5` 达到 `verified`：checkpoint/interrupt/replanning 的中断、换实例、timeout、审批等待、损坏状态和结果未知副作用均有可复现故障证据；可安全恢复则继续，不可安全恢复则明确停止并诊断，副作用不重复。
- `KI-004` 保持 mitigated，M11 仍需 PostgreSQL、持久 ToolExecution、lease、恢复扫描和真实进程重启才能关闭。下一任务进入 `M10-T6 / planned`，只做 M10 课程汇总与里程碑验收，不提前实现 M11。

## V-20260722-006：M10-T5 实现提交后恢复锚点

- 任务：`M10-T5`
- 时间：2026-07-22，Asia/Shanghai
- 验证目标：实现提交 `1e332f3`（`test: inject LangGraph recovery faults`）
- 模式：offline；只执行本地 LangGraph、故障 fixture 与标准库路径，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -3 --oneline` | 0 | 实现提交后工作区干净；`1e332f3` 位于 M10-T4 验证锚点 `7538fb4` 之后 |
| `.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_recovery_faults -q`（首次） | 0 | 10 项通过；Windows asyncio debug 输出一条 0.187 秒慢任务诊断，不是 ResourceWarning |
| 同一故障专项原命令复跑 | 0 | 10 项在 0.256 秒内通过，无 ResourceWarning 或慢任务诊断 |
| `.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过，LangGraph 专用模块保持显式导入 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、70 个 Markdown 文件通过 |

### 结论

- M10-T5 实现提交固定为 `1e332f3`；`V-20260722-005` 的 10 项专项、123 项定向回归、失败尝试、全量门跳过理由和同进程 E3 边界不变。
- 当前任务为 `M10-T6 / planned`；不重做故障矩阵，不把内存故障注入描述为进程重启或 exactly-once，不提前进入 M11。

## V-20260722-007：M10 课程汇总与里程碑验收

- 任务：`M10-T6`
- 时间：2026-07-22，Asia/Shanghai
- 验证目标：HEAD `07741db` 上的 M10-T6 课程工作区；课程提交由后续本地 commit 固定
- 任务等级：B 类课程文档整合与里程碑完整门，时间盒 60–90 分钟
- 模式：offline；只执行本地 LangGraph、Agents SDK 确定性 Model、Store、构建与配置检查，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；没有修改业务代码、公共契约、默认 Container、HTTP/SSE 或前端行为

### 恢复、漂移与课程检查

- 开始时 `git status --short` 干净；最近提交为 `07741db`、`1e332f3`、`7538fb4`、`abdc409`、`ae9e3aa`、`e27a8ef`，没有重做 M10-T1–T5。
- 按顺序阅读 AGENTS、continuity README/status/playbook、实施计划 M10-T6/M11-T1、ADR-0011/0012/0013、最新 handoff、V-005/V-006、后端规约、Stage 10、Stage 9、课程模板和 30 项映射，并核对实际 M10 代码/测试。
- handoff 最小恢复集通过：故障专项 10 项、禁用 `site-packages` 的 M1 手写 Loop 7 项、52 个稳定任务/70 个 Markdown；实际代码与 M10-T5 提交一致。
- 发现并先登记 `KI-021`：动态 status 的最近实现提交和结果未知描述已过时；最新不可变 handoff 仍描述待提交文档，但 `07741db` 后工作区实际干净；实施计划曾要求 M10 关闭 `KI-004`/演示重启，与 accepted ADR 的 M11 真重启边界冲突。课程、status 和新 handoff 已澄清，旧 handoff 不回写。
- Stage 10 新增三张状态图、四次跟练、故障定位矩阵、固定排错顺序、证据等级、题库/评分红线、速查与费曼任务；新增 M10 一页速查表并同步 30 项大纲映射。

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 初始工作区干净，基线 `07741db`，提交边界正确 |
| M10-T5 handoff 的故障专项、M1 与连续性恢复命令 | 0 | 10 项、7 项、52 个任务/70 个 Markdown 通过；代码与记录一致 |
| `... -m unittest backend.tests.test_langgraph_checkpointing backend.tests.test_langgraph_approval_resume backend.tests.test_langgraph_replanning backend.tests.test_langgraph_recovery_faults backend.tests.test_multi_agent backend.tests.test_workflow_comparison_eval -v` | 0 | M10 checkpoint、审批、重规划、故障、多 Agent 与对照评测聚焦 58 项通过，无 ResourceWarning |
| `... -m backend.app.evals.multi_agent` | 0 | 3 个固定案例两组质量均 1.0、失败率均 0；manager 27 requests/324 fixture Token/412.399 ms/复杂度 12，single 9/108/138.548 ms/复杂度 3，选择 `single_agent` |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1`（沙箱首轮） | 1 | 后端 354 项通过、1 项 Windows symlink 能力跳过；受控代码 Agent 与依赖检查通过；Vue 因无法写 `frontend/tsconfig.app.tsbuildinfo` 报 `TS5033`/`EPERM`，MCP/Compose 尚未执行 |
| 同一完整脚本（批准工作区构建权限后） | 0 | 后端 354 项通过、1 项跳过；受控代码 Agent、依赖检查、Vue 生产构建、MCP TypeScript 构建和 Compose 配置全部通过 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 新 handoff 后 52 个稳定任务、72 个 Markdown 文件通过 |
| 新课程相对链接 `Test-Path` / `git diff --check` | 0 | 速查、syllabus、status、known issue 和 playbook 链接目标存在；无 whitespace 错误，仅有 Git 的 LF/CRLF 转换提示 |

### 失败、警告与未验证范围

- 完整门首次失败只发生在沙箱 Vue `tsbuildinfo` 写入边界；没有修改代码或配置规避。相同脚本在获批工作区构建权限下完整退出 0，首次失败事实与后续结果同时保留。
- 全量后端输出含一条既有 `StarletteDeprecationWarning`，Windows 环境仍有 1 项真实 symlink 能力测试跳过；二者没有被描述为已消除。
- 课程中的“恢复”只指同一进程内新 Runtime 实例复用共享 `InMemorySaver`；没有操作系统进程重启、PostgreSQL checkpointer、持久 ToolExecution、lease、恢复扫描或多进程仲裁证据，`KI-004` 保持 mitigated。
- 多 Agent usage/延迟来自确定性 fixture 与本地 SDK 聚合，不是 Provider tokenizer、账单、线上质量、费用或生产容量证据。
- 没有在线 Provider、密钥、网络或付费调用。学习者尚未在 `docs/progress.md` 完成 M10 题库、速查和费曼个人通关；工程 verified 不等于个人 accepted。

### 结论

- `M10-T6` 达到 `verified`，M10 里程碑达到工程 `verified`：可运行代码、58 项聚焦证据、完整离线门、跟练、排错、题库、速查、费曼任务和 30 项映射全部落盘。
- `KI-021` closed；`KI-004` 正确保留 mitigated 并由 M11-T1 承接 PostgreSQL 真重启边界。当前任务推进到 `M11-T1 / planned`，不在本轮实现数据库、记忆或 RAG。

## V-20260722-008：M10-T6 课程提交后恢复锚点

- 任务：`M10-T6`
- 时间：2026-07-22，Asia/Shanghai
- 验证目标：课程提交 `1766875`（`docs: complete M10 course acceptance`）
- 模式：offline；只执行本地 LangGraph、Agents SDK 确定性 fixture 和标准库路径，没有读取真实 API Key、访问模型服务或产生付费调用，费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -3 --oneline` | 0 | 课程提交后工作区干净；`1766875` 位于 M10-T5 验证锚点 `07741db` 之后 |
| `... -m unittest backend.tests.test_langgraph_checkpointing backend.tests.test_langgraph_approval_resume backend.tests.test_langgraph_replanning backend.tests.test_langgraph_recovery_faults backend.tests.test_multi_agent backend.tests.test_workflow_comparison_eval -q` | 0 | handoff 的 M10 聚焦 58 项通过，无 ResourceWarning |
| `.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过，M10 专用模块仍未污染顶层导入 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1` | 0 | 52 个稳定任务、72 个 Markdown 文件通过 |

### 结论

- M10-T6 课程提交固定为 `1766875`；`V-20260722-007` 的 58 项聚焦、完整离线门、首次沙箱 EPERM、课程链接和离线 E2/E3 边界不变。
- 当前任务为 `M11-T1 / planned`；不重做 M10，不把 `InMemorySaver` 描述为进程重启，不提前进入 pgvector、Embedding、记忆或 RAG。

## V-20260722-009：M11-T1 PostgreSQL Run/Event/checkpoint 首个纵切

- 任务：`M11-T1 / in_progress`
- 时间：2026-07-22，Asia/Shanghai
- 验证目标：HEAD `8af705b` 上的 M11-T1 工作区；首个纵切实现提交由后续本地 commit 固定
- 任务等级：A 类关键持久化、事务和恢复边界，时间盒 2–4 小时
- 模式：本地真实 PostgreSQL E3；用户已明确授权安装依赖、启动 Docker Desktop、拉取镜像和运行本地测试容器。没有读取真实 API Key、访问模型 Provider 或产生付费调用，费用 0
- 依赖事实：新增并固定 `langgraph-checkpoint-postgres==3.1.0`、`psycopg[binary,pool]==3.3.4`；实际安装 `psycopg-binary==3.3.4`、`psycopg-pool==3.3.1` 与传递依赖 `tzdata==2026.3`

### 恢复、环境与纵切边界

- 开始时 `git status --short` 干净；最近提交为 `8af705b`、`1766875`、`07741db`、`1e332f3`、`7538fb4`、`abdc409`，没有重做 M10。
- 按强制顺序阅读 AGENTS、continuity README/status/playbook、实施计划 M11-T1 及 M8-T2/M10-T1 依赖、ADR-0004/0006/0011/0012、最新 M10 handoff、关联 verification、后端规约和实际 Store/checkpoint/依赖/Docker 边界；启动时代码与记录一致，无需登记漂移。
- handoff 最小恢复集通过：M10 聚焦 58 项、禁用 `site-packages` 的 M1 手写 Loop 7 项、52 个稳定任务/72 个 Markdown。
- 本轮只完成版本化应用 migration、PostgreSQL Run/Event Store、共享连接池与官方 PostgreSQL checkpointer，以及两个 Python 进程恢复。Approval/Memory、持久私有审批参数、ToolExecution、lease/recovery scanning、默认 Container 和 pgvector 明确不在首个纵切内。

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` 与 handoff 恢复命令 | 0 | 初始工作区干净；M10 58 项、M1 7 项、连续性 52/72 通过 |
| `python -m pip show psycopg psycopg-pool langgraph-checkpoint-postgres` | 1 | 安装前确认三项均不存在；未把 import 或依赖存在当作框架完成证据 |
| `python -m pip install "psycopg[binary,pool]==3.3.4" "langgraph-checkpoint-postgres==3.1.0"` | 0 | 经用户授权解析并安装固定依赖；后续 `pip check` 无损坏依赖 |
| `docker version`（沙箱首轮/批准后） | 1 / 0 | 首轮 Docker API 权限被拒；批准后 Client/Server 29.3.1 可用 |
| `docker compose -f deploy/compose.postgres.yaml config` / `up -d --wait` | 0 / 0 | 配置有效；经授权拉取 `postgres:17-alpine` 并启动本地健康容器 |
| 容器内 `SHOW server_version` | 0 | 实际 PostgreSQL 17.10；测试端口只绑定 `127.0.0.1:55432` |
| PostgreSQL persistence `setup()`（默认 Proactor / Selector loop） | 1 / 0 | Psycopg 明确拒绝 Windows Proactor；适配器稳定返回 `store_unavailable`。使用局部 Selector loop 后 migration、pool 和 saver setup 成功 |
| `... -m unittest backend.tests.postgres_store_integration -q`（首轮） | 1 | 33 项中 32 项通过；测试进程的 Selector loop 不支持 asyncio subprocess，checkpoint 子进程用例报 `NotImplementedError` |
| checkpoint 子进程改用 `asyncio.to_thread(subprocess.run)` 后专项 / 33 项全量 | 0 / 0 | 两个不同 PID 分别观察 0→1、1→2；33 项通过 |
| 增加 event INSERT 触发器故障回滚后专项 / 最终集成 | 0 / 0 | Run 状态与 event INSERT 同事务回滚；复审再补 applied history 连续前缀用例，最终真实 PostgreSQL 集成 35 项通过 |
| RunStore、Coordinator、checkpoint 与 approval 受影响回归（首轮/原命令复跑） | 0 / 0 | 两轮均 71 项通过；首轮有一条 Windows asyncio 0.172 秒慢任务诊断，复跑只保留 3 条既有 notifier 负向日志，无 ResourceWarning |
| `python -S ... test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过；PostgreSQL 模块保持显式导入 |
| `scripts/verify.ps1`（沙箱首轮/批准后） | 1 / 0 | 首轮在 Vue `tsbuildinfo` 写入处 `TS5033`/`EPERM`；相同完整脚本批准后后端 354 项通过、1 项跳过，Code Agent、依赖、Vue、MCP TypeScript 和 Compose 配置全部通过 |
| `scripts/check-continuity.ps1` / `git diff --check` | 0 / 0 | 新 handoff 后 52 个稳定任务、73 个 Markdown 通过；无 whitespace 错误，仅有 Git 的 LF/CRLF 转换提示 |

### 实现与事务证据

- `0001_durable_run_event_store.sql` 建立 Run、每 Run event sequence 和 Event 表；应用 migration 记录版本与 SHA-256 校验和，使用 advisory transaction lock，首次/重复、历史缺口、校验和漂移和失败回滚均有真实数据库用例。
- `PostgresPersistence` 让 RunStore、EventStore 和官方 `AsyncPostgresSaver` 复用一个异步连接池；应用 migration 先于 saver `setup()`，模块不进入 Store 包顶层导出，M1 隔离保持不变。
- PostgreSQL RunStore 继承现有完整 `RunStoreContract`。EventStore 在持有 Run row lock 后分配每 Run 序号，并在同一个数据库事务内提交 start/pause/resume/terminal 状态与事件；幂等创建、所有权隔离、并发序号、并发终态和注入 event INSERT 失败后的原子回滚均通过。
- 数据库不可达只返回稳定 `store_unavailable`，没有切换 InMemory Store，也不在错误或 probe JSON 中输出 DSN。checkpoint probe 只读取显式测试 DSN，并由父测试核对两个不同进程的前后计数和答案。
- Windows psycopg 异步连接需要 Selector loop；生产模块不在 import 时修改全局 event-loop policy，probe 与显式集成测试只在自己的进程/测试边界安装 Selector。

### 警告与未验证范围

- 首次 Proactor setup、asyncio subprocess 用例、Docker 沙箱权限和 Vue 沙箱写入失败均如上保留；没有静默吞掉失败或将 fallback 当作成功。最终 35 项集成、71 项受影响回归、M1 7 项和完整发布门均退出 0。
- 全量后端仍有一条既有 `StarletteDeprecationWarning`，Windows 环境仍有 1 项真实 symlink 能力测试跳过。数据库不可达负向用例会输出一条 psycopg pool connection timeout 诊断，测试退出 0且没有泄露 DSN。
- 两进程证据证明 Python 进程边界后的 checkpoint 恢复，不证明 PostgreSQL 容器重启、持久卷、同 thread 并发、多主机、跨机房、备份、TLS、高可用或生产容量。
- 本地 Compose 使用 localhost-only、trust 和 tmpfs，只供显式集成测试；不是生产部署模板。容器在交接时保持健康运行，后续会话必须重新检查，不能据文档假设可用。
- PostgreSQL Approval/Memory Store、持久私有审批参数、ToolExecution 结果仲裁、连接结果未知、lease/heartbeat、恢复扫描、默认 Container 和 M11-T2 pgvector 均未实现；因此 M11-T1 只能进入 `in_progress`，`KI-004`、`KI-014`、`KI-015`、`KI-016` 均不关闭。
- 没有读取 Key、调用在线模型或产生付费调用；本轮数据库网络仅为本机 Docker 端口，镜像与依赖下载均在用户明确授权内。

### 结论

- M11-T1 首个真实 PostgreSQL 纵切达到可运行、可恢复和可复现：不是 import-only，也没有 Fake/Mock 数据库完成声明。Run/Event 同事务和官方 saver 跨两个 OS 进程恢复已有真实 PostgreSQL 证据。
- 当前任务保持 `M11-T1 / in_progress`。下一条原子动作只实现 PostgreSQL ApprovalStore/MemoryStore、共同合同和审批恢复所需私有参数；不提前进入 ToolExecution/lease、默认 Container 或 M11-T2。

## V-20260722-010：M11-T1 PostgreSQL 首个纵切提交后恢复锚点

- 任务：`M11-T1 / in_progress`
- 时间：2026-07-22，Asia/Shanghai
- 验证目标：实现提交 `8c6b011`（`feat: persist runs and checkpoints in postgres`）
- 模式：本地真实 PostgreSQL E3；没有读取真实 API Key、访问模型 Provider 或产生付费调用，费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -3 --oneline` | 0 | 实现提交后工作区干净；`8c6b011` 位于 M10-T6 验证锚点 `8af705b` 之后 |
| 设置本地测试 DSN 后 `... -m unittest backend.tests.postgres_store_integration -q` | 0 | 真实 PostgreSQL migration、Run/Event、故障和两个进程 checkpoint 集成 35 项通过；数据库不可达负向用例保留一条预期 pool timeout 诊断，无 ResourceWarning |
| `python -S ... test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过，PostgreSQL 专用模块仍为显式导入 |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、73 个 Markdown 文件通过 |

### 结论

- M11-T1 首个 PostgreSQL 纵切实现提交固定为 `8c6b011`；`V-20260722-009` 的 35 项集成、71 项受影响回归、完整发布门、失败尝试和本地 E3 边界不变。
- 当前任务保持 `M11-T1 / in_progress`；下一条原子动作只做 PostgreSQL ApprovalStore/MemoryStore 和审批恢复私有参数，不重做 Run/Event/checkpoint，也不提前进入 ToolExecution/lease、默认 Container 或 M11-T2。

## V-20260803-001：M11-T1 PostgreSQL Approval/Memory 第二纵切

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-03，Asia/Shanghai
- 验证目标：HEAD `bf875be` 上的 M11-T1 第二纵切工作区；实现提交由后续本地 commit 固定
- 任务等级：A 类身份授权、私有数据、迁移、事务和跨进程恢复边界，时间盒 2–4 小时
- 模式：本地真实 PostgreSQL E3；经本轮批准启动仓库已有 localhost-only 测试容器。没有读取真实 API Key、访问模型 Provider 或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；继续使用已固定的 `psycopg[binary,pool]==3.3.4` 与 `langgraph-checkpoint-postgres==3.1.0`

### 恢复、漂移与设计边界

- 开始时 `git status --short` 干净；最近提交为 `bf875be`、`8c6b011`、`8af705b`、`1766875`、`07741db`、`1e332f3`，没有重做 M10 或 M11-T1 首个纵切。
- 按强制顺序阅读 AGENTS、continuity README/status/playbook、实施计划 M11-T1 及依赖、ADR-0004/0006/0011/0012、最新 handoff、V-009/V-010、后端规约和实际 Approval/Memory/PostgreSQL 代码。首次按标题猜测四个 ADR 路径均不存在，随后用 `rg --files` 按稳定编号找到真实文件；错误路径没有用于结论或修改。
- Docker 沙箱只读检查因 Docker config/API 权限退出 1；批准后 Docker Engine 29.3.1 可用。原测试容器不存在，经批准执行仓库 Compose 后 PostgreSQL 容器健康。
- handoff 恢复集通过：真实 PostgreSQL 35 项、M1 7 项、52 个稳定任务/73 个 Markdown。PostgreSQL 首轮有一条 Windows asyncio 0.125 秒慢任务诊断和预期 pool timeout，无 ResourceWarning。
- 恢复审计先登记 `KI-022`：`status.md` 顶部最近实现提交仍为 M10 的 `1e332f3`，而 Git、专项字段、handoff 与 V-010 均为 `8c6b011`。本轮修正后关闭，未改写历史 handoff。
- `ADR-0014` 固定同步 Approval/Memory Protocol 与双 pool 边界：同一 DSN/lifecycle，不同连接池，不宣称跨 pool 事务；默认 Container、HTTP 和 M10 Runtime 不迁移。

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 初始工作区干净，基线 `bf875be`，提交边界正确 |
| 首次错误 ADR `Get-Content` / `rg --files` 后真实 ADR 读取 | 1 / 0 | 仅文件名猜测错误；按稳定编号纠正并完成必读，不据失败命令推断设计 |
| `docker version`（沙箱/批准后） | 1 / 0 | 沙箱拒绝 Docker config/API；批准后 Client/Server 29.3.1 可用 |
| `docker compose ... ps` / `up -d --wait` | 0 / 0 | 初始无容器；经批准启动既有 localhost-only PostgreSQL 测试服务并达到 healthy |
| handoff 的 PostgreSQL、M1 与连续性恢复命令 | 0 | 35 项、7 项、52 个任务/73 个 Markdown 通过；一条非持续慢任务诊断，无 ResourceWarning |
| 新内存合同、既有 approval/memory/tool 回归首轮 | 0 | 41 项通过；既有审批用例出现一条 Windows asyncio 0.187 秒慢任务诊断，不是 ResourceWarning |
| PostgreSQL 集成首轮 | 0 | 51 项通过：Approval/Memory 共同合同、两个进程私有状态恢复与既有 Run/Event/checkpoint/migration 均执行 |
| approval grant 触发器故障专项 | 0 | request resolution 更新与 grant INSERT 同事务回滚；无 resolution、无可消费 grant |
| 首轮完整 PostgreSQL 集成 / grant 事务故障补测 | 0 / 0 | 51 项通过；补一项真实 trigger 故障，证明 resolution 与 grant 同事务回滚 |
| 聚焦复审后的最终 `backend.tests.postgres_store_integration -q` | 0 | 补 forged resolution 读取拒绝合同后，真实 PostgreSQL 53 项通过；不可达数据库负向用例保留一条预期 pool timeout，无 ResourceWarning |
| Approval/Memory/Runtime/API/Container 等受影响定向回归 | 0 | 最终 80 项通过；只有既有 `StarletteDeprecationWarning` |
| `python -S ... test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过，PostgreSQL 专用模块保持显式导入 |
| `scripts/verify.ps1`（沙箱首轮） | 1 | 后端 370 项通过、1 项既有 Windows symlink 跳过；Code Agent 与依赖检查通过；Vue `tsbuildinfo` 写入报 `TS5033`/`EPERM`，MCP/Compose 尚未执行 |
| 相同完整脚本（批准工作区构建权限后） | 0 | 后端 370 项通过、1 项跳过；Code Agent、依赖、Vue 生产构建、MCP TypeScript 和 Compose 配置全部通过 |
| forged resolution 语义修正后的相同完整脚本 | 0 | 最终后端 371 项通过、1 项跳过；Code Agent、依赖、Vue、MCP TypeScript 和 Compose 配置再次全部通过 |
| `scripts/check-continuity.ps1` / `git diff --check` | 0 / 0 | 新 ADR/handoff 后 52 个稳定任务、75 个 Markdown 通过；无 whitespace 错误，仅有 Git 的 LF/CRLF 转换提示 |

### 实现、事务与隐私证据

- 新增同步 `ApprovalStore`/`MemoryStore` Protocol；现有内存实现、ToolExecutionContext、审批 Runtime、Container 和 `create_app()` 依赖抽象。审批 Store 故障从 Runtime 原样传播，测试证明 Run 留在 running 且不伪造终态。
- `0002_approval_memory_store.sql` 分离 request 私有参数与精确 grant；私有参数限制为 64,000 UTF-8 字节，公开 dataclass/checkpoint/event/probe 不包含参数。resolve 锁 request row 并与 grant 写入同事务；consume 锁 grant row，并发合同只有一个赢家。
- PostgreSQL MemoryStore 使用 per-session 计数器，在追加消息事务内裁剪窗口；长期事实要求显式批准，按 owner 读取和删除。内存与 PostgreSQL 分别运行同一 11 项 Approval 和 5 项 Memory 合同，包括伪造 approved resolution 不能读取未决私有参数。
- `PostgresPersistence` 统一打开/关闭异步 Run/Event/checkpoint pool 与同步 Approval/Memory pool。两者同 DSN但没有共同连接或跨 pool 事务声明，默认 Container 保持内存。
- 两个 PID 不同的 Python 进程依次写入和恢复 request 私有参数、决议/单次消费、完整 Message 与长期事实；子进程内部核对真实内容，stdout 仅允许 phase、PID、ID、计数、布尔结果和稳定 replay reason。
- 数据库、pool 和触发器故障只越界为稳定 StoreError；没有内存 fallback、DSN、原始参数、消息、事实或数据库异常文本进入应用输出。

### 失败、警告与未验证范围

- ADR 路径猜测、Docker 沙箱拒绝、Vue 沙箱 EPERM、两条非持续 Windows asyncio 慢任务诊断和一次窄 `apply_patch` 权限审查超时均保留；相同窄 patch 重试成功。最终真实 PostgreSQL、聚焦回归、M1 与完整门均退出 0。
- 后端仍有一条既有 `StarletteDeprecationWarning`，Windows 环境仍跳过 1 项真实 symlink 能力用例；数据库不可达负向测试仍输出一条不含 DSN 的 pool timeout 诊断。
- 跨进程证据证明 Approval/Memory Store 数据可恢复，不证明默认应用、M10 Approval Runtime、HTTP 或 ContextAssembler 已切换 PostgreSQL。同步适配器尚无 async event-loop 线程隔离、取消、超时或 pool 耗尽证据，`KI-023` open。
- Approval 与 Run/Event/checkpoint 使用不同 pool，不提供跨 pool 原子性、持久 ToolExecution 结果仲裁、lease/heartbeat、恢复扫描或 exactly-once。默认 Container、M11-T2 pgvector、Embedding 和 RAG 未实现。
- 私有参数和记忆在本地测试数据库中为明文；没有应用层加密、生产 TLS、持久卷、备份、数据保留、高可用或容量证据。
- 没有读取 Key、调用在线模型或产生付费调用；本轮只有本机 Docker 数据库通信。

### 结论

- M11-T1 第二个真实 PostgreSQL 纵切达到可运行、可恢复和可复现：Approval/Memory 不是 Fake/Mock，私有参数、同事务 grant、并发单次消费、消息窗口、长期事实与两个 OS 进程恢复均有真实数据库证据。
- `KI-014` 进入 mitigated，`KI-022` closed，新增 `KI-023` 记录同步数据库适配器接入 async 主链前的线程/取消缺口。M11-T1 保持 `in_progress`；下一条原子动作只做 PostgreSQL ToolExecution 结果仲裁，不合并 lease、默认 Container 或 M11-T2。

## V-20260803-002：M11-T1 Approval/Memory 实现提交后恢复锚点

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-03，Asia/Shanghai
- 验证目标：实现提交 `cb4fd52`（`feat: persist approvals and memory in postgres`）
- 模式：本地真实 PostgreSQL E3；复用已批准并保持 healthy 的 localhost-only 测试容器。没有读取 Key、调用在线模型或产生费用

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git commit -m "feat: persist approvals and memory in postgres"` | 0 | 24 个本任务文件固定为实现提交 `cb4fd52`，2060 行新增、54 行删除 |
| `docker compose -f deploy/compose.postgres.yaml ps` | 0 | `ai-agent-demo-m11-postgres-1` healthy，继续仅绑定 `127.0.0.1:55432` |
| 设置测试 DSN 后 `... -m unittest backend.tests.postgres_store_integration -q` | 0 | 实现提交上真实 PostgreSQL 53 项通过；不可达数据库负向用例保留预期 pool timeout，无 ResourceWarning |
| `python -S ... test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过 |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、75 个 Markdown 文件通过 |

### 结论

- M11-T1 PostgreSQL Approval/Memory 第二纵切实现提交固定为 `cb4fd52`；`V-20260803-001` 的 53 项真实数据库集成、80 项受影响回归、371 项完整后端门、失败尝试与未验证范围不变。
- 当前任务保持 `M11-T1 / in_progress`。下一条原子动作只做 PostgreSQL ToolExecution 结果仲裁，不重做 Run/Event/checkpoint 或 Approval/Memory，不合并 lease、默认 Container 或 M11-T2。

## V-20260803-003：M11-T1 PostgreSQL ToolExecution 结果仲裁

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-03，Asia/Shanghai
- 验证目标：HEAD `bb36875` 上的 M11-T1 第三纵切工作区；实现提交由后续本地 commit 固定
- 任务等级：A 类副作用、持久化、幂等、CAS、事务和跨进程结果未知边界，时间盒 2–4 小时
- 模式：本地真实 PostgreSQL E3；复用用户已启动的 localhost-only 测试容器。没有读取 Key、访问模型 Provider 或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；继续使用已固定的 PostgreSQL 驱动和官方 checkpointer

### 恢复、设计与范围

- 开始时 `git status --short` 干净，最近提交为 `bb36875`、`cb4fd52`、`bf875be`、`8c6b011`、`8af705b`、`1766875`；按强制顺序读取 Git、AGENTS、continuity、实施计划、ADR-0004/0006/0011/0012/0014、最新 handoff、V-001/V-002、后端规约和实际代码。
- Docker Compose 状态查询的自动权限审查因远端 stream 断开而未执行；已获准的只读 `docker exec ... pg_isready` 返回 accepting connections。handoff 恢复集随后真实 PostgreSQL 53 项、M1 7 项和连续性 52/75 通过，数据库不可达负向用例保留预期 pool timeout，无 ResourceWarning。
- `ADR-0015` 固定 async ToolExecutionStore、Run owner 绑定、running Run 创建门、`(run_id, tool_name, key digest)` 幂等作用域、version CAS、单次 terminal settlement 和 running 恢复只能 unknown。默认 Container、lease/recovery scanning 与 M11-T2 不在本纵切。

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 初始工作区干净，基线 `bb36875`，没有重做前三个已提交范围 |
| `docker compose ... ps` / `docker exec ... pg_isready` | 未执行 / 0 | Compose 权限审查 stream 断开；更窄只读健康检查确认本地数据库 accepting connections |
| handoff PostgreSQL、M1、连续性恢复命令 | 0 | 53 项、7 项、52 个任务/75 个 Markdown 通过；预期 pool timeout，无 ResourceWarning |
| 新内存 ToolExecution 合同首轮 | 1 | 10 项中 9 项通过；测试取消 Run 时漏传领域要求的 `error_code`，未放宽状态机 |
| 修正测试输入后的内存 ToolExecution 合同 | 0 | 10 项通过：owner、running 创建门、幂等、call 冲突、claim/settle CAS、unknown 与终态不可变 |
| 首轮完整 PostgreSQL 65 项 | wrapper 0 / unittest 1 | `0003` 显式约束名与列级自动 CHECK 同名，migration 回滚；后续 fixture setup 连锁产生 63 errors 并在该进程中耗尽连接。清理环境变量的 PowerShell `finally` 遮蔽了 Python 退出码，失败以 unittest 输出为准 |
| 强制回滚诊断事务 | 0 | PostgreSQL 返回 `DuplicateObject / 42710`：`tool_executions_version_check` 已存在；没有提交诊断 DDL |
| 重命名约束后的 migration 专项 | 0 | 首次/重复、checksum、history gap、失败回滚 4 项通过，应用版本为 1/2/3 |
| PostgreSQL ToolExecution 合同、跨进程与事务专项 | 0 | 12 项通过；含 terminal commit 后进程退出 17、completed 恢复、running→unknown 和 settlement trigger 回滚 |
| 完整 `backend.tests.postgres_store_integration -q` | 0 | Run/Event/checkpoint、Approval/Memory、ToolExecution 与 migration 共 65 项通过；预期 pool timeout，无 ResourceWarning |
| Run/Store/Coordinator/LangGraph 受影响定向回归 | 0 | 108 项通过；三条既有 notifier 负向日志，无原始异常文本 |
| `python -S ... test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过 |
| `scripts/verify.ps1`（沙箱首轮） | 1 | 后端 381 项通过、1 项既有 Windows symlink 跳过；Code Agent 与依赖通过；Vue `tsbuildinfo` 报 `TS5033`/`EPERM`，MCP/Compose 尚未执行 |
| 相同完整脚本（批准工作区构建权限后） | 0 | 后端 381 项通过、1 项跳过；Code Agent、依赖、Vue、MCP TypeScript 和 Compose 配置全部通过 |
| 聚焦复审补 Run 终态 replay 后的内存/PostgreSQL 合同 | 0 / 0 | 两个适配器各 10 项通过；终态 Run 拒绝新执行但同幂等键仍返回既有终态 |
| `scripts/check-continuity.ps1` / `git diff --check` | 0 / 0 | 新 ADR/handoff 后 52 个稳定任务、77 个 Markdown 通过；无 whitespace 错误，仅有 Git 的 LF/CRLF 转换提示 |

### 实现与安全证据

- 新增 async `ToolExecutionStore`、稳定冲突/未找到/非法转换错误和 `InMemoryToolExecutionStore`；owner 只由父 Run 验证，新记录只允许在 running Run 以 pending/version 0 创建。
- `0003_tool_execution_store.sql` 只保存 arguments/result/idempotency digest、有界安全摘要和状态元数据；唯一 call、partial idempotency index、状态/version、时间和 outcome CHECK 与领域对象共同 fail closed。
- PostgreSQL 创建锁 Run 行；claim 与 terminal settlement 锁 ToolExecution 行并检查 expected version。并发 claim/settle 各只有一个赢家，同键同参数返回既有权威状态，同键改参数稳定冲突。
- 三个不同 PID 的 probe 依次 prepare、terminal commit 后异常退出、recover；stdout 只含 phase、PID、ID 和布尔结论，不含原始参数、结果或 key。恢复 completed 不重放，遗留 running 只转 terminal unknown。
- 触发器拒绝 completed UPDATE 时整次 settlement 回滚，记录保持 running 且无 result digest；移除触发器后由显式恢复动作转 unknown。数据库错误不回退内存、不输出 DSN 或原始数据。

### 失败、警告与未验证范围

- Compose 权限审查 stream 断开、测试输入漏字段、migration 约束重名、首轮 PostgreSQL 连锁 setup 错误和 ad-hoc PowerShell 退出码遮蔽均保留。后续命令显式保存 `$LASTEXITCODE`；修正后 migration、PostgreSQL、定向、M1 和完整门均通过。
- 完整门首次仍受沙箱 Vue `tsbuildinfo` EPERM 影响，批准后通过；后端保留一条既有 `StarletteDeprecationWarning` 和 1 项 Windows symlink 跳过，数据库不可达负向用例保留预期 pool timeout。
- ToolExecution 持久仲裁不等于外部系统与数据库分布式 exactly-once。没有把 Store 接入默认 Container、ToolRegistry、Approval Runtime、Replanning Runtime 或 HTTP，也没有 lease、heartbeat、自动扫描、补偿、跨 pool/Run/Event/checkpoint 共同事务。
- 本地 Compose 仍是 trust/tmpfs/localhost 课程实例；没有生产鉴权、TLS、持久卷、备份、高可用、容量或跨主机证据。没有读取 Key、调用在线模型或产生费用。

### 结论

- M11-T1 第三个真实 PostgreSQL 纵切达到本地 E3：ToolExecution 共同合同、真实 migration、跨连接 CAS、单次结果结算、提交后异常退出恢复与 fail-closed unknown 均可复现，不是 Fake/Mock 证据。
- `KI-004` 与 `KI-015` 继续保持 mitigated；持久 ToolExecution 缺口已关闭，但 lease/recovery scanning、Run/Event 连接结果未知、默认主链和跨域一致性仍未关闭。M11-T1 保持 `in_progress`，下一动作只做 lease/heartbeat 与 orphan recovery scanning。

## V-20260803-004：M11-T1 ToolExecution 实现提交后恢复锚点

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-03，Asia/Shanghai
- 验证目标：实现提交 `0de735d`（`feat: arbitrate tool executions in postgres`）
- 模式：本地真实 PostgreSQL E3；复用 healthy 的 localhost-only 测试容器。没有读取 Key、调用在线模型或产生费用

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git commit -m "feat: arbitrate tool executions in postgres"` | 0 | 16 个本任务文件固定为实现提交 `0de735d`，2115 行新增、20 行删除 |
| 设置测试 DSN 后 `... -m unittest backend.tests.postgres_store_integration -q` | 0 | 实现提交上真实 PostgreSQL 65 项通过；不可达数据库负向用例保留预期 pool timeout，无 ResourceWarning |
| `python -S ... test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过 |
| `scripts/check-continuity.ps1` / `git status --short` | 0 / 0 | 52 个稳定任务、77 个 Markdown 通过；实现提交后工作区干净 |

### 结论

- M11-T1 PostgreSQL ToolExecution 第三纵切实现提交固定为 `0de735d`；`V-20260803-003` 的 65 项真实数据库集成、108 项受影响回归、381 项完整后端门、失败尝试和未验证范围不变。
- 当前任务保持 `M11-T1 / in_progress`。下一条原子动作只做 lease/heartbeat 与 orphan recovery scanning，不重做前三个纵切，不迁移默认 Container，也不进入 M11-T2。

## V-20260803-005：M11-T1 PostgreSQL Run lease 与 orphan recovery

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-03，Asia/Shanghai
- 验证目标：HEAD `1219737` 上的 M11-T1 第四纵切工作区；实现提交由后续本地 commit 固定
- 任务等级：A 类持久化凭证、并发租约、故障恢复、migration 与跨进程仲裁，时间盒 2–4 小时
- 模式：本地真实 PostgreSQL E3；复用用户已启动的 localhost-only PostgreSQL 17.10 测试容器。没有读取 Key、访问模型 Provider 或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；继续使用已固定的 PostgreSQL 驱动和官方 checkpointer

### 恢复、设计与范围

- 开始时 `git status --short` 干净，最近提交为 `1219737`、`0de735d`、`bb36875`、`cb4fd52`、`bf875be`、`8c6b011`；按强制顺序读取 Git、AGENTS、continuity、实施计划、ADR-0004/0006/0011/0012/0014/0015、最新 handoff、V-003/V-004、后端规约和实际 Store/migration/test。
- `docker exec ... pg_isready` 返回 accepting connections；handoff 恢复集的 PostgreSQL 65 项、M1 7 项和连续性 52/77 通过，不可达数据库负向用例保留预期 pool timeout，无 ResourceWarning。实际代码与记录一致，没有登记漂移。
- `ADR-0016` 固定服务端生成 token、数据库时钟过期、heartbeat/release token+version CAS、`FOR UPDATE SKIP LOCKED` scanner，以及 running ToolExecution=unknown、pending/waiting=cancelled、Run=`run_orphaned` 的 fail-closed 顺序。默认 Container/Coordinator、后台调度、同步 Approval/Memory async 边界与 M11-T2 不在本纵切。

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 | 初始工作区干净，基线 `1219737`，没有重做前三个已提交纵切 |
| `docker exec ... pg_isready` | 0 | 本地数据库 accepting connections |
| handoff PostgreSQL、M1、连续性恢复命令 | 0 | 65 项、7 项、52 个任务/77 个 Markdown 通过；预期 pool timeout，无 ResourceWarning |
| 首轮内存 lease/recovery 专项 | 0 | 11 项通过；owner/running 门、token 隐藏、heartbeat/release CAS、过期领用、scanner 竞争、工具/Run 恢复和部分故障收敛 |
| 首轮 migration/lease/四进程 PostgreSQL 专项 | 1 | migration 4 项与四进程恢复 1 项通过；7 项 PostgreSQL lease 合同因固定 Run 时间晚于未注入的 RunStore 时钟而在 fixture 准备阶段报“时间倒退”，没有放宽领域校验 |
| 给 PostgreSQL 合同注入既有固定时钟后重跑同组 | 0 | migration 4 项、lease 合同 7 项、四进程恢复 1 项，共 12 项通过 |
| PostgreSQL token 摘要与 recovery trigger 专项 | 0 | 9 项通过；表内只有 token SHA-256，Run/Event 插入故障回滚后下一次 scanner 收敛 |
| 首轮完整 `backend.tests.postgres_store_integration -q` | 0 | migration 1–4、前三纵切、lease/recovery 共 75 项通过；预期 pool timeout，无 ResourceWarning |
| 首轮受影响 Run/Store/Coordinator/LangGraph 回归 | 0 | 129 项通过；三条既有 notifier 负向日志，无原始异常文本 |
| `python -S ... test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过 |
| `scripts/verify.ps1`（沙箱首轮） | 1 | 后端 393 项通过、1 项既有 Windows symlink 跳过；Code Agent 与依赖通过；Vue `tsbuildinfo` 报 `TS5033`/`EPERM`，MCP/Compose 尚未执行 |
| 相同完整脚本（批准工作区构建权限后） | 0 | 后端 393 项通过、1 项跳过；Code Agent、依赖、Vue、MCP TypeScript 和 Compose 配置全部通过 |
| 聚焦锁序复审后的内存/PostgreSQL 专项 | 0 / 0 | 内存 lease/recovery 13 项、PostgreSQL lease/recovery 11 项通过；heartbeat 固定 Run row→lease row 锁序，终态 Run 不能续约 |
| 最终完整 PostgreSQL / 受影响回归 | 0 / 0 | PostgreSQL 76 项、Run/Store/Coordinator/LangGraph 131 项通过；预期 pool timeout与三条 notifier 负向日志保持 |
| 锁序修正后的最终 `scripts/verify.ps1`（已批准权限） | 0 | 后端 394 项通过、1 项跳过；Code Agent、依赖、Vue、MCP TypeScript 和 Compose 配置全部通过 |
| `scripts/check-continuity.ps1` / `git diff --check` | 0 / 0 | 52 个稳定任务、79 个 Markdown 通过；无 whitespace 错误，仅有 Git 的 LF/CRLF 转换提示 |

### 实现、并发与隐私证据

- 新增 async `RunLeaseStore`、repr-safe `LeaseToken`、内存参考实现、`0004_run_leases.sql` 和 `PostgresRunLeaseStore`。只有 running owned Run 能 acquire，每 Run 一条记录；普通 executor 不覆盖过期租约。
- PostgreSQL 使用 `clock_timestamp()` 判断 acquire/heartbeat/release/scan 的时间，表只保存 token SHA-256。heartbeat 先锁 Run row 再锁 lease row，并要求 running、未过期、token/version 全部匹配；旧 handle 统一 `run_lease_lost`。
- `claim_expired()` 有界排序并使用 `FOR UPDATE SKIP LOCKED` 轮换 recovery token。prepare 进程创建 execution lease 后以 17 退出，两个 scanner 进程并发时只有一个返回 recovered，第四个审计进程确认 Run failed、running tool unknown、pending tool cancelled、单一终态事件和 lease release；stdout 不含 token、参数、key 或结果。
- 显式 `RunRecoveryService` 先结算 ToolExecution，再用现有 `TerminalCommit` 提交 `failed + run.failed`，最后 release。真实触发器拒绝 recovery event 时 Run 更新整事务回滚而工具保持 unknown；recovery lease 再过期后下一次扫描完成 Run 终态。
- terminal 或 waiting approval Run 只清理 lease，不伪造 `run_orphaned`。取消和非 Store 程序错误不被吞掉；StoreError 只记录稳定 code，凭证和数据库异常文本不越界。

### 失败、警告与未验证范围

- 初次 ADR 路径使用推测文件名、两次窄 `apply_patch` 上下文不匹配和一次 Windows 路径正则无匹配均未修改文件；改按实际路径/上下文后继续。PostgreSQL 合同首轮 fixture 时钟错误保留，注入与既有合同一致的固定时钟后通过，未修改领域时间不变量。
- 完整门首次仍受沙箱 Vue `tsbuildinfo` EPERM 影响，批准后通过；锁序复审后最终完整门再次通过。后端保留一条既有 `StarletteDeprecationWarning` 和 1 项 Windows symlink 跳过，数据库不可达负向用例保留预期 pool timeout。
- ToolExecution 结算、Run/Event 终态和 lease release 是分离事务；触发器测试证明可收敛，不等于原子快照或外部副作用 exactly-once。恢复期间可短暂观察到工具已终态而 Run 仍 running。
- 本纵切不把 lease 注入默认 Container/RunCoordinator，不运行 heartbeat 任务或 lifespan scanner，也不证明统一应用重启恢复、同步 Approval/Memory 的 async 线程/取消、生产鉴权/TLS/持久卷/备份/高可用/容量或跨主机能力。
- 没有读取 Key、调用在线模型或产生费用；本轮外部执行只有用户已启动且 localhost-only 的本机 PostgreSQL 测试容器。

### 结论

- M11-T1 第四个真实 PostgreSQL 纵切达到本地 E3：数据库时钟 lease、opaque token 摘要、heartbeat/version CAS、多进程 scanner 单赢家、running ToolExecution/Run fail-closed 和故障后收敛均可复现，不是 Fake/Mock 证据。
- `KI-004` 与 `KI-016` 保持 mitigated，`KI-023` 保持 open；M11-T1 继续 `in_progress`。下一条原子动作只做显式注入的 RunCoordinator lease 生命周期，不迁移默认 Container/HTTP，不合并同步 Approval/Memory async 边界，也不进入 M11-T2。

## V-20260803-006：M11-T1 Run lease/recovery 实现提交后恢复锚点

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-03，Asia/Shanghai
- 验证目标：实现提交 `1fc55fb`（`feat: recover orphaned runs with postgres leases`）
- 模式：本地真实 PostgreSQL E3；复用 healthy 的 localhost-only 测试容器。没有读取 Key、调用在线模型或产生费用

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git commit -m "feat: recover orphaned runs with postgres leases"` | 0 | 18 个本任务文件固定为实现提交 `1fc55fb`，2553 行新增、16 行删除 |
| `git status --short` / `docker exec ... pg_isready` | 0 / 0 | 提交后工作区干净；本地 PostgreSQL accepting connections |
| 设置测试 DSN 后 `... -m unittest backend.tests.postgres_store_integration -q` | 0 | 实现提交上真实 PostgreSQL 76 项通过；不可达数据库负向用例保留预期 pool timeout，无 ResourceWarning |
| `python -S ... test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 手写 Loop 7 项通过 |
| 新增提交锚点后的 `scripts/check-continuity.ps1` / `git diff --check` | 0 / 0 | 52 个稳定任务、80 个 Markdown 通过；无 whitespace 错误，仅有 Git 的 LF/CRLF 转换提示 |

### 结论

- M11-T1 PostgreSQL Run lease/orphan recovery 第四纵切实现提交固定为 `1fc55fb`；`V-20260803-005` 的 PostgreSQL 76 项、受影响 131 项、完整后端门 394 项、四进程竞争、触发器故障、失败尝试和未验证范围不变。
- 当前任务保持 `M11-T1 / in_progress`。下一条原子动作只做显式注入的 RunCoordinator lease 生命周期，不重做前四个纵切，不迁移默认 Container/HTTP，不合并同步 Approval/Memory async 边界，也不进入 M11-T2。

## V-20260808-001：M11-T1 Coordinator lease 纵切恢复基线

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-08，Asia/Shanghai
- 验证目标：HEAD `beefc1a`；M11 第四纵切实现仍为 `1fc55fb`，其后的学习者提交只修改 M1/M2 练习与 `docs/progress.md`
- 任务等级：A 类并发、持久化租约、取消与 fail-closed，时间盒 2–4 小时
- 模式：本地真实 PostgreSQL E3；没有读取 Key、调用在线模型或产生付费调用，费用 0

### 恢复结果与漂移

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 / 0 | 初始工作区干净；HEAD `beefc1a`，M11 最近实现提交仍为 `1fc55fb` |
| `docker exec ... pg_isready`（首次） | 1 | Docker Engine 未运行；启动已安装的 Docker Desktop 后发现既有测试容器停止 |
| `docker start ai-agent-demo-m11-postgres-1` / `docker exec ... pg_isready` | 0 / 0 | 仅启动既有 localhost 测试容器；数据库 accepting connections |
| 设置测试 DSN 后 `... -m unittest backend.tests.postgres_store_integration -q` | 0 | 真实 PostgreSQL 76 项通过；不可达数据库负向用例保留预期 pool timeout |
| `python -S ... test_manual_agent_loop -q` | 0 | 10 项通过；`beefc1a` 在旧 handoff 的 7 项之后新增 3 项学习者用例 |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、80 个 Markdown 通过 |

### 结论

- M11 PostgreSQL 恢复基线与 `V-20260803-006` 一致，可以继续显式 Coordinator lease 生命周期，不重做前四个纵切。
- 旧 handoff 是不可变历史快照，其 M1 “7 项”预期已被后续学习者提交自然取代；当前可复现基线为 10 项，登记为 `KI-024` 后继续。

## V-20260808-002：M11-T1 显式 RunCoordinator lease 生命周期

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-08，Asia/Shanghai
- 验证目标：HEAD `beefc1a` 上的第五纵切工作区；实现提交随后固定为 `003c7be`
- 任务等级：A 类并发、持久化租约、取消、公共 Store 契约与 fail-closed，时间盒 2–4 小时
- 模式：本地真实 PostgreSQL E3；复用 localhost-only PostgreSQL 17.10 测试容器。没有读取 Key、访问模型 Provider 或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；默认 Container/HTTP 未迁移

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| 首轮 `py_compile` 四个修改模块 | 1 | `py_compile` 尝试写 `backend/app/services/__pycache__` 时权限拒绝；改用不落盘 `compile()` 后四个模块 syntax-ok，不把权限失败描述成代码失败 |
| 既有 Coordinator + 内存 lease 合同 | 0 | 首轮 28 项通过；新增 reservation 合同后 39 项通过 |
| 新增 PostgreSQL lease/Coordinator 专项首轮 | 1 | 15 项中 14 项通过；故障夹具只回拨 `expires_at`，触发既有 `agent_run_leases_time_check`，生产路径尚未执行 |
| 修正夹具保持 acquired < heartbeat < expires 后重跑 | 0 | PostgreSQL lease 共同合同与真实 Coordinator 共 15 项通过 |
| 完整 `backend.tests.postgres_store_integration -q` | 0 | migration 1–4、前四纵切、reservation/Coordinator 共 82 项通过；不可达数据库负向用例保留预期 pool timeout，无 ResourceWarning |
| 最终 Coordinator + lease 合同 | 0 | 41 项通过；覆盖 start 结果未知、reservation 顺序、heartbeat、pause/resume、cancel、双 Coordinator、lease lost、store unavailable 与 release failure |
| Run/Store/Coordinator/LangGraph 核心定向回归 | 0 | 134 项通过；三条既有 notifier 负向日志和一条新增 release 负向稳定日志符合预期 |
| API、Container、OpenAI SDK、framework runtime 回归 | 0 | 68 项通过；保留一条既有 `StarletteDeprecationWarning` |
| 首轮 `scripts/verify.ps1`（沙箱） | 1 | 后端 410 项通过、1 项既有 Windows symlink 跳过；Code Agent 与依赖检查通过；Vue `tsconfig.app.tsbuildinfo` 以 `TS5033`/`EPERM` 失败，后续门未执行 |
| 相同 `scripts/verify.ps1`（工作区构建权限） | 0 | 后端 410 项通过、1 项跳过；Code Agent、依赖、Vue、MCP TypeScript 和 Compose 配置全部通过 |
| `git diff --check` | 0 | 无 whitespace 错误；只有仓库既有 LF/CRLF 转换提示 |

### 实现与风险证据

- `reserve_execution()` 只接受 owned `queued` 或 `waiting_approval` Run；旧 `acquire()` 仍只接受 running。内存与 PostgreSQL 使用同一合同，expired reservation 仍只能由 recovery scanner 轮换，普通 executor 不能覆盖。
- 显式 Coordinator 顺序固定为 reservation → start/resume lifecycle commit → heartbeat → Runtime → stop heartbeat → pause/terminal → release。两个 lease-aware Coordinator 共享同一 Store 时只有一个 Runtime 调用。
- start/resume 提交 CAS 明确失败时释放 reservation；StoreError、取消或连接结果未知时保留租约。scanner 可据真实 Run 状态清理 queued/waiting reservation，或把 running Run 收敛为 `run_orphaned`。
- heartbeat 的 token/version 更新串行化；`run_lease_lost` 或 `store_unavailable` 会取消 Runtime 且不提交伪终态。真实 PostgreSQL 强制过期后，Coordinator 返回 `run_lease_lost`、Run 先保持 running，显式 scanner 随后提交 `run_orphaned` 并释放 recovery lease。
- pause、terminal 和 cancel 停止 heartbeat 后提交 durable 生命周期，再尝试 release；release StoreError 不回滚已提交状态，只记录 stable code 并等待过期 scanner 清理。
- 聚焦复审发现 cancel 在连续两次 CAS 冲突后读到终态的尾部分支可能漏 release，已补 terminal 检查；重跑定向和全量门通过。

### 未验证范围

- 本纵切是显式注入的 Coordinator + 真实 PostgreSQL E3，不迁移默认 Container/HTTP，也没有应用 lifespan scanner、统一应用进程重启或定时恢复调度。
- 没有把 PostgreSQL Approval/Memory 同步 pool 接入 async 主链；线程隔离、取消、超时和 pool 耗尽仍由 `KI-023` 跟踪。
- lease 仲裁数据库执行资格，不包含外部副作用与数据库的分布式 exactly-once；running ToolExecution 结果未知仍按 `ADR-0015` 终结为 unknown。
- 完整门首轮 Vue 写权限失败与最终通过均保留；后端仍有一条既有 Starlette 警告和一项 Windows symlink 能力跳过。
- 没有读取 Key、调用在线模型、访问远程服务、产生费用、配置 remote 或执行 push。

### 结论

- M11-T1 第五个真实纵切达到本地 E3，`ADR-0017` 的 reservation/heartbeat/release/fail-closed 顺序可由内存合同和真实 PostgreSQL 复现。
- `KI-004`、`KI-016` 保持 mitigated，`KI-023` 保持 open；M11-T1 继续 `in_progress`。下一原子动作只做显式 recovery scanner 调度生命周期，不迁移默认 Container/HTTP，不进入 M11-T2。

## V-20260808-003：M11-T1 Coordinator lease 实现提交后恢复锚点

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-08，Asia/Shanghai
- 验证目标：实现提交 `003c7be`（`feat: coordinate runs with postgres leases`）
- 模式：本地真实 PostgreSQL E3；没有读取 Key、调用在线模型或产生费用

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git commit -m "feat: coordinate runs with postgres leases"` | 0 | 11 个本任务文件固定为实现提交 `003c7be`，1345 行新增、115 行删除 |
| `git status --short` / `docker exec ... pg_isready` | 0 / 0 | 实现提交后工作区干净；本地 PostgreSQL accepting connections |
| 设置测试 DSN 后 `... -m unittest backend.tests.postgres_store_integration -q` | 0 | 实现提交上真实 PostgreSQL 82 项通过；不可达数据库负向用例保留预期 pool timeout，无 ResourceWarning |
| `python -S ... test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后学习者当前 M1 10 项通过 |
| `scripts/check-continuity.ps1` | 0 | 新增 ADR 后 52 个稳定任务、81 个 Markdown 通过 |

### 结论

- `003c7be` 可从干净工作区恢复；`V-20260808-002` 的 134 项核心回归、68 项 API/Container/SDK 回归、后端 410 项完整门、Vue/MCP/Compose 结果与未验证范围不变。
- 当前任务保持 `M11-T1 / in_progress`。下一原子动作只设计并实现显式 recovery scanner 调度生命周期，不迁移默认 Container/HTTP、不合并同步 Approval/Memory async 边界，也不进入 M11-T2。

## V-20260808-004：M11-T1 Coordinator lease 连续性闭环

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-08，Asia/Shanghai
- 验证目标：实现提交 `003c7be` 上的 continuity 工作区
- 模式：纯文档闭环；离线、无 Key、费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、82 个 Markdown 通过；新增 ADR/handoff 引用和任务状态一致 |
| `git diff --check` | 0 | 无 whitespace 错误；仅有 Git 的 LF/CRLF 转换提示 |
| 定向搜索旧“下一步/四纵切/76+7 恢复基线”措辞 | 1 | 指定动态 status、实施计划第五纵切和新 handoff 中无旧命中；退出 1 表示 `rg` 未匹配，不是检查失败 |

### 结论

- implementation plan、ADR、known issue、status、verification 和新 handoff 已分别记录第五纵切事实、残余边界与下一条 scanner 调度原子动作。
- 本步骤没有代码或行为变化，因此不重复运行后端/前端业务测试；实现提交 `003c7be` 的 PostgreSQL 82、核心 134、API/Container/SDK 68 与完整门 410 项证据继续引用 `V-20260808-002`/`003`。

## V-20260808-005：M11-T1 显式 recovery supervisor 调度生命周期

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-08，Asia/Shanghai
- 验证目标：基线 HEAD `8297ac0` 上的第六纵切工作区；实现提交 `e63d718`（`feat: schedule postgres run recovery`）
- 任务等级：A 类并发、持久恢复、取消和后台任务生命周期；时间盒 2–4 小时
- 模式：本地真实 PostgreSQL E3；复用 localhost-only PostgreSQL 17.10 测试容器。没有读取 Key、访问在线模型或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；没有修改 migration、Store Protocol、默认 Container、HTTP 或 FastAPI lifespan

### 恢复基线

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 / 0 | 初始工作区干净；HEAD `8297ac0`，第五纵切实现提交为 `003c7be` |
| `docker exec ... pg_isready` | 0 | 本地测试数据库 accepting connections |
| 设置测试 DSN 后 `... -m unittest backend.tests.postgres_store_integration -q` | 0 | 修改前真实 PostgreSQL 82 项通过；不可达数据库负向用例保留预期 pool timeout |
| `python -S ... test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 当前 10 项通过 |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、82 个 Markdown 通过 |

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| 首轮 recovery/supervisor 单元测试 | 1 | 13 项中 12 项通过；长周期关闭用例错误等待“第二次扫描”并超时，生产路径未失败 |
| 修正夹具等待首轮完成后重跑 | 0 | recovery/supervisor 13 项通过；补调用方取消合同后最终 14 项通过 |
| 新增 PostgreSQL supervisor 单例首轮 | 1 | Run 已提交 `failed` 后测试立即 close，取消尚未完成 release 的扫描；观测到陈旧 lease 和 psycopg rollback 清理警告，符合分离事务可收敛边界，但未满足本用例完整自动恢复目标 |
| 改为等待 Run 终态与 lease 删除同时可见后重跑单例 | 0 | 真实 supervisor 自动 claim、提交 `run_orphaned`、release 并关闭；1 项通过，无 ResourceWarning |
| 最终完整 `backend.tests.postgres_store_integration -q` | 0 | migration 1–4、前五纵切和 supervisor 自动恢复共 83 项通过；不可达数据库负向 pool timeout 为预期输出 |
| Run/Store/Coordinator/recovery/LangGraph 核心定向回归 | 0 | 154 项通过；既有 release/notifier 安全负向日志符合预期 |
| `python -S ... test_manual_agent_loop -q` | 0 | M1 隔离 10 项通过 |
| 不落盘 `compile()` / `git diff --check` | 0 / 0 | 3 个修改 Python 文件 syntax-ok；无 whitespace 错误，仅有既有 LF/CRLF 转换提示 |
| 首次 `git add`（沙箱） | 1 | `.git/index.lock` 权限拒绝；未修改源码或 Git 历史 |
| 获本地 Git 写权限后 `git commit -m "feat: schedule postgres run recovery"` | 0 | 3 个实现/测试文件固定为提交 `e63d718` |
| 提交后 recovery/supervisor 单元集 / PostgreSQL 自动恢复单例 | 0 / 0 | 14 项 / 1 项再次通过，提交后工作区干净 |

### 实现与风险证据

- 显式 `RunRecoverySupervisor` 立即启动首轮扫描，只有一个后台 task 串行 await 既有 `RunRecoveryService.scan_once()`，每轮完成后再等待周期；同一实例不会重叠 scan。
- `start()` 幂等但关闭后不可重启；`created/running/closing/failed/closed` 固定并发 start/close 语义。`close()` 取消并 await 唯一 task，扫描清理异常不吞；调用方取消 close 时 `CancelledError` 继续传播。
- claim 级 `StoreError` 和单 Run `FAILED` 结果只记录稳定 error code，不输出异常文本，下一周期继续扫描；非 Store 程序错误把 supervisor 置为 failed，并在 close 时重新抛出。
- 构造阶段把 scan limit 固定为 1–100、recovery TTL 固定为大于 0 且不超过 1 天，与既有 lease Store 边界一致，避免非法配置延迟到后台 task。
- 聚焦复审先后修正长周期测试观察点、终态/release 分离事务测试竞态、close 调用方取消吞没风险、关闭期间假启动和 Store 上限延迟失败；修正后定向与 PostgreSQL 集均通过。

### 未验证范围与全量门说明

- 本纵切只提供显式 service/supervisor 与真实 PostgreSQL E3，不注入默认 Container/HTTP/FastAPI lifespan，不证明统一应用进程重启或生产部署调度。
- shutdown 在 in-flight scan 中取消时，已提交的 Run/Tool 状态与陈旧 recovery lease 仍按 `ADR-0016` 由下一次过期扫描收敛；没有证明任意驱动/网络中断点都无清理警告或立即删除 lease。
- PostgreSQL Approval/Memory 同步 pool 的 async 线程隔离、取消、超时和耗尽仍未处理，`KI-023` 保持 open；外部副作用 exactly-once 仍不成立。
- 本原子步骤没有依赖、migration、公共 Store Protocol、默认 composition、HTTP 或跨前后端契约变化，也不是里程碑验收/发布门；按课程交付协议只运行定向回归，没有重复运行 `scripts/verify.ps1`、Vue、MCP TypeScript 或 Compose 全量门。
- 本地 Compose 仍是 localhost trust/tmpfs 测试实例，不是生产鉴权、TLS、持久卷、备份、高可用、跨主机或容量证据。没有配置 remote 或执行 push。

### 结论

- M11-T1 第六个真实纵切达到本地 E3；显式 recovery supervisor 的单任务调度、故障续跑、取消清理和 PostgreSQL 自动收敛可以从提交 `e63d718` 复现。
- `KI-004`、`KI-016` 继续保持 mitigated，不能因显式 supervisor 关闭；M11-T1 保持 `in_progress`。下一原子动作仍须由本轮连续性文档在不迁移默认 HTTP、不进入 M11-T2 的范围内固定。

## V-20260808-006：M11-T1 recovery supervisor 连续性闭环

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-08，Asia/Shanghai
- 验证目标：实现提交 `e63d718` 上的 continuity 工作区
- 模式：纯文档闭环；离线、无 Key、费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、84 个 Markdown 通过；新增 ADR/handoff 引用、M11-T1 状态和任务编号一致 |
| `git diff --check` | 0 | 无 whitespace 错误；仅有 Git 的 LF/CRLF 转换提示 |
| 定向搜索动态文档中的旧 scanner 下一动作/五纵切措辞 | 1 | `status.md`、known issue 和新 handoff 中无旧命中；退出 1 表示 `rg` 未匹配，不是检查失败 |
| 定向搜索 `e63d718`、`V-20260808-005`、`ADR-0018`、83/84 计数和 execution composition | 0 | status、known issue、实施计划、ADR 与 handoff 的实现事实、未验证范围和下一动作相互一致 |

### 结论

- implementation plan、ADR、backend standards、known issue、status、verification 和新 handoff 已分别记录第六纵切事实、显式 composition 边界与下一条原子动作。
- 本步骤没有代码或行为变化，因此不重复运行业务测试或全仓门；实现提交 `e63d718` 的 PostgreSQL 83、核心 154、supervisor/recovery 14、M1 10 与提交后单例证据继续引用 `V-20260808-005`。

## V-20260808-007：M11-T1 显式 PostgreSQL execution composition

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-08，Asia/Shanghai
- 验证目标：基线 HEAD `e6e53dd` 上的第七纵切工作区；实现提交 `1d4386c`（`feat: compose postgres execution lifecycle`）
- 任务等级：A 类资源所有权、取消、持久恢复和跨进程生命周期；时间盒 2–4 小时
- 模式：本地真实 PostgreSQL E3；复用 localhost-only PostgreSQL 17.10 测试容器。没有读取 Key、访问在线模型或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；没有修改 migration、Store Protocol、默认 Container、HTTP、FastAPI lifespan 或同步 Approval/Memory 调用边界

### 恢复基线

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 / 0 | 初始工作区干净；HEAD `e6e53dd`，第六纵切实现提交 `e63d718` 与文档锚点存在 |
| `docker exec ... pg_isready` | 0 | 本地测试数据库 accepting connections |
| 设置测试 DSN 后 `... -m unittest backend.tests.postgres_store_integration -q` | 0 | 修改前真实 PostgreSQL 83 项通过；不可达数据库负向用例保留预期 pool timeout |
| `... test_run_recovery test_run_recovery_supervisor -q` | 0 | recovery/supervisor 14 项通过 |
| `python -S ... test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 当前 10 项通过 |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、84 个 Markdown 通过 |

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| 首轮 `backend.tests.test_postgres_execution -v` | 0 | composition 启动/关闭、幂等、context manager、setup/config 失败、关闭失败与取消共 8 项通过 |
| 增加 supervisor start 失败逆序清理后重跑 | 0 | 最终 9 项生命周期合同通过 |
| `PostgresExecutionCompositionProcessTest -v` | 0 | 1 项真实 PostgreSQL 不同 PID 自动恢复通过；旧 holder 退出 17，新 composition 自动提交 `run_orphaned`、唯一失败事件并释放 lease |
| 系统 `python -m unittest ...` | 1 | Windows 系统 Python 报“指定的登录会话不存在”，测试未启动；改用仓库 `.venv` 后通过，未修改系统设置 |
| `python -m py_compile ...` | 1 | 现有 `backend/app/__pycache__` 临时 pyc 写入被拒绝；该次不记为语法通过 |
| 不落盘 `compile()` | 0 | 4 个修改 Python 文件 `syntax-ok`；单测导入和两个 probe 子进程也已实际执行相关模块 |
| 完整 `backend.tests.postgres_store_integration -q` | 0 | migration 1–4、前六纵切和新 composition 共 84 项通过；不可达数据库负向 pool timeout 为预期输出，无 ResourceWarning |
| composition/Run/Store/Coordinator/recovery/LangGraph 核心定向回归 | 0 | 155 项通过；既有 lease release/notifier 安全负向日志符合预期 |
| `python -S ... test_manual_agent_loop -q` | 0 | M1 隔离 10 项通过 |
| `git diff --check` | 0 | 无 whitespace 错误；仅有 Git 的 LF/CRLF 转换提示 |
| `git commit -m "feat: compose postgres execution lifecycle"` | 0 | 4 个实现/测试文件固定为提交 `1d4386c` |
| 提交后 composition 单元集 / PostgreSQL 跨 PID 单例 | 0 / 0 | 9 项 / 1 项再次通过 |

### 实现与风险证据

- `PostgresExecutionComposition.open()` 真实执行 persistence open/setup，构造共享同一组 PostgreSQL adapters 的 lease-aware Coordinator、恢复服务和 supervisor，再启动 scanner；依赖存在或 import 成功没有被当作完成证据。
- setup、配置或 supervisor start 失败均回收已经取得的资源；正常关闭固定 supervisor 先于 persistence，重复关闭幂等，supervisor 关闭失败仍尝试关闭 pool，调用方取消继续传播。
- 旧 holder 与新 composition PID 不同；新进程没有手动调用 scanner，恢复完全来自 composition 启动的 supervisor。探针只输出阶段、PID 和布尔审计结果，并检查私有输入/幂等键没有泄漏。
- 聚焦复审补齐 supervisor start 部分失败清理、测试 patch 栈自动回收和崩溃进程对 active execution task 的强引用；同时明确 composition close 不隐式改变 Coordinator 的用户取消语义。

### 未验证范围与全量门说明

- 调用方必须在 composition close 前停止接收 execute/resume 并等待 active Coordinator 操作结束；本纵切没有 admission stop、drain、shutdown timeout 或强制终止 Runtime 的公共合同。若违反前置条件，活跃 Runtime/heartbeat 仍可能访问即将关闭的 pool。
- 默认 `ApplicationContainer`、`create_app()`、FastAPI lifespan 和 HTTP 未迁移，不能把显式 probe 描述成默认应用重启恢复。PostgreSQL Approval/Memory 同步 pool 的 async 线程隔离、取消、超时和耗尽仍未处理，`KI-023` 保持 open。
- lease、ToolExecution、Run/Event 和外部副作用仍不构成 exactly-once；本地 Compose 仍是 localhost trust/tmpfs 测试实例，不是生产鉴权、TLS、持久卷、备份、高可用、跨主机或容量证据。
- 本原子步骤没有依赖、migration、公共 Store Protocol、默认 composition/HTTP 或跨前后端契约变化，也不是里程碑验收/发布门；按课程交付协议只运行定向回归，没有重复运行 `scripts/verify.ps1`、Vue、MCP TypeScript 或 Compose 全量门。第五纵切完整门继续引用 `V-20260808-002`/`003`。
- 没有配置 remote 或执行 push。

### 结论

- M11-T1 第七个真实纵切达到本地 E3；显式 PostgreSQL execution composition 的启动、失败清理、关闭顺序和跨 PID 自动恢复可以从提交 `1d4386c` 复现。
- `KI-004`、`KI-016` 继续保持 mitigated，`KI-023` 保持 open；M11-T1 保持 `in_progress`。下一原子动作是先固定 active Coordinator quiesce/drain，再考虑默认应用接线。

## V-20260808-008：M11-T1 execution composition 连续性闭环

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-08，Asia/Shanghai
- 验证目标：实现提交 `1d4386c` 上的 continuity 工作区
- 模式：纯文档闭环；离线、无 Key、费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、86 个 Markdown 通过；新增 ADR/handoff、M11-T1 状态和引用一致 |
| `git diff --check` | 0 | 无 whitespace 错误；仅有 Git 的 LF/CRLF 转换提示 |
| 定向搜索 `1d4386c`、`V-20260808-007`、`ADR-0019`、active execution quiesce 和 86 个 Markdown | 0 | status、known issue、实施计划、backend standards、ADR 与 handoff 的实现事实、未验证范围和下一动作相互一致 |

### 结论

- implementation plan、ADR、backend standards、known issue、status、verification 和新 handoff 已分别记录第七纵切事实、显式 composition 所有权、active Run 关闭前置条件与下一条 quiesce/drain 原子动作。
- 本步骤没有代码或行为变化，因此不重复运行业务测试或全仓门；实现提交 `1d4386c` 的 composition 9、PostgreSQL 84、核心 155、M1 10 与提交后跨 PID 单例证据继续引用 `V-20260808-007`。

## V-20260808-009：M11-T1 Coordinator admission stop 与 active quiesce

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-08，Asia/Shanghai
- 验证目标：基线 HEAD `acd4f40` 上的第八纵切工作区；实现提交 `2e94640`（`feat: quiesce postgres run execution`）
- 任务等级：A 类并发 admission、取消、资源关闭和持久结果未知恢复；时间盒 2–4 小时
- 模式：本地真实 PostgreSQL E3；复用 localhost-only PostgreSQL 17.10 测试容器。没有读取 Key、访问在线模型或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；没有修改 migration、Store Protocol、默认 Container、HTTP、FastAPI lifespan 或同步 Approval/Memory 调用边界

### 恢复基线

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 / 0 | 初始工作区干净；HEAD `acd4f40`，第七纵切实现 `1d4386c` 与文档锚点存在 |
| `docker exec ... pg_isready` | 0 | 本地测试数据库 accepting connections |
| 设置测试 DSN 后 `... -m unittest backend.tests.postgres_store_integration -q` | 0 | 修改前真实 PostgreSQL 84 项通过；不可达数据库负向用例保留预期 pool timeout |
| `... test_postgres_execution -q` | 0 | 修改前 composition 9 项通过 |
| `python -S ... test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 当前 10 项通过 |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、86 个 Markdown 通过 |

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| 首轮 `backend.tests.test_run_coordinator_quiesce -v` | 1 | 6 项中 5 项通过；调用方取消用例在 quiesce 协程实际启动前立即取消，未进入待验证生命周期，生产断言未失败 |
| 修正夹具等待 `quiescing` 后重跑 | 0 | 6 项全部通过：空闲幂等、execute/resume 拒绝、自然 drain、timeout abandon、调用方取消与并发共享 |
| `test_postgres_execution` + quiesce 单元集 | 0 | 最终 18 项通过；composition 关闭顺序、timeout 配置、取消传播和 quiesce 程序错误下不提前关闭 pool 均固定 |
| `PostgresExecutionCompositionProcessTest -v` | 0 | 3 项真实 PostgreSQL 通过：跨 PID 崩溃恢复、自然完成关闭、timeout 后 running+lease 由新 composition 自动恢复 |
| 不落盘 `compile()` | 0 | 5 个修改 Python 文件 `syntax-ok` |
| 完整 `backend.tests.postgres_store_integration -q` | 0 | migration 1–4、前七纵切和 quiesce 共 86 项通过；不可达数据库负向 pool timeout 为预期输出，无 ResourceWarning |
| composition/Run/Store/Coordinator/recovery/LangGraph 核心定向回归 | 0 | 164 项通过；既有 lease release/notifier 安全负向日志符合预期 |
| API、Container、OpenAI SDK、framework runtime 回归 | 0 | 68 项通过；保留一条既有 `StarletteDeprecationWarning` |
| `python -S ... test_manual_agent_loop -q` | 0 | M1 隔离 10 项通过 |
| `git diff --check` | 0 | 无 whitespace 错误；仅有 Git 的 LF/CRLF 转换提示 |
| `git commit -m "feat: quiesce postgres run execution"` | 0 | 5 个实现/测试文件固定为提交 `2e94640` |
| 提交后 quiesce+composition 单元集 / PostgreSQL composition 集 | 0 / 0 | 18 项 / 3 项再次通过 |

### 实现与风险证据

- Coordinator 在既有 active lock 内从 accepting 切为 quiescing，之后 execute/resume 统一返回稳定 `coordinator_not_accepting`；并发 quiesce 共享一个 drain task，quiesced 不可重启。
- 自然完成宽限期内，Runtime 继续正常提交 terminal 并 release。宽限期超时后，内部 `coordinator_shutdown` 取消 task，`_drive_running` 停止 heartbeat 并 abandon lease，不写 `run.cancelled` 或用户取消失败码。
- 调用方取消 quiesce 时，内部 drain 完成后才传播 `CancelledError`。聚焦复审又补全对所有快照 task 的 gather，避免自然失败但调用方已离开时留下未检索 task 异常。
- composition close 固定 Coordinator、supervisor、persistence 顺序。真实 PostgreSQL 证明自然 drain 期间 pool 保持可用；timeout 后审计读到 running、仅 `run.started`、lease 仍存在，下一 composition 自动提交 `run_orphaned` 并释放 lease。

### 未验证范围与全量门说明

- timeout 是自然完成宽限期，不是整个 Runtime 或进程的硬终止上限；若 Runtime 非协作地吞掉 task cancellation，quiesce 会继续等待清理，不能宣称硬停止线程、子进程或外部请求。
- admission stop 只覆盖 execute/resume 和已登记 active task。默认 HTTP/命令入口尚未停用，现有显式用户 `cancel()` 等非执行 Store 操作仍需调用方在 composition close 前停止，不能把本纵切描述成完整 FastAPI shutdown。
- 默认 `ApplicationContainer`、`create_app()`、FastAPI lifespan 和 HTTP 未迁移。PostgreSQL Approval/Memory 同步 pool 的 async 线程隔离、取消、超时和耗尽仍未处理，`KI-023` 保持 open。
- 无 lease Coordinator 可以自然 drain，但 timeout 后可由 scanner 收敛的证据只适用于显式 lease-aware PostgreSQL composition。lease、ToolExecution、Run/Event 与外部副作用仍不构成 exactly-once。
- 本原子步骤没有依赖、migration、Store Protocol、默认 HTTP 或跨前后端契约变化，也不是里程碑验收/发布门；核心 164 与 API/Container 68 项已覆盖共享 Coordinator 兼容性，因此没有重复运行 `scripts/verify.ps1`、Vue、MCP TypeScript 或 Compose 全量门。第五纵切完整门继续引用 `V-20260808-002`/`003`。
- 本地 Compose 仍是 localhost trust/tmpfs 测试实例，不是生产鉴权、TLS、持久卷、备份、高可用、跨主机或容量证据。没有配置 remote 或执行 push。

### 结论

- M11-T1 第八个真实纵切达到本地 E3；Coordinator admission stop、active drain、shutdown timeout fail-closed 和 composition 关闭顺序可以从提交 `2e94640` 复现。
- `KI-004`、`KI-016` 继续保持 mitigated，`KI-023` 保持 open；M11-T1 保持 `in_progress`。下一原子动作应处理同步 PostgreSQL Approval/Memory 的 async 隔离，再考虑默认应用接线。

## V-20260808-010：M11-T1 Coordinator quiesce 连续性闭环

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-08，Asia/Shanghai
- 验证目标：实现提交 `2e94640` 上的 continuity 工作区
- 模式：纯文档闭环；离线、无 Key、费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、88 个 Markdown 通过；新增 ADR/handoff、M11-T1 状态和引用一致 |
| `git diff --check` | 0 | 无 whitespace 错误；仅有 Git 的 LF/CRLF 转换提示 |
| 定向搜索 `2e94640`、`V-20260808-009`、`ADR-0020`、164 项、88 个 Markdown 和 Approval/Memory async 下一动作 | 0 | status、known issue、实施计划、backend standards、ADR 与 handoff 的事实、未验证范围和下一动作相互一致 |

### 结论

- implementation plan、ADR、backend standards、known issue、status、verification 和新 handoff 已分别记录第八纵切事实、Coordinator quiesce 所有权、shutdown 结果未知边界与下一条同步 Store async 隔离动作。
- 本步骤没有代码或行为变化，因此不重复运行业务测试或全仓门；实现提交 `2e94640` 的专用 18、PostgreSQL 86、核心 164、API/Container 68、M1 10 与提交后真实 composition 3 项证据继续引用 `V-20260808-009`。

## V-20260808-011：M11-T1 PostgreSQL 同步 Store async 隔离

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-08，Asia/Shanghai
- 验证目标：基线 HEAD `0c30a28` 上的第九纵切工作区；实现提交 `bffeab7`（`feat: isolate postgres sync stores`）
- 任务等级：A 类同步数据库 I/O、线程取消、结果未知和资源关闭；时间盒 2–4 小时
- 模式：本地真实 PostgreSQL E3；复用 localhost-only PostgreSQL 17.10 测试容器。没有读取 Key、访问在线模型或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；没有修改 migration、同步 Approval/Memory Protocol、默认 Container、HTTP 或 FastAPI lifespan

### 恢复基线

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 / 0 | 初始工作区干净；HEAD `0c30a28`，第八纵切实现 `2e94640` 与文档锚点存在 |
| `docker exec ... pg_isready` | 0 | 本地测试数据库 accepting connections |
| 设置测试 DSN 后 `... -m unittest backend.tests.postgres_store_integration -q` | 0 | 修改前真实 PostgreSQL 86 项通过；不可达数据库负向用例保留预期 pool timeout |
| `... test_run_coordinator_quiesce test_postgres_execution -q` | 0 | 修改前 quiesce+composition 18 项通过 |
| `python -S ... test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 10 项通过 |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、88 个 Markdown 通过 |

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| 首轮 `backend.tests.test_postgres_async_stores -v` | 1 | 7 项中 6 项通过；共享 40 ms timeout 也使占位读返回预期 timeout，但夹具清理错误地期待成功。修正清理断言，没有放宽生产行为 |
| 最终 `backend.tests.test_postgres_async_stores -q` | 0 | 9 项通过：配置、事件循环非阻塞、排队取消、running 结果未知、调用方取消、参数快照、owned open、in-flight close 和双 pool 异常清理 |
| 新增真实 PostgreSQL async façade/pool exhaustion/composition close 专项 | 0 | 3 项通过；真实审批/记忆事务、共享 sync pool 耗尽 `store_unavailable`、composition 等待 in-flight worker 均实际执行 |
| 完整 `backend.tests.postgres_store_integration -q` | 0 | migration 1–4、前八纵切和本 async 隔离共 89 项通过；不可达数据库负向 pool timeout 为预期输出，无 ResourceWarning |
| async bridge、quiesce/composition、Approval/Memory 合同与 Runtime 定向回归 | 0 | 56 项通过 |
| `python -S ... test_manual_agent_loop -q` | 0 | M1 隔离 10 项通过 |
| 不落盘 `compile()` / `git diff --check` | 0 / 0 | 4 个修改 Python 文件语法通过，无 whitespace 错误；仅有 Git 的 LF/CRLF 转换提示 |
| `git commit -m "feat: isolate postgres sync stores"` | 0 | 4 个实现/测试文件固定为提交 `bffeab7` |
| 提交后新增单元与真实 PostgreSQL 专项 | 0 | 12 项再次通过 |

### 实现与风险证据

- 一个显式 `PostgresSyncStoreBridge` 用有界专用线程池承载同步 Approval/Memory 调用；worker 数与共享 sync pool `max_size` 对齐，两个 async façade 共用同一 admission 和 in-flight 所有权。
- async façade 在提交前复制审批参数。调用超时时先尝试取消尚未开始的 submission：取消成功时 `result_unknown=false` 且写操作不执行；已运行时返回稳定 `store_operation_timeout`、`result_unknown=true`，底层 worker 不被描述成硬取消，也没有自动重试或结果复用。
- 调用方取消只取消等待；已运行 worker 继续被 bridge 追踪。close 从 accepting 进入 quiescing，拒绝新调用，等待所有 worker 后关闭 executor；`PostgresPersistence.close()` 再按 bridge、sync pool、async pool 排序。
- 同步 pool open 也成为 owned worker：调用方取消时先等待 open 结束，再关闭两类 pool。聚焦复审补回同步 pool close 失败时仍关闭 async pool 的原有资源不变量。
- 真实 PostgreSQL 证明 async façade 执行了审批 resolve/grant consume、消息/事实写读、连接池耗尽映射和 composition shutdown 等待，不是 import 或 Mock 证据。

### 未验证范围与全量门说明

- 默认 `ApplicationContainer`、`create_app()`、FastAPI lifespan 和 HTTP 仍使用既有内存主链，没有迁移到 PostgreSQL composition 或 async façade；`KI-023` 只降为 mitigated，不能关闭。
- 只有通过 async façade 提交的调用受 bridge admission/in-flight 追踪。为兼容既有合同而保留的直接同步 `approval_store`/`memory_store` 调用不受该 bridge 追踪，调用方仍须自行停止后再 close。
- Python 线程中的数据库调用不能硬取消。running timeout/cancel 后结果可能未知，bridge 只等待并丢弃无人接收的结果；调用方不得自动重试有副作用写操作。没有查询级 PostgreSQL statement timeout、线程强杀或进程级硬终止证据。
- Approval 与 Memory 共用同步 pool/bridge，但仍与 async Run/Event/checkpoint pool 分离，没有跨 pool 事务或外部副作用 exactly-once。
- 本原子步骤没有依赖、migration、公共 Store Protocol、默认 HTTP 或跨前后端契约变化，也不是里程碑验收/发布门；真实 PostgreSQL 89 与定向 56 已覆盖修改面，因此没有重复运行 `scripts/verify.ps1`、Vue、MCP TypeScript 或 Compose 全量门。第五纵切完整门继续引用 `V-20260808-002`/`003`。
- 本地 Compose 仍是 localhost trust/tmpfs 测试实例，不是生产鉴权、TLS、持久卷、备份、高可用、跨主机或容量证据。没有配置 remote 或执行 push。

### 结论

- M11-T1 第九个真实纵切达到本地 E3；同步 Approval/Memory 的 async 线程隔离、取消/超时结果未知、共享 pool 耗尽和 composition in-flight close 可从提交 `bffeab7` 复现。
- `KI-023` 更新为 mitigated；`KI-004`、`KI-016` 继续保持 mitigated。M11-T1 保持 `in_progress`，下一原子动作应处理 opt-in PostgreSQL 默认应用 composition 与 HTTP/lifespan admission，而不是进入 M11-T2。

## V-20260808-012：M11-T1 PostgreSQL 同步 Store async 隔离连续性闭环

- 任务：`M11-T1 / in_progress`
- 时间：2026-08-08，Asia/Shanghai
- 验证目标：实现提交 `bffeab7` 上的 continuity 工作区
- 模式：纯文档闭环；离线、无 Key、费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、90 个 Markdown 通过；新增 ADR/handoff、M11-T1 状态和引用一致 |
| `git diff --check` | 0 | 无 whitespace 错误；仅有 Git 的 LF/CRLF 转换提示 |
| 定向搜索 `bffeab7`、`V-20260808-011`、`ADR-0021`、89/56/12 项、`KI-023` 与 opt-in application composition 下一动作 | 0 | status、known issue、实施计划、backend standards、ADR 与 handoff 的事实、未验证范围和下一动作相互一致 |

### 结论

- implementation plan、ADR、backend standards、known issue、status、verification 和新 handoff 已分别记录第九纵切事实、owned worker/结果未知边界与下一条 opt-in PostgreSQL application composition 动作。
- 本步骤没有代码或行为变化，因此不重复运行业务测试或全仓门；实现提交 `bffeab7` 的 async bridge 9、PostgreSQL 89、定向 56、M1 10 与提交后新增专项 12 项证据继续引用 `V-20260808-011`。

## V-20260808-013：M11-T1 PostgreSQL application composition 与任务验收

- 任务：`M11-T1 / verified`
- 时间：2026-08-08，Asia/Shanghai
- 验证目标：基线 HEAD `1e867bc` 上的第十纵切工作区；实现提交 `be2c818`（`feat: compose postgres application lifecycle`）
- 任务等级：A 类默认 composition、数据库生命周期、HTTP/命令 admission 与 async/sync I/O 边界；时间盒 2–4 小时
- 模式：默认离线 E3 与本地真实 PostgreSQL E3；复用 localhost-only PostgreSQL 17.10 测试容器。没有读取 Key、访问在线模型或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除依赖；没有修改 migration、公共同步 Store Protocol、旧 Run HTTP/SSE 响应合同、前端 API 或部署 Compose

### 恢复基线

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 / 0 | 初始工作区干净；HEAD `1e867bc`，第九纵切实现 `bffeab7` 与文档锚点存在 |
| `docker exec ... pg_isready` | 0 | 本地测试数据库 accepting connections |
| 设置测试 DSN 后 `backend.tests.postgres_store_integration -q` | 0 | 修改前真实 PostgreSQL 89 项通过；不可达数据库负向用例保留预期 pool timeout |
| `test_postgres_async_stores -q` | 0 | 修改前 async bridge 9 项通过 |
| `test_run_coordinator_quiesce test_postgres_execution -q` | 0 | 修改前 quiesce+composition 18 项通过 |
| `python -S ... test_manual_agent_loop -q` | 0 | 修改前 M1 隔离 10 项通过 |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、90 个 Markdown 通过 |

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| 新增 Settings/application lifecycle 首轮 25 项 | 1 | 24 项通过；admission close 测试只让出一次 loop 就断言 quiescing，owned close task 尚未调度。夹具改为等待明确状态，生产状态机未放宽 |
| 新增 Settings/application lifecycle 修正后 25 项 | 0 | persistence gate、DSN 脱敏、active drain、并发 close、启动回滚、关闭顺序和命令拒绝通过 |
| Settings、Container、API、MCP、bridge、quiesce/composition 定向回归 | 0 | 98 项通过；仅有既有 Starlette/httpx 弃用警告 |
| 新增真实 FastAPI/PostgreSQL application 专项首轮 | 1 | 数据库操作完成，测试误用不存在的 `ApprovalDecision.allowed` 字段；改为既有 `approved` 合同，生产代码未修改 |
| 最终完整 `backend.tests.postgres_store_integration -q` | 0 | 前九纵切与新增 application composition 共 91 项通过；两个 FastAPI lifespan 跨应用写/删同一 fact，Container Approval façade 实际 grant/consume；不可达数据库 pool timeout 为预期输出 |
| 首轮 `scripts/verify.ps1` | 1 | 后端 462 项中 461 通过、1 项既有 Windows symlink 跳过；TypeScript MCP E2E 单项在 5 秒内 startup timeout，后续门未执行 |
| 单独 `backend.tests.test_mcp_client_e2e -v` | 0 | 4 项在 0.964 秒内通过；未修改 MCP timeout 或生产行为 |
| 第二轮 `scripts/verify.ps1` | 1 | 后端 462 项通过、1 项既有 symlink 跳过，Code Agent 与依赖通过；Vue 写 `tsconfig.app.tsbuildinfo` 被沙箱以 `TS5033/EPERM` 拒绝，MCP build/Compose 尚未执行 |
| 相同完整门在工作区写权限下重跑 | 0 | 后端 462 项通过、1 项既有 symlink 跳过；Code Agent、`pip check`、Vue、MCP TypeScript 和 Compose 配置全部通过 |
| 聚焦复审后的最终 `scripts/verify.ps1` | 0 | 增加完整 ASGI response-body admission 合同后，后端 463 项通过、1 项既有 symlink 跳过；其余完整门再次通过 |
| 最终 `python -S ... test_manual_agent_loop -q` | 0 | M1 隔离 10 项通过 |
| `git diff --check` / `git diff --cached --check` | 0 / 0 | 无 whitespace 错误；工作区检查只有既有 LF/CRLF 转换提示 |
| `git commit -m "feat: compose postgres application lifecycle"` | 0 | 13 个实现、配置与测试文件固定为提交 `be2c818` |
| 提交后 Settings/lifecycle/Container/API 与真实 PostgreSQL application 专项 | 0 | 63 项默认路径和 2 项真实 PostgreSQL 专项再次通过 |

### 实现与风险证据

- persistence 默认 `memory`；只有 `AI_AGENT_PERSISTENCE=postgres` 与可解析的 SecretStr DSN 同时存在时才进入异步 Container open。缺失/无效配置不连接数据库、不回退内存，安全输出不含 DSN。
- PostgreSQL Container 绑定 composition 的真实 Run/Event Store、lease-aware Coordinator、Approval/Memory compatibility Store 与 async façade。模块 import/create_app 不打开数据库，FastAPI lifespan 才执行 open/setup/supervisor。
- startup 固定 PostgreSQL composition 后 MCP，最后开启 admission；MCP/认证/seed 失败会清理已打开 composition 并保留原错误。shutdown 先停止并排空 HTTP/command，再按 Coordinator、supervisor、bridge/pool 关闭 composition，最后关闭 MCP。
- admission 使用纯 ASGI middleware，直到完整响应 body 结束才 release；单元测试证明关闭会等待仍在发送的响应。`ApplicationRunCommands` 对 execute/resume/cancel 使用同一 gate。
- memory HTTP 只 await `async_memory_store`；application approval 专项只 await `async_approval_store`。真实数据库证据不是 import、Fake 或 Mock。
- 聚焦复审撤销了把 legacy 静态 auth grant 每次启动写入 PostgreSQL 的方案；该方案会在重启时与一次性 grant 唯一约束冲突。legacy auth 保持进程内兼容，统一持久审批端点仍由 M12 负责。

### 未验证范围

- 旧 `/api/sessions/.../runs` 与 SSE 仍使用 `InMemoryRunService`，没有双写 durable Store；统一 Run、审批、取消和事件 API 属于 M12，不能把本轮描述成 M12 已完成。
- 同步 Approval/Memory compatibility adapter 仍可被显式外部调用且不受 bridge 追踪；默认 async application path 不这样调用。调用方若绕过 Container command/HTTP admission，仍须自行保证停止顺序。
- Python worker 不能硬取消 PostgreSQL statement；running timeout/cancel 后结果可能未知，不得自动重试有副作用写操作。Approval/Memory、Run/Event/checkpoint 与外部副作用仍无跨 pool/系统 exactly-once。
- Windows PostgreSQL host 必须在 event loop 创建前选择 Selector policy；本轮测试模块显式设置该 policy，库代码未修改全局 policy，也未新增生产启动脚本。
- localhost trust/tmpfs 容器不是生产鉴权、TLS、持久卷、备份、高可用、跨主机、容量或硬进程终止证据。没有配置 remote 或执行 push。

### 结论

- M11-T1 第十纵切达到本地 E3，任务计划中的 migration、持久 Store、checkpointer、lease/recovery、连接生命周期、事务边界和默认 opt-in application composition 均有可复现证据，任务更新为 `verified`。
- `KI-023` 关闭；`KI-004`、`KI-014`、`KI-016` 保持 mitigated，分别继续等待统一 durable Run 重启链、Agent ContextAssembler/记忆主链和更高层故障/部署证据。下一原子动作进入 M11-T2 真实 pgvector，不在本轮实现。

## V-20260808-014：M11-T1 application lifecycle 连续性闭环

- 任务：`M11-T1 / verified`；下一任务 `M11-T2 / planned`
- 时间：2026-08-08，Asia/Shanghai
- 验证目标：实现提交 `be2c818` 上的 continuity 工作区
- 模式：纯文档闭环；离线、无 Key、费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、92 个 Markdown 通过；新增 ADR/handoff、M11-T1 verified、M11-T2 planned 与恢复入口一致 |
| `git diff --check` | 0 | 无 whitespace 错误；只有既有 LF/CRLF 转换提示 |
| 定向搜索 `be2c818`、`V-20260808-013/014`、`ADR-0022`、`KI-023`、91/63/2/463 项与 M11-T2 下一动作 | 0 | status、known issue、实施计划、backend standards、ADR、verification 与 handoff 的事实、边界和下一动作相互一致 |
| handoff 恢复命令类名复核 | 0 | 真实 PostgreSQL application 专项固定为 `PostgresFastApiApplicationTest` 与 `PostgresApplicationContainerTest`，没有记录不存在的测试类 |

### 结论

- M11-T1 的 implementation plan、ADR、backend standards、known issue、status、verification 和最新 handoff 已固定第十纵切与任务验收事实；恢复入口指向实现提交 `be2c818`、`V-20260808-013/014` 与 `ADR-0022`。
- 本步骤没有代码或行为变化，因此没有重复运行业务测试或完整门；PostgreSQL 91 项、定向 98 项、最终完整门后端 463 项与 1 项既有 Windows symlink 跳过、M1 10 项，以及提交后 63+2 项继续引用 `V-20260808-013`。
- 当前任务为 `M11-T2 / planned`。下一条原子动作只做真实 pgvector migration 与最小 CRUD/相似度检索纵切；不重做 M11-T1，不安装依赖，不执行在线 Embedding，不进入 M11-T3/M12。

## V-20260809-001：M11-T2 真实 pgvector 文档与检索闭环

- 任务：`M11-T2 / verified`
- 时间：2026-08-09，Asia/Shanghai
- 验证目标：基线 HEAD `41871c4` 上的 M11-T2 工作区；实现提交 `7ebaa16`（`feat: add real pgvector knowledge store`）
- 任务等级：A 类数据库 extension、版本化 schema、事务替换与启动副作用边界；时间盒 2–4 小时
- 模式：默认离线 E3 与本地真实 pgvector E3；没有读取 Key、访问在线模型或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除 Python/Node 依赖；固定 Docker image `pgvector/pgvector:0.8.1-pg17` 仅在用户明确授权后下载，digest `sha256:3e8b3adfd27b5707128f60956f62a793c3c9326ea8cfaf0eab7adccb5d700b21`

### 恢复基线

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 / 0 | 初始工作区干净；HEAD `41871c4`，M11-T1 实现 `be2c818` 与文档锚点存在 |
| `docker exec ai-agent-demo-m11-postgres-1 pg_isready ...` | 0 | M11-T1 本地 PostgreSQL 测试数据库 accepting connections |
| 设置测试 DSN 后 `backend.tests.postgres_store_integration -q` | 0 | 修改前真实 PostgreSQL 91 项通过；不可达数据库负向用例保留预期 pool timeout |
| Settings/lifecycle/Container/API 恢复集 | 0 | 修改前默认路径 63 项通过；仅有既有 Starlette/httpx 弃用警告 |
| 真实 PostgreSQL application 专项 | 0 | 修改前 2 项通过 |
| `python -S ... test_manual_agent_loop -q` | 0 | 禁用 `site-packages` 后 M1 10 项通过 |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、92 个 Markdown 通过 |

### 授权与环境证据

| 操作 | 结果 | 说明 |
| --- | --- | --- |
| 首次申请 `docker pull pgvector/pgvector:0.8.1-pg17` | 未执行 | 当时没有本轮明确下载授权，审批拒绝；没有绕过权限或改用浮动 image |
| 用户明确回复授权后执行固定 image pull | 退出 0 | 下载固定 tag 并记录 digest；没有下载 Python/Node 包 |
| `docker compose -f deploy/compose.integration.yaml up -d --wait --pull never` | 退出 0 | localhost `55433`、trust/tmpfs integration 容器进入 healthy；后续不隐式 pull |
| `docker compose -f deploy/compose.integration.yaml config --quiet` | 退出 0 | 新增 integration Compose 最终配置解析通过，主 `deploy/compose.yaml` 未修改 |

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| 首轮知识/PgVector/RAG/API/Container 聚焦集 | 0 | 53 项通过；迁移、SQL 参数、摘要 seed、启动零写入和 API 行为通过 |
| 补迁移 checksum/history 失败合同后的聚焦集 | 0 | 55 项通过；失败 migration 回滚且不标记版本 |
| 设置 `AI_AGENT_TEST_PGVECTOR_DSN` 后 `backend.tests.pgvector_integration -v` | 0 | 4 项真实 pgvector 通过：extension/schema/HNSW、插入/替换/删除/检索、同摘要不重写、维度错误与旧内容回滚 |
| 提交前首轮完整 backend discover | 1 | 当时 468 项中 `test_unknown_start_commit_keeps_reservation_for_recovery` 单项时序断言失败，预期 claim 1 实得 0；没有修改生产行为 |
| 单独重跑上述 lease 用例 / 串行重跑完整 backend discover | 0 / 0 | lease 用例通过；补完最终测试后完整后端 470 项通过、1 项既有 Windows symlink 跳过 |
| 不落盘 `compile()` / `git diff --check` / `git diff --cached --check` | 0 / 0 / 0 | 修改 Python 语法通过，无 whitespace 错误；两处 EOF 空行在提交前移除，只有既有 LF/CRLF 提示 |
| `git commit -m "feat: add real pgvector knowledge store"` | 0 | 13 个实现、migration、测试、integration Compose 与 ADR 文件固定为提交 `7ebaa16` |
| 提交后知识/PgVector/RAG/API/Container 聚焦集 | 0 | 55 项再次通过；保留一条既有 Starlette/httpx 弃用警告 |
| 提交后真实 pgvector integration | 0 | 4 项再次通过，实际连接 localhost `55433` 的 vector extension 数据库 |
| 提交后完整 M11-T1 PostgreSQL 集 | 0 | 91 项通过，证明独立 knowledge migration 未污染 `app_schema_migrations`；不可达数据库 timeout 为预期负向输出 |
| 提交后 M1 `python -S` 隔离 | 0 | 10 项通过，pgvector/psycopg 路径未进入 M1 标准库边界 |
| 首轮 `scripts/verify.ps1` | 1 | 后端 470 项中 TypeScript MCP E2E 单项在 5 秒内 startup timeout，1 项既有 Windows symlink 跳过；门在后端阶段停止 |
| 单独 `backend.tests.test_mcp_client_e2e -v` | 0 | 4 项在 0.943 秒通过；没有放宽 timeout 或修改 MCP 生产代码 |
| 第二轮 `scripts/verify.ps1` | 0 | 后端 470 项通过、1 项既有 Windows symlink 跳过；Code Agent、`pip check`、Vue、MCP TypeScript 与主 Compose 配置全部通过 |

### 实现与风险证据

- Knowledge schema 使用独立 `backend/knowledge_migrations`、advisory transaction lock 和 checksum history，不强迫 M11-T1 的 vanilla PostgreSQL Run Store安装 vector extension。
- migration 实际创建 `knowledge_documents`、外键级联的 `knowledge_chunks.embedding vector(3)` 与 HNSW `vector_cosine_ops`。查询使用 cosine `<=>`，并用 document ID/chunk index 固定同距排序。
- `add()` 在同一事务 upsert 文档、删除旧切片并插入新向量；真实维度错误证明整个 replacement 回滚，旧 title/source/chunk 仍可检索。`delete()` 通过文档外键级联并返回实际存在性。
- `seed()` 用 server-owned 文档摘要和 transaction advisory lock 跳过同内容数据库重写。FastAPI import、`create_app()` 与 lifespan 不再写 knowledge Store，只有固定 demo seed 端点显式触发；任意文档 API 仍不能覆盖保留 ID。
- Fake Cursor 55 项只作为参数、错误分支和领域映射证据；M11-T2 的完成结论来自独立真实 pgvector 4 项和完整门，不把 import、extension presence 或 Mock 描述成真实检索。

### 未验证范围

- 三维 `_KeywordEmbedding` 是确定性本地测试 fixture，不是 Provider Embedding。批处理、重试、缓存键、维度元数据、在线授权、usage/费用和真实模型质量属于 M11-T3/M11-T7。
- 相同 seed 已证明不重写数据库 row/chunk，但当前适配器在摘要比较前仍计算确定性切片向量；没有把这描述成在线 Embedding 缓存或零 Provider 调用，后续由 M11-T3 固定缓存/批处理所有权。
- 没有固定不少于 50 条查询的 Recall@K、MRR 或回答依据正确率；`KI-006` 只降为 mitigated，最终关闭仍需 M11-T6。
- PgVector adapter 尚未接入默认 `ApplicationContainer` persistence selector。integration Compose 只绑定 localhost 并使用 trust/tmpfs，不是主 Compose、生产鉴权、TLS、持久卷、备份、高可用、容量或灾备证据。
- 首轮完整门 MCP startup timeout 与提交前 lease 时序失败均在独立/串行重跑通过，但仍说明并行进程启动与时间敏感测试存在抖动；本任务没有扩大到修订其 timeout 合同。
- 没有配置 remote、执行 push、读取环境密钥或调用在线/付费模型。

### 结论

- M11-T2 达到本地 E3：真实 pgvector migration、固定维度/index、事务 CRUD、显式幂等 seed 和相似度检索均可从提交 `7ebaa16` 复现，任务更新为 `verified`。
- `KI-006` 更新为 mitigated；M11 继续 `in_progress`。下一原子任务是 M11-T3 的确定性离线 Embedding/批处理/维度元数据最小纵切，不在本轮实现在线调用或 M12/M13。

## V-20260809-002：M11-T2 pgvector 连续性闭环

- 任务：`M11-T2 / verified`；下一任务 `M11-T3 / planned`
- 时间：2026-08-09，Asia/Shanghai
- 验证目标：实现提交 `7ebaa16` 上的 continuity 工作区
- 模式：纯文档闭环；离线、无 Key、费用 0

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、94 个 Markdown 通过；新增 ADR/handoff、M11-T2 verified、M11-T3 planned 与恢复入口一致 |
| `git diff --check` | 0 | 无 whitespace 错误；只有既有 LF/CRLF 转换提示 |
| 定向复核 `7ebaa16`、`V-20260809-001/002`、`ADR-0023`、55/4/91/470 项、`KI-006` 与 M11-T3 下一动作 | 0 | status、known issue、实施计划、backend standards、ADR、verification 与 handoff 的事实、边界和下一动作相互一致 |

### 结论

- M11-T2 的 implementation plan、ADR、backend standards、known issue、status、verification 和最新 handoff 已固定真实 pgvector migration/CRUD/seed 证据与未验证范围；恢复入口指向实现提交 `7ebaa16`。
- 本步骤没有代码或行为变化，因此没有重复运行业务测试或完整门；提交后知识/API 55 项、真实 pgvector 4 项、M11-T1 PostgreSQL 91 项、M1 10 项和最终完整离线门继续引用 `V-20260809-001`。
- 当前任务为 `M11-T3 / planned`。下一条原子动作只做确定性离线 Embedding、批次与维度元数据最小纵切；不得重做 M11-T2、读取 Key、执行在线 Embedding 或扩大到 M12/M13。

## V-20260809-003：M11-T3 确定性离线 Embedding 与批次纵切

- 任务：`M11-T3 / in_progress`
- 时间：2026-08-09，Asia/Shanghai
- 验证目标：基线 HEAD `9b77bfd` 上的 M11-T3 第一纵切工作区
- 任务等级：B 类普通离线 Adapter 与确定性批次功能；时间盒 30–90 分钟
- 模式：默认离线 E3；没有读取 Key、访问在线模型或产生付费调用，费用 0
- 依赖事实：没有新增、安装、升级或删除 Python/Node 依赖；没有修改 Settings、数据库 schema、主 Compose 或前后端接口

### 恢复基线

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `git status --short` / `git log -6 --oneline` | 0 / 0 | 初始工作区干净；HEAD `9b77bfd`，M11-T2 实现 `7ebaa16` 与文档锚点存在 |
| 首次按推测文件名读取 ADR-0005 | 1 | 文件名猜测错误；用 `rg --files` 定位实际 `ADR-0005-explicit-settings-without-dotenv.md` 后读取成功，不是仓库漂移 |
| `docker compose -f deploy/compose.integration.yaml up -d --wait --pull never` | 0 | 只使用本地缓存 image，pgvector integration 容器 healthy，没有下载 |
| 修改前真实 pgvector integration | 0 | 4 项通过 |
| 修改前知识/PgVector/RAG/API/Container 集 | 0 | 55 项通过；仅有既有 Starlette/httpx 弃用警告 |
| 修改前 M11-T1 PostgreSQL 完整集 | 0 | 91 项通过；不可达数据库 pool timeout 为预期负向输出 |
| `python -S ... test_manual_agent_loop -q` | 0 | M1 隔离 10 项通过 |
| `scripts/check-continuity.ps1` | 0 | 52 个稳定任务、94 个 Markdown 通过 |

### 实际命令与结果

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| 首轮 `test_embeddings + test_pgvector -v` | 0 | 22 项通过；批次拆分/顺序、空批/空文本、部分返回、维度/metadata 漂移、非法值和 PgVector 数据库前失败均执行 |
| 聚焦自审 | 0 | 发现非整数 dimensions/batch size 会延迟到 Python 容器操作、绕过 Batcher 的非数字向量可能暴露转换文本；补构造期整数校验、DEL 控制字符拒绝和稳定数值错误 |
| 最终 Embedding/PgVector/RAG/API/Container 定向集 | 0 | 67 项通过；本纵切新增 12 个关键测试方法或等价覆盖，既有 Starlette/httpx 弃用警告不变 |
| 设置 `AI_AGENT_TEST_PGVECTOR_DSN` 后真实 pgvector integration | 0 | 4 项通过；新 metadata/batch fixture 实际完成 schema、CRUD、查询、幂等 seed 和回滚路径 |
| 最终 M1 `python -S` 隔离 | 0 | 10 项通过，knowledge Embedding 模块未进入 M1 标准库 Loop 导入路径 |

### 实现与风险证据

- `EmbeddingMetadata` 冻结 provider/model/revision/dimensions，拒绝空值、控制字符、异常长度和非正整数维度；公开错误只有稳定 code，不包含输入文本。
- `BatchingEmbeddingModel` 统一单条/批次路径，先规范化并完整校验输入，再按固定 batch size 调用 Provider。空批不调用 Provider，返回数量不匹配时不暴露已完成前缀。
- 确定性离线 Provider 使用标准库 SHA-256 token hash 和 L2 归一化；相同规范化文本跨实例得到同一固定维度向量。它不是在线模型或语义质量证据。
- `PgVectorKnowledgeBase` 对所有文档切片执行一次 Model batch；Model 再按 Provider 限额拆分。metadata、数量、维度、非数字或非有限值在 connection factory 前失败，数据库事务不包住 Embedding。
- 真实 pgvector 4 项使用更新后的 metadata/batch 合同通过，因此当前结论不是 import 或 Fake-only 证据。

### 未验证范围与全量门说明

- 尚未实现缓存 Store/命中、版本化 key 代码、暂时性 Provider 错误重试、显式在线 SDK Adapter、Embedding Settings 或 Provider usage/cost；这些继续属于 M11-T3。
- 没有读取 `OPENAI_API_KEY`、构造在线 Embedding Client 或执行网络。ADR-0024 只固定未来在线 composition 所有权，不能描述成在线兼容证据。
- SHA-256 token-hash 三维向量不证明语义质量、Provider tokenizer、Recall@K、MRR 或回答依据正确率；`KI-006` 保持 mitigated，M11-T6 仍需固定评测集。
- 本纵切没有依赖、锁文件、构建配置、数据库 migration、Settings、跨前后端接口或多个里程碑共享核心领域契约变化；67 项受影响回归、真实 pgvector 4 项和 M1 10 项覆盖修改面，因此没有重复运行 `scripts/verify.ps1`、Vue 或 MCP 构建。
- integration Compose 继续是 localhost trust/tmpfs 测试基础设施，不是生产部署证据。没有配置 remote 或执行 push。

### 结论

- M11-T3 第一纵切达到本地 E3：确定性离线 Provider、冻结维度元数据、通用批次拆分和 PgVector 批次调用链可从基线 `9b77bfd` 上的工作区复现。
- M11-T3 更新为 `in_progress`，不能标记 `verified`。下一原子动作只实现版本化内存缓存与按批次暂时性错误重试 wrapper，覆盖缓存命中、失败不缓存、可重试/不可重试和耗尽；在线 SDK/真实调用继续后置。
