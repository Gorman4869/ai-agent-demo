# M8-T7 交接：跟练材料与离线里程碑验收

- 日期：2026-07-17，Asia/Shanghai
- 完成任务：`M8-T7`
- 完成状态：`verified`
- M8 里程碑状态：离线 `code_complete`；真实在线 E4 未授权，不能 `accepted`
- 下一任务：`M9-T1 / planned`
- 验证基线 HEAD：`6e86e1e`
- M8-T7 文档提交：待本轮本地 commit 固定
- 验证记录：`V-20260717-003`
- 分支：`main`
- 任务等级：`B`，纯文档里程碑验收，时间盒 60-90 分钟
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 把 M8-T1 至 M8-T6 的稳定产物串成四次递进跟练；每次都有时间、目标、命令、产物、工作映射、通关标准和常见错误。
2. 修正阶段文档中不存在的 `test_langchain_comparison`，改为实际存在并已验证的 `test_runtime_comparison + test_langchain_agent_lab + test_framework_runtimes`。
3. 增加 Provider 故障定位演练，固定 Settings、Coordinator、Runtime、Store/Event、重试/副作用的排查顺序。
4. 把默认离线分支与经单次授权的 E4 分支拆开，写明 M8 online smoke 的完整门、低预算、费率参数和证据边界。
5. 增加 5 道概念题、4 道实操题、4 道工作场景题、100 分评分标准和安全红线。
6. 新增独立 `docs/m8-runtime-cheat-sheet.md`，压缩五层职责、门禁、主链、框架取舍、事件白名单、预算、稳定错误、取消和命令。
7. 增加 M8 费曼任务、可观察最终验收清单，以及对 30 项大纲中 01、03、05、06、09、10、11、23、24 的证据映射与后续承接点。
8. 移除阶段文档中的动态测试计数，实际通过数只记录在 verification，避免教程随回归增长而漂移。

## 课程边界

- M8-T7 `verified` 表示课程产物、命令和离线里程碑门已验收，不表示学习者已经完成个人自测；个人勾选仍只写 `docs/progress.md`。
- M8-T4/M8-T6 仍为 `code_complete`。Fake Runner、确定性 ChatModel 和 Store/Coordinator 集成最高是 E2/E3，不是 Provider E4。
- M8 整体只达到离线 `code_complete`。没有用户新的单次授权，不能读取 Key、执行真实模型或把里程碑标为 `accepted`。
- operator-supplied 费用估算不是 Provider 账单；逐调用硬成本门和持久账本仍由 `KI-018` / M13 承接。

## 本次修改文件

- `docs/stages/08-real-model-runtimes.md`
- `docs/m8-runtime-cheat-sheet.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/handoffs/2026-07-17-m8-t7-course-acceptance.md`

## 实际验证

- handoff 恢复：12 项 online smoke 测试和 102 项 Settings/Container/Runtime/SDK/Coordinator 定向回归通过；未授权在线脚本保持 fail closed。
- 教程命令：Provider 稳定错误映射 1 项通过；三 Runtime、LangChain 和框架对照组合 12 项通过。
- 全量离线门：后端 252 项通过、1 项既有 Windows symlink 跳过；受控 Code-Agent Demo、`pip check`、Vue 18 模块生产构建、MCP TypeScript 构建和 Compose 配置通过。
- 文档检查：M8-T7 八个必需章节存在；TBD/TODO/PLACEHOLDER、待补/待定和旧错误模块名均无匹配。
- 连续性检查：52 个稳定任务、52 个 Markdown 文件通过；`git diff --check` 无空白错误。
- handoff 创建后复查：52 个稳定任务、53 个 Markdown 文件通过。
- 聚焦自审修复两点：速查表把 Agent/Runner 从一行拆成定义与执行两层；E4 分支补齐不含 Key 值的低预算配置表。

## 失败尝试

- ADR-0002/0005 首次使用了猜测文件名，路径不存在；列出 decisions 目录后按真实文件名读取。
- 30 项映射首次探测了不存在的 `docs/curriculum-outline.md`；实际真相源是 `docs/syllabus-map.md`，未创建重复大纲。
- 一次多文件 `apply_patch` 因 hunk 结构无效未应用；拆成两个最小补丁后成功。
- 全量门首次在 Vue 写 `frontend/tsconfig.app.tsbuildinfo` 时被沙箱 EPERM 阻断；工作区验证授权后重跑同一脚本全部通过，没有修改系统策略或留下构建改动。

## 警告与未验证范围

- 全量后端仍有既有 Starlette/httpx 弃用警告、Windows symlink 跳过、预期 HTTP/observer/notifier 负向日志；未升级依赖。
- 没有运行带 `-Authorized` 的 online smoke；Provider strict schema、真实 streaming、真实工具、真实 usage、在线费用和资源清理仍无 E4 证据。
- Compose 只验证配置展开；Docker Engine、镜像、容器、PostgreSQL/pgvector 与 Nginx 未运行。
- 学习者尚未在本轮实际提交自测答案、实操产物或费曼复述；工程任务完成不代替个人训练完成。
- M9 MCP Client、工具发现、Skill、M10 持久 LangGraph 和旧 HTTP/SSE 迁移均未在本轮实现。

## 未提交改动

handoff 创建时以上 6 个 M8-T7 文件均未提交；不得回滚或混入 M9-T1 实现。提交后的新 HEAD 由下一条 verification 或 handoff 记录。

## 下一条原子动作

开始 `M9-T1` 的 B 类框架任务：先只读审阅实施计划 M9-T1、`docs/stages/09-mcp-client-skills.md`、现有 TypeScript MCP Server、`backend/requirements-m2.txt` 中锁定的 Python MCP 版本和 FastAPI lifespan 入口；定义服务端允许的 Server 配置、连接/启动 timeout、正常关闭、取消和稳定错误。只实现 Client 配置与生命周期，不提前进入 M9-T2 的工具发现/映射或 M9-T4 的 Skill。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_openai_agents_runtime.OpenAIAgentsRuntimeTest.test_stream_and_post_stream_errors_use_safe_stable_mapping -q
.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_runtime_comparison backend.tests.test_langchain_agent_lab backend.tests.test_framework_runtimes -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 Provider 错误命令 1 项、框架对照 12 项通过，连续性为 52 个稳定任务和 53 个 Markdown 文件。若结果一致，不要重跑 M8 实现或再次执行全量门，直接进入 M9-T1 只读设计检查；在线调用仍必须重新取得当次授权。
