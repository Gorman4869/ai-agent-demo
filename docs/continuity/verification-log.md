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
