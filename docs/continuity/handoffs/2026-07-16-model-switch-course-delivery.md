# 模型切换交接：课程优先、里程碑验收

- 日期：2026-07-16，Asia/Shanghai
- 交接类型：课程生产协议与模型切换恢复
- 当前任务：`M8-T5`
- 当前任务状态：`planned`，本次不提升状态
- 接手基线 HEAD：`ed5ad9c`
- 分支：`main`
- 任务等级：`B`，纯文档与连续性调整，时间盒 30–90 分钟
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次目的

把“如何在不降低课程质量的前提下加快后续生成”固化到仓库中，使任何新模型不依赖聊天记录也能使用同一套范围、时间盒、证据和验收规则。该调整只改变课程生产节奏，不改动课程技术目标、稳定任务 ID、M8-T5 业务范围或已有验证结论。

## 本次完成

1. 新增[课程高效交付协议](../course-delivery-playbook.md)，固定质量底线、A/B/C 任务等级、E0–E4 证据等级、时间盒、定向/全量验证边界、文档与提交节奏。
2. 更新[仓库协作规则](../../../AGENTS.md)，把交付协议加入所有新模型的强制阅读顺序。
3. 更新[连续性入口](../README.md)，保持它仍是唯一恢复入口，并为交付协议定义单一职责。
4. 更新[实施计划](../../implementation-plan.md)的通用规则，明确原子任务提供真实纵切，完整教程、题库、速查表与费曼任务在里程碑验收时汇总。
5. 更新[当前状态](../status.md)和[根 README](../../../README.md)的导航；没有修改 Runtime、API、前端、测试或 M8-T5 业务代码。

## 不得丢失的现场事实

- 计划版本仍为 2.0，共 52 个稳定任务。已有 8 个交付锚点：7 个 `verified`，M8-T4 为 1 个 `code_complete`；从 M8-T5 起仍有 44 个稳定任务。
- 当前实际接手基线是 `ed5ad9c`。M8-T4 的设计、实现、实质文档闭环和最终状态锚点分别是 `38a39d4`、`ac24dda`、`176d182`、`ed5ad9c`。
- M8-T4 的证据是 `V-20260716-006`：SDK 专项 33 项通过；全量后端 231 项通过、1 项既有 Windows symlink 能力跳过；前端构建、MCP 构建、`pip check` 和 Compose 配置通过。
- M8-T4 全程 offline、没有读取真实 API Key、费用为 0。真实 Provider schema、streaming、工具调用、usage、费用和资源清理没有证据，所以 M8-T4 只能保持 `code_complete`。
- M8-T5 仍为 `planned`，没有未提交业务修改。旧 HTTP/SSE、M8-T6 在线 Runner、M10 checkpoint/interrupt/resume 和 M13 生产强化都不属于本次起点。
- Docker Engine 未运行、真实在线冒烟未获新的单次授权、远程 Git 地址未提供；它们不阻塞 M8-T5 的离线实现。

## M8-T5 的高效执行边界

M8-T5 按 B 类课程任务执行，必要时拆成两个不改变稳定任务 ID 的内部原子步骤：

1. 用同一输入、计算工具、成功结果和失败语义建立 Manual、Agents SDK、LangGraph 的共享 contract fixture。
2. 在 `labs/langchain-agent/` 建立真正进入 LangChain 公开 API 调用链的离线最小实验，并完成四种方案的取舍表。

整体优先控制在约 8–12 个高价值新增用例或等价参数化覆盖；测试数不是 KPI。目标证据为：三 Runtime 达到共享契约 E3，LangChain 对照至少达到真实离线调用链 E2，并通过相关回归。

本任务明确不做：

- 不把 LangChain 接入主 `AgentRuntime`。
- 不实现 LangGraph checkpoint、interrupt、resume 或生产持久化；这些属于 M10。
- 不迁移旧 HTTP/SSE；统一 API 属于 M12。
- 不补完整费用账本、跨进程 lease、部署或容量治理；这些属于 M11–M13。
- 不安装新依赖，不读取 Key，不运行 M8-T6，不把 Fake/Mock 写成 E4 在线证据。

如果第一个内部步骤达到 90 分钟仍未形成真实可运行纵切，应先停在可验证边界并交接，不把后续里程碑内容提前塞入 M8-T5。

## 给新模型的启动指令

可直接复制以下内容作为新会话第一条工程指令：

```text
接手 ai-agent-demo 后，不要依赖聊天记录推断进度。

依次运行和阅读：
1. git status --short 与 git log -6 --oneline
2. AGENTS.md
3. docs/continuity/README.md
4. docs/continuity/status.md
5. docs/continuity/course-delivery-playbook.md
6. implementation-plan 的 M8-T5、关联 ADR、最新 handoff 与 V-20260716-006
7. M8-T4 handoff 指定的最小恢复测试

当前唯一任务是 M8-T5 / planned，业务代码尚未开始。保持 offline，不重做 ac24dda，不运行 M8-T6，不迁移旧 HTTP/SSE。
按课程优先、里程碑验收执行：先建立三 Runtime 共用 fixture，再做 LangChain 最小真实调用链；整体只保留约 8–12 个高价值新增用例或等价覆盖。普通任务跑定向回归，完整教程和全量验证留到 M8-T7，除非公共契约变化或测试结果触发扩大验证。
未经用户新的明确授权，不安装依赖、不使用密钥、不执行在线/付费调用、不配置或推送远程 Git、不扩大任务范围。
结束时如实更新 verification、status 和 handoff，并留下下一条精确原子动作。
```

## 本次修改文件

- `AGENTS.md`
- `README.md`
- `docs/implementation-plan.md`
- `docs/continuity/README.md`
- `docs/continuity/status.md`
- `docs/continuity/course-delivery-playbook.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-07-16-model-switch-course-delivery.md`

## 本次验证

- 验证记录：`V-20260716-007`
- `git diff --check` 通过，无空白错误，仅有既有 LF/CRLF 转换提示。
- 连续性检查通过：52 个稳定任务、49 个 Markdown 文件，任务 ID、当前任务、accepted spec、相对链接和大纲映射均有效。
- 占位符扫描无匹配；一次独立聚焦复审发现的纯文档测试规则冲突和验证记录缺口均已修正。
- 没有代码、依赖、构建配置或公共接口变化，因此没有重复运行 M8-T4 的 231 项全量回归；该范围继续引用 `V-20260716-006`。

## 残余边界

- 本次是交付规则与恢复文档调整，没有重跑 M8-T4 的 231 项全量回归；其代码证据继续由 `V-20260716-006` 提供。
- 本协议不会自动判断某项设计是否正确。新模型仍需读取实际代码、锁定版本和任务相关测试，不能只按提示词盲写。
- 如果后续用户改变速度、验证深度或课程目标，应先修改交付协议并记录新的 handoff，不能只在聊天中形成隐藏规则。

## 下一条原子动作

开始 M8-T5 的第一个内部步骤：只读核对 Manual、Agents SDK 和现有 LangGraph 的真实公共边界，给出共享成功/失败 fixture 的最小设计；经用户确认后实现。不要在该步骤开始 LangChain、M10 持久化或在线调用。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime backend.tests.test_runtime_contract backend.tests.test_run_coordinator -q
```

若连续性检查通过、实现提交 `ac24dda` 存在且 M8-T4 专项仍通过，不要重做 M8-T4。从 M8-T5 的共享 contract fixture 设计开始。
