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
