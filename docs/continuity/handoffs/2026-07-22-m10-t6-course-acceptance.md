# M10-T6 交接：课程汇总与里程碑验收

- 日期：2026-07-22，Asia/Shanghai
- 完成任务：`M10-T6`
- 完成状态：`verified`
- 里程碑状态：`M10 / verified`
- 下一任务：`M11-T1 / planned`
- 验证基线 HEAD：`07741db`
- M10-T5 实现提交：`1e332f3`
- M10-T6 课程提交：待本地提交固定
- 验证记录：`V-20260722-007`
- 分支：`main`
- 任务等级：B 类课程文档整合与里程碑完整门，时间盒 60–90 分钟
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 扩展 Stage 10：补齐 Run、重规划和审批恢复三张状态图，四次里程碑跟练，故障定位矩阵，固定排错顺序，以及概念/实操/场景题与评分红线。
2. 新增 `docs/m10-langgraph-cheat-sheet.md`，集中记录 durable 状态、重规划五问、审批绑定链、单/多 Agent 选择、稳定错误码、验收命令和证据红线。
3. 更新 30 项大纲映射和实施计划，明确 M10 只验收同进程新 Runtime 共享 saver 恢复；PostgreSQL 真进程重启、持久 ToolExecution、lease 和恢复扫描仍由 M11 承接。
4. 完成 M10 聚焦 58 项、确定性多 Agent Demo 和完整离线门；课程、自动化与构建证据共同满足 M10 工程里程碑验收。
5. 先登记再关闭 `KI-021`：修正 status 的旧提交/旧缺口措辞；旧 M10-T5 handoff 作为不可变历史不回写，本交接说明其待提交描述已由后续锚点提交 `07741db` 固定。

## 本次修改文件

- `docs/stages/10-durable-langgraph.md`
- `docs/m10-langgraph-cheat-sheet.md`
- `docs/syllabus-map.md`
- `docs/implementation-plan.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-07-22-m10-t6-course-acceptance.md`

没有业务代码、测试代码、依赖、锁文件、公共协议、默认 Container、HTTP/SSE 或前端行为变化。

## 实际验证

- 启动恢复：M10-T5 故障专项 10 项、禁用 `site-packages` 的 M1 手写 Loop 7 项、连续性 52/70 通过；代码与 `1e332f3` 一致。
- M10 聚焦：checkpoint、审批 resume、重规划、恢复故障、多 Agent 和对照评测共 58 项通过，无 ResourceWarning。
- 固定评测：3 例中 manager-as-tools 与 single Agent 质量均为 1.0、失败率均为 0；manager 27 requests/324 fixture Token/412.399 ms/复杂度 12，single 9/108/138.548 ms/复杂度 3，继续选择 single Agent。
- 完整离线门：首次沙箱运行在后端 354 项通过、1 项跳过，受控代码 Agent 和依赖检查通过后，因 Vue `tsconfig.app.tsbuildinfo` 写入 `EPERM` 退出 1；相同脚本经批准工作区构建权限后退出 0，Vue、MCP TypeScript 和 Compose 配置也全部通过。
- 课程检查：相对链接目标存在，`git diff --check` 无 whitespace 错误；最终连续性为 52 个稳定任务、72 个 Markdown。
- 所有证据均为本地离线 E2/E3；没有网络、密钥、Provider 或费用。

## 警告与未验证范围

- 后端全量输出有一条既有 `StarletteDeprecationWarning`；Windows 环境有 1 项真实 symlink 能力测试跳过。
- `InMemorySaver` 只证明同一进程内共享对象恢复，不证明操作系统进程重启。M10 的 at-most-once/fail-closed 证据也不等于跨崩溃 exactly-once。
- 未验证 PostgreSQL migration、PostgreSQL Store/checkpointer、持久 ToolExecution、lease、恢复扫描、多进程事务与默认主链迁移；这些是 M11-T1 及后续任务范围。
- fixture Token、延迟与质量不是 Provider tokenizer、账单、线上模型质量、真实费用或生产容量证据。
- 学习者个人尚未完成 M10 题库、速查练习和费曼复述；个人进度只在 `docs/progress.md` 勾选。

## 未提交改动

当前只有上列 M10-T6 课程、映射和连续性文档改动；没有任务外改动，没有安装依赖，没有远程 Git 操作。课程提交创建后，应在下一条 verification/handoff 锚定新 HEAD，不回写旧 handoff 的历史结论。

## 下一条原子动作

开始 `M11-T1` 前，只读审阅现有 Run/Event/Approval/Memory Store Protocol、数据库连接与 migration 目录、ADR-0004/0006/0011/0012 以及 Docker 可用性；先固定内存/PostgreSQL 共用契约和最小“写入 checkpoint -> 新进程读取并恢复”纵切，再判断是否需要用户授权启动本地容器或安装依赖。不要提前进入 M11-T2 pgvector、Embedding、记忆或 RAG。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_checkpointing backend.tests.test_langgraph_approval_resume backend.tests.test_langgraph_replanning backend.tests.test_langgraph_recovery_faults backend.tests.test_multi_agent backend.tests.test_workflow_comparison_eval -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 M10 聚焦 58 项、M1 7 项通过且无 ResourceWarning，连续性保持 52 个稳定任务、72 个 Markdown。若一致，不要重做 M10；只进入 M11-T1 只读契约与环境审计。未经用户新的明确授权，不安装依赖、不读取 Key、不执行在线/付费调用、不配置或推送远程 Git、不扩大范围。
