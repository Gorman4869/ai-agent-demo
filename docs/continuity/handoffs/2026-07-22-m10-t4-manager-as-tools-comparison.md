# M10-T4 交接：Agents SDK Manager-as-Tools 对照

- 日期：2026-07-22，Asia/Shanghai
- 完成任务：`M10-T4`
- 完成状态：`verified`
- 下一任务：`M10-T5 / planned`
- 验证基线 HEAD：`ae9e3aa`
- 验证记录：`V-20260722-003`
- 分支：`main`
- 任务等级：A 类角色工具隔离、调用预算与失败闭合，时间盒 2–4 小时
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 新增显式导入的 manager-as-tools 拓扑，使用公开 `Agent.as_tool()` 构造 researcher、writer、reviewer，并由公开 `Runner.run()` 实际执行 manager 与嵌套角色。
2. manager 只持有三个 specialist tool；researcher 只有固定事实查询工具，writer 无业务工具，reviewer 只有要求检查工具。业务工具均经共享 `ToolRegistry`、可信 Run context 和 `build_sdk_tools()` 快照。
3. manager 与 specialist 分别有 6/3 turns 上限；角色失败向外传播，稳定评测错误不包含原始异常。所有 RunConfig 显式关闭 Trace 与敏感 Trace 数据。
4. 新增确定性离线 Model 与 3 个固定课程案例，比较 manager-as-tools 和同工具单 Agent 的质量、本地 elapsed、SDK fixture aggregate usage、失败率和拓扑复杂度。
5. 固定集两组质量均为 1.0、失败率均为 0；manager 每例 9 requests/108 fixture Token/复杂度 12，单 Agent 3/36/3，本地延迟也更高，因此按契约保留单 Agent。
6. 新增 14 项风险驱动测试，覆盖实际嵌套角色执行、角色/工具隔离、高风险省略、Trace 配置、重复工具拒绝、turns 超限、零网络、指标、证据标签、输入校验和异常脱敏。
7. 更新后端规约、实施计划、Stage 10、known issue、status 与 verification；`KI-013` closed。

## 本次修改文件

- `backend/app/agent/multi_agent.py`
- `backend/app/evals/multi_agent.py`
- `backend/tests/test_multi_agent.py`
- `backend/tests/test_workflow_comparison_eval.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/stages/10-durable-langgraph.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-07-22-m10-t4-manager-as-tools-comparison.md`

## 实际验证

- 恢复检查：M10-T3 重规划 14 项、M1 7 项和连续性 52/68 通过，起始代码与记录无漂移。
- 可运行 Demo 最终 3 例通过：两组质量 1.0、失败率 0；manager 27 requests/324 fixture Token/424.656 ms，单 Agent 9/108/138.526 ms，输出选择 `single_agent`。
- 新增专项 14 项无异步警告、无 ResourceWarning 通过；最终 SDK、多 Agent、评测、ToolRegistry、Runtime 与重规划定向回归 93 项通过。
- M1 隔离：禁用 `site-packages` 的手写 Loop 7 项通过，新 SDK 模块未从 `backend.app.agent` 顶层导出。
- 连续性在新增 handoff 后为 52 个稳定任务/69 个 Markdown，通过。
- 所有证据均为本地离线。实际框架编排达到 E2，共享工具授权/Schema 边界达到本地 E3；没有网络、密钥、Provider 或费用。

## 失败尝试与复审修正

- 首次 Demo 因固定案例先于文本校验函数定义而 `NameError`，前移校验后修复。
- SDK 0.18.2 在当前机器上即使 RunConfig 禁用 Trace 仍先初始化默认 exporter，受 SOCKS 代理缺可选 `socksio` 影响在模型调用前失败；未安装依赖或改代理，改为在独立离线评测进程安装无 exporter 的禁用 Trace provider。
- 首个多行 Runner 诊断探针因 PowerShell 引号产生 `SyntaxError`；stdin 探针随后确认 exporter 失败点。
- 首轮 14 项虽退出 0，但替换整个 `socket.socket` 类干扰 Windows Proactor 自管道并产生类型错误日志；改为守卫 `create_connection`/`socket.connect` 后同一专项无日志通过。

## 警告与未验证范围

- fixture Model 每次响应声明 8 input/4 output Token并增加 1 ms delay；这些值只验证 SDK usage 聚合和相对开销，不是 Provider tokenizer、账单、真实模型质量或生产网络延迟。
- 离线评测安装进程本地禁用 Trace provider；该过程不能嵌入应用进程或覆盖应用观测配置。默认 Container、`RunCoordinator`、EventStore、HTTP/SSE 和现有 `OpenAIAgentsRuntime` 均未迁移。
- 没有实现 handoff；完成的是计划允许的 manager-as-tools。现有 SDK Runtime 对 handoff event 的 fail-closed 行为保持不变。
- 未运行全仓 `scripts/verify.ps1`，原因是没有依赖、锁文件、构建配置、默认组合根、前后端 API 或共享 Runtime/Store Protocol 变化；实际风险由 93 项定向集覆盖。
- 没有执行 M10-T5 checkpoint 损坏、工具 timeout、审批等待或结果未知副作用故障注入，也没有进程重启/PostgreSQL 证据。

## 未提交改动

M10-T4 代码、测试、规约、课程和连续性记录当前均在基线 `ae9e3aa` 之上的工作区；没有任务外改动，没有安装依赖，没有远程 Git 操作。实现提交后由下一条 verification 或 handoff 固定新 HEAD。

## 下一条原子动作

开始 `M10-T5` 前，只读审阅实施计划 M10-T5、现有 checkpoint/approval/replanning 测试和三个 ADR，列出中断、新 Runtime 共享 saver、工具 timeout、审批等待、checkpoint 损坏与结果未知副作用的可注入矩阵。只实现现有内存边界能真实证明的故障，不把它扩大成 M11 PostgreSQL、进程重启或默认主链迁移。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.multi_agent
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_multi_agent backend.tests.test_workflow_comparison_eval -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 Demo 的 3 个固定案例两组质量均为 1.0、失败率 0并选择 single Agent；专项 14 项、M1 7 项通过且无 ResourceWarning，连续性任务数保持 52，Markdown 数量以本 handoff 加入后的实际输出为准。若一致，不要重做 M10-T4，直接进入 M10-T5 只读故障矩阵。没有用户新的单次授权，不得读取 Key 或执行真实模型。
