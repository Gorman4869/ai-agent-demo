# M13 分层验证与 CI

本页说明 M13-T3 的工程入口。它不代替 `docs/continuity/status.md` 的动态状态，也不表示
M13-T4 的镜像、健康检查或 Nginx 已完成。

## Profile 对照

| Profile | 实际层 | 前置条件 | 缺少前置条件时 |
| --- | --- | --- | --- |
| 默认或 `default` | offline、MCP、frontend | 项目 `.venv`、两个现有 `node_modules` | required layer 失败 |
| `offline` | 后端 discovery、代码 Agent Demo、`pip check` | 项目 `.venv`、Node、MCP 依赖 | 失败 |
| `mcp` | TypeScript build、本地 STDIO 集成 | `.venv`、Node、MCP 依赖 | 失败 |
| `postgresql` / `integration` | PostgreSQL Store、pgvector integration | 两个测试 DSN | 失败，不静默 skip |
| `frontend` | Vitest、Vue build | Node、前端依赖 | 失败 |
| `e2e` | FastAPI + Vite + Chromium | `.venv`、Node、已安装 Chromium | 失败 |
| `docker` | 两份 Compose `config --quiet` | Docker CLI + Compose | 失败 |
| `online` | 既有 M8 在线 smoke | 本次授权、在线配置与 Key | 未授权时明确 skip |
| `all` | 七层 | 上述全部 required 前置条件 | required layer 失败；online 可明确 skip |

默认入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify.ps1
```

单层入口示例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify.ps1 -Profile mcp
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify.ps1 -Profile integration
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify.ps1 -Profile e2e
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify.ps1 -Profile docker
```

在线 profile 默认只产生显式跳过。只有用户对本次调用重新授权、环境变量由操作者安全注入且
已确认费用边界后，才可使用 `-AuthorizedOnline`。普通 CI 永远不传这个开关。

## 汇总和退出码

七层始终出现在最终表中：

- `PASSED`：该层所有 required step 都实际退出 0；
- `FAILED`：命令、工具或前置配置失败；脚本最终退出 1；
- `SKIPPED`：未被 profile 选择、被显式 `-SkipCompose` 关闭，或 online 缺少本次授权。

首个 required layer 失败后，后续已选择层显示“未运行”，不会继续消耗资源。只要存在失败，
脚本就不会输出全部通过；只要存在跳过，最终只报告计数，不把局部门禁描述成完整通过。

## CI job

`.github/workflows/verification.yml` 在 push、pull request 和手动触发时定义七个 job：

- Windows：offline、MCP、frontend、E2E；
- Ubuntu + pgvector service：PostgreSQL；
- Ubuntu Docker：两份 Compose 配置；
- Ubuntu online policy：只验证未授权得到显式 skip。

workflow 权限只有 `contents: read`，不引用仓库 secret。offline 的完整 backend discovery 本来
就包含 TypeScript MCP E2E，因此其干净 runner 也先按 MCP lockfile 安装依赖；其余 job 同样只
安装自己需要的现有依赖。本地 `verify.ps1` 从不安装或升级依赖。

## 证据边界

- Docker profile 只证明 YAML 可以展开，不证明镜像可构建、容器 healthy、migration 可用或
  Nginx SSE 实时；这些属于 M13-T4。
- 本地 profile 通过不等于 GitHub Actions 已运行。远程仓库尚未配置时，workflow 只能记为
  code-complete，不能关闭 `KI-008`。
- online policy skip 不是 Provider E4；真实在线结果仍由独立 verification 记录费用、usage 和
  本次授权范围。
