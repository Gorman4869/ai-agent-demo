# M12-T5 交接：前端单元测试与真实 Chromium 恢复

- 日期：2026-08-28，Asia/Shanghai
- 当前任务：`M12-T5 / verified`
- 下一任务：`M12-T6 / planned`
- 验证基线：`8610f06`
- 验证记录：`V-20260828-012`
- 关联决策：`ADR-0029`、`ADR-0030`、`ADR-0031`、`ADR-0032`
- 任务等级：A/C 类（capability、恢复状态、浏览器与依赖）
- 在线模型/付费调用：未执行；npm/Playwright 下载和 advisory 查询已获授权，费用 0
- 远程仓库：未配置，未 push

## 本次结果

前端锁定 Vitest `4.1.11`、Vue Test Utils `2.5.0`、happy-dom `20.11.12` 和
Playwright Test `1.62.1`。12 项单测覆盖 SSE 分帧/CRLF、多帧、无效 JSON、ID
不一致、Abort、无终态、usage 校验、重复/缺口 sequence、有界重连、服务端取消、
审批绑定和刷新 cursor 恢复。

真实 Chromium 两项 E2E 启动本地 FastAPI 与 Vite：普通 Mock Run 的首次 SSE 请求被
故意断开后从 Store 续传，完成后刷新仍恢复同一 Run/答案；审批 Run 在
`waiting_approval` 时刷新仍恢复同一 approval，浏览器只提交 decision 和路径 approval
ID，拒绝后进入安全失败终态。审批使用独立测试装配中的真实
`ApprovalLangGraphRuntime` 与合成高风险工具，不改变生产匿名角色或工具定义。

## 修改文件

- `frontend/package.json`、`frontend/package-lock.json`
- `frontend/vitest.config.ts`、`frontend/playwright.config.ts`
- `frontend/tsconfig.node.json`、`frontend/vite.config.ts`
- `frontend/tests/unit/agentApi.spec.ts`
- `frontend/tests/unit/useAgentDesk.spec.ts`
- `frontend/tests/e2e/durable-run.spec.ts`
- `backend/tests/m12_frontend_e2e_server.py`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- 本 handoff

## 验证与失败尝试

- `npm.cmd run test:unit`：2 files / 12 tests 通过。
- `npm.cmd run test:e2e`：Chromium 2 项通过。
- `npm.cmd run build`：Vue TypeScript 与 Vite production build 通过，19 modules。
- 审批/durable 定向后端 30 项通过。
- `powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify.ps1`：后端 643 项
  通过、1 项既有 Windows symlink 能力跳过；其余全量门全部通过。
- 沙箱内 Vitest/Chromium 的 `spawn EPERM` 经已授权沙箱外重跑通过；这不是 Node 版本
  失败。当前 Node `22.16.0` 可运行全部测试，无需切 nvm。
- Windows `cmd.exe` 不接受 `./.venv/...` webServer 命令，现由 config 解析带引号绝对
  Python 路径。端口 8000 位于本机保留区间，E2E 使用 18080；默认 dev proxy 仍为
  8000，测试子进程通过 `AI_AGENT_DEV_API_TARGET` 覆盖。
- 默认 manual/匿名生产策略正确地把 `publish_report` 作为角色拒绝并完成，不会产生
  approval pause；测试装配只为浏览器审批行为提供真实 LangGraph interrupt/resume。
- `npm audit --json` 保留两个既有 transitive advisory；没有运行 `npm audit fix`，见
  `KI-027`。

## 未验证范围

- 未验证生产 OIDC/HttpOnly/CSP、Nginx、跨浏览器矩阵、浏览器崩溃、真实 PostgreSQL
  浏览器链、后端硬进程重启或在线模型。
- M12-T5 不决定 legacy Research API 与旧 POST SSE 的移除时间，也不把测试 fixture
  当成生产匿名审批权限证据。
- npm 两项既有公告尚未升级；统一分层 CI 仍由 M13-T3 处理。

## 下一条原子动作

开始 M12-T6 前只读检查 legacy Research、旧 SSE、新 durable API 的代码调用和文档
引用；形成保留/替代 ADR 与迁移记录，再汇总 `docs/stages/12-realtime-agent-ui.md` 的
跟练、自测、速查和费曼材料。不得提前删除兼容 API，也不得进入 M13/Nginx/生产认证。
