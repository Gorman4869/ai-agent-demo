# M13-T7 交接：生产工程课程与里程碑验收

- 日期：2026-09-01，Asia/Shanghai
- 当前任务：`M13-T7 / verified`
- 下一任务：`M14-T1 / planned`
- 验证基线：`68ea1bb`
- 验证记录：`V-20260901-003`
- 关联决策：`ADR-0034` 至 `ADR-0039`（均未改写）
- 任务等级：B 类里程碑学习交付
- 在线模型/付费调用：未执行，费用 0
- Docker/数据库：未执行新有状态演练，复用既有不可变证据
- 远程 Git：未 push

## 本次结果

Stage 13 已把 M13-T1 至 M13-T6 整理为七次项目跟练：从 Run ID 观测、六道重试门、七层
验证、单实例部署、代码进程安全、固定负载/故障演练，到一次未知故障综合验收。每次包含真实
入口、精确 PowerShell 命令、前端工作映射、产出、通关和常见错误。

新增事故响应手册，固定止损、定界、定位、仲裁、恢复、验证、复盘七步，以及 Provider、MCP、
副作用结果未知、PostgreSQL、Nginx SSE、CI、代码进程和成本故障卡。恢复必须同时具备新 Run、
旧 Run、健康依赖、持久终态和精确清理五类证据。

新增一页观测速查表；课程主章同时包含 20% 关键知识、五级能力路线、100 分考核与红线、费曼
复述、30 项映射和最终验收清单。`build-learning-plan` 模板影响的是教学结构，没有修改业务实现
或学习者 `docs/progress.md`。

## 修改文件

- `docs/stages/13-production-engineering.md`
- `docs/m13-incident-handbook.md`
- `docs/m13-observability-cheat-sheet.md`
- `docs/syllabus-map.md`
- `docs/implementation-plan.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/status.md`
- 本 handoff

业务 Python/Vue/TypeScript、测试、依赖、锁文件、构建配置、accepted ADR、known issues 和
`docs/progress.md` 均未修改。

## 验证与失败尝试

- 课程产物后的连续性检查通过：52 个稳定任务、161 个 Markdown 文件。
- 默认门沙箱内首轮因用户 Temp ACL 被拒绝，backend 703 项出现 54 个环境错误和 2 个派生 MCP
  失败；后续层按合同停止。该结果不是代码失败或成功证据，但保留在 verification。
- 同一门沙箱外首次排除 ACL 后，只余 TypeScript MCP E2E 一项 `startup_timeout`；定向 1 项随后
  通过，未改代码/timeout。完整门再次复跑退出 0。
- 最终 offline 后端 703 项通过、1 项既有 Windows symlink 条件跳过；Code Agent Demo、依赖、
  MCP build/STDIO 11 项、Vue 12 项和 production build 均通过。
- 没有切换 Node 或 nvm；没有读取 Key、运行 online、Docker、PostgreSQL profile 或 push。
- 自审修正一处不存在的观测模块路径；Markdown 链接、实际入口、连续性和 diff check 通过。

## 证据和残余边界

- 本轮课程回归是离线 E1–E3；M13-T4 的真实部署与 M13-T6 的三轮故障演练继续分别引用
  `V-20260831-003` 和 `V-20260901-001`，没有被教程命令伪装为新执行。
- `KI-015/KI-016/KI-017/KI-018/KI-027` 无新关闭证据，保持原状态。没有生产 TLS、备份、HA、
  公网流量、在线 Provider 容量、逐调用硬成本门或同步线程/远端请求硬撤销证明。
- M13 工程达到 `verified`，不表示学习者已完成题库、实操或费曼；个人通关仍只写
  `docs/progress.md`。

## 下一条原子动作

开始 M14-T1 前按 AGENTS 顺序恢复，读取 `docs/stages/14-advanced-capstone.md`、实施计划 M14-T1、
现有 browser planner/安全测试和关联 ADR。先冻结受控测试站点、DOM/截图 observation、导航/
点击/输入动作、超时/弹窗/新窗口/下载的 fail-closed 合同；保留离线 planner 对照，不使用真实
个人登录态，不提前进入 M14-T2 的 SSRF、DNS/重定向复核或完整审批实现。
