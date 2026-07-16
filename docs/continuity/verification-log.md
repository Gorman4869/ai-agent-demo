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
