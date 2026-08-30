# M13-T3 交接：分层验证与 CI 本地 code complete

- 日期：2026-08-30，Asia/Shanghai
- 当前任务：`M13-T3 / code_complete`
- 验证基线：`57f0c8b`
- 验证记录：`V-20260830-001`
- 关联决策：`ADR-0036`
- 任务等级：A 类公共验证/CI 合同 + C 类本地数据库、浏览器和远程 runner
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，workflow 未在 GitHub runner 执行，未 push

## 本次结果

`scripts/verify.ps1` 现在固定 offline、MCP、PostgreSQL、frontend、E2E、Docker 和 online 七层。
默认只展开 `offline + mcp + frontend`；`integration` 是 PostgreSQL 别名，`all` 展开全部。
显式 required layer 缺少前置条件时失败，online 缺少本次授权时只明确 skip。

每一层最终都显示 `PASSED/FAILED/SKIPPED`。首个 required failure 会停止后续命令、输出完整
汇总并退出 1；有失败或 skip 时不会落到全部通过文案。新增 4 项入口测试锁定缺 DSN 失败、
无授权 skip、独立 online 拒绝和 CI 无 secret policy。

`.github/workflows/verification.yml` 把七层拆成只读 job：Windows 执行 offline/MCP/frontend/E2E，
Ubuntu service 执行 PostgreSQL，Ubuntu Docker 执行 Compose config，online-policy 只验证 skip。
workflow 不引用仓库 secret、不使用 `pull_request_target`、不传在线授权。

## 修改文件

- `scripts/verify.ps1`
- `.github/workflows/verification.yml`
- `backend/tests/test_verification_entrypoint.py`
- `docs/continuity/decisions/ADR-0036-layered-verification-and-ci.md`
- `docs/m13-verification-ci.md`
- `BACKEND_CODING_STANDARDS.md`
- `README.md`
- `docs/stages/07-system-design-capstone.md`
- `docs/stages/13-production-engineering.md`
- `docs/implementation-plan.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/status.md`
- 本 handoff

没有修改 `docs/progress.md`、业务 Runtime/Store/API/前端源码、依赖/锁文件、migration、Dockerfile
或 Compose 内容；没有读取用户 `.env`、Key、Token 或生产 DSN。

## 本地验证

- 恢复基线：33 项通过。
- 入口 policy：4 项通过。
- offline：670 项通过，1 项既有 Windows symlink 能力跳过；代码 Agent Demo 和 `pip check`
  通过。
- 默认组合门：顺序执行 offline、MCP、frontend，最终汇总 3 passed、4 skipped、0 failed。
- MCP：TypeScript build 与本地 STDIO 11 项通过。
- PostgreSQL/pgvector：localhost integration trust 测试库共 120 项通过。
- frontend：Vitest 12 项与 production build 通过。
- E2E：真实本地 FastAPI + Vite + Chromium 2 项通过。
- Docker：主/integration 两份 Compose `config --quiet` 通过。
- online：无本次授权时显式 skip，未执行网络。
- workflow：PowerShell 语法、YAML 解析、七 job/只读权限/无 secret policy 静态检查通过。

## 失败尝试与边界

- MCP 首轮受控沙箱因 build 文件写入拒绝失败；frontend 首轮受控沙箱因 `spawn EPERM` 失败。
  两次脚本都正确汇总失败且无成功文案，相同 profile 在沙箱外通过。
- 两次 PostgreSQL 长命令的终端桥只返回部分输出；最终用持续 session polling 明确取得
  exit 0、120 项和汇总，不把部分输出计入成功。
- Node `22.16.0` 与 npm `10.9.2` 通过当前前端/MCP 门，不需要用户切换 nvm。
- Docker profile 只做 config，不代表镜像、容器健康、migration、Nginx SSE 或生产部署。
- workflow 文件尚未在 GitHub-hosted runner 运行；本地通过不能冒充远程 CI，所以 M13-T3 为
  `code_complete`，`KI-008` 保持 mitigated。

## 下一条原子动作

不要进入依赖 M13-T3 的 M13-T4。先由用户提供远程仓库地址并明确授权配置 remote/push，随后
实际运行 `.github/workflows/verification.yml` 的七个 job。记录 URL/commit、每个 job 结果、
失败/skip 和未验证范围；只有全部 required job 成功且 online-policy 明确 skip 后，才能追加新
verification、把 M13-T3 改为 `verified` 并关闭 `KI-008`。

如果用户不授权远程 Git，本地提交后保持当前 code-complete 状态，不寻找其他仓库、不创建
临时公网仓库、不注入 Key，也不提前执行 M13-T4。

## 交接时工作区

本 handoff 创建时，以上 M13-T3 文件均为待提交改动，基线 HEAD 为 `57f0c8b`；结束前应重跑
连续性检查、`git diff --check`、最终范围审计，并只提交本任务文件。提交后的新 HEAD 由下一条
verification 或 handoff 记录。
