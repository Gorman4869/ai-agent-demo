# M12-T6 交接：兼容层决策与 M12 里程碑验收

- 日期：2026-08-28，Asia/Shanghai
- 当前任务：`M12-T6 / verified`
- 下一任务：`M13-T1 / planned`（按用户当前工程优先级）
- 验证基线：`0f81b0a`
- 验证记录：`V-20260828-013`
- 关联决策：`ADR-0029`–`ADR-0033`
- 任务等级：A 类公共 API 迁移决策 + B 类里程碑课程整合
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本次结果

Vue 的 legacy `POST .../runs/stream` + 终态后 `/api/research` 覆盖答案/引用双链被标记为
`superseded`。该状态只适用于前端主流程；legacy sessions/runs/read/POST SSE 和独立
Research API 仍保留现有响应、Store 隔离与合同测试，不代理、不双写、不共享 Run ID。

新调用方只采用 `/api/durable/*`。迁移记录固定 `202`、幂等键、匿名 capability、非终态、
排他 sequence cursor、snapshot、取消、审批和同 Run evidence 的差异。未来删除兼容端点前，
必须另有消费者清单、通知/版本策略、迁移回归和取代 `ADR-0033` 的新决策。

Stage 12 已汇总六次跟练、三张图、排错、自测、评分红线、速查、费曼、最终验收和 30 项
大纲映射。`build-learning-plan` 模板用于保证项目步骤、工作映射和可观察通关标准，未改动
学习者个人 `docs/progress.md`。

## 修改文件

- `docs/continuity/decisions/ADR-0033-legacy-run-api-compatibility.md`
- `docs/m12-api-migration.md`
- `docs/stages/12-realtime-agent-ui.md`
- `docs/m12-realtime-ui-cheat-sheet.md`
- `docs/syllabus-map.md`
- `docs/项目编码规约 v1.0.md`
- `docs/implementation-plan.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- 本 handoff

业务后端、Vue 运行代码、测试、依赖和锁文件均未修改；所有旧 HTTP 路由仍存在。

## 验证与失败尝试

- 新旧 API/SSE/projection 定向 46 项通过。
- Vue 单元测试 2 files / 12 tests 通过，production build 转换 19 modules。
- 真实 Chromium E2E 2 项通过：首次 SSE 断开 + 刷新恢复，以及 waiting approval 刷新后
  同 Run 拒绝。
- 统一全量离线门通过：后端 643 项通过、1 项既有 Windows symlink 能力跳过；受控 Code
  Agent、Python 依赖、Vue、MCP TypeScript 和 Compose 配置均通过。
- Vue 单测/构建在沙箱内首次分别命中 `spawn EPERM` 和 `TS5033/EPERM`；相同命令经授权在
  沙箱外通过。Node 22.16.0 兼容，无需切 nvm。
- 补丁工具拒绝删除并同名重建 Stage 文件，改用原文件分段 patch；自审发现并修正两个不
  存在的代码入口，没有据此改业务实现。
- `frontend/src` 无 `/api/research`、`/runs/stream`、legacy sessions/runs 引用；连续性、
  Markdown 链接和 `git diff --check` 通过。

## 连续性变更

- `KI-004`、`KI-005` closed：跨进程持久恢复、统一 durable Run、同 Run evidence 和浏览器
  实时恢复均已有 M10–M12 证据；剩余生产故障分别由 KI-015/KI-016 承接。
- `KI-008` 继续 mitigated，等待 M13-T3 把现有 offline/MCP/PostgreSQL/frontend/E2E/
  Docker/online opt-in 汇总为分层 CI。
- `KI-027` 保持 open；没有运行 `npm audit fix` 或升级依赖。
- `KI-028` 登记并关闭：`status.md` 底部旧 M11-T7 恢复入口已改为本 handoff。
- M12 更新为 `verified`；M11-T8 学习交付仍未启动，不因用户当前工程优先级被伪装完成。

## 未验证范围

- 未验证仓库外 legacy 消费者、HTTP deprecation header、调用遥测或真实删除/回滚演练。
- 本轮未重跑 PostgreSQL integration；M12 数据库重启证据仍为 `V-20260828-008/009/010`。
- 未验证 OIDC/HttpOnly、capability 撤销、CSP、Nginx、多实例通知、跨浏览器、生产容量、
  usage/cost 账本或在线模型。
- 真实浏览器审批仍使用测试 Runtime/合成工具，不证明生产匿名用户具有高风险工具权限。

## 下一条原子动作

开始 M13-T1 前按 AGENTS 顺序重新恢复，并审计现有 `RunObserver`、usage event/projection、
Settings、Store/migration 与前端成本展示。先形成最小 Trace/Metrics sink 和持久 usage/cost
账本边界，不把未知 cost 写成 0，不读取 Key、不执行在线 Provider、不升级 npm 依赖，也不
提前进入 M13-T2 重试或 M13-T4 部署。
