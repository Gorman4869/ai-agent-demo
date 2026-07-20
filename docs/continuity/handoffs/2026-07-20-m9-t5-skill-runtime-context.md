# M9-T5 交接：Skill Runtime 上下文与离线评测

- 日期：2026-07-20，Asia/Shanghai
- 完成任务：`M9-T5`
- 完成状态：`verified`
- 下一任务：`M9-T6 / planned`
- 验证基线 HEAD：`c820c7e`
- M9-T4 实现提交：`de8a63d`
- M9-T5 实现提交：`a6ff518`
- 验证记录：`V-20260720-007`、`V-20260720-008`
- 架构决策：`ADR-0010`
- 分支：`main`
- 任务等级：开始时预估 B；发现共享 `RuntimeRequest` 与三 Runtime 契约变化后上调为 A，时间盒 2–4 小时
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. `RuntimeRequest` 增加隐藏 repr、32,000 UTF-8 字节上限的可选 `prompt_context`，字段放在既有 `execution_context` 之后，保留旧第三位置参数兼容性。
2. `SkillContextBuilder` 从 M9-T4 冻结 Resolver 快照生成确定性 JSON，限制为 4 个 Skill、24,000 字节；内嵌 reference 内容但将源路径替换为稳定编号。
3. `SkillAwareRuntime` 只根据原始用户输入解析 Skill；无匹配时原请求对象原样传递，未知显式 Skill 或上下文失败返回稳定安全错误。
4. 默认 Container 包装内建 Manual、Agents SDK 与 LangGraph Runtime。Manual/LangGraph 使用 system message，SDK 默认 factory 使用 instructions，三条路径均保留原始 user input 和可信工具上下文。
5. 新增可直接运行的固定离线评测，真实执行 LangGraph Runtime API，对比 `$research-summary` 触发与普通不触发输入；报告效果、UTF-8 字节和明确标注的 Token 启发式。
6. 10 项新增测试覆盖上下文边界、路径脱敏、显式/自动/不触发、三 Runtime 消费、未知 Skill、旧位置参数、工具 Schema 对照，以及角色、审批和参数校验不可绕过。
7. 阶段 09、后端规范与 `ADR-0010` 记录共享契约、证据等级和非目标；没有提前扩写 M9-T6 完整题库或进入 M10。

## 真实证据边界

- 固定评测通过 LangGraph `ainvoke()` 进入真实框架 Runtime，结果为 2/2；触发答案包含来源与限制，不触发答案保持通用处理。
- 当前 `research-summary` 上下文为 3153 UTF-8 字节，`ceil(bytes / 4)` 为 789 个估算输入 Token；不触发增加 0 字节。
- 评测模型是确定性离线 fixture，Provider usage 明确不可用、美元费用为 `null`。该证据是 E3 应用契约，不是在线模型质量、真实 tokenizer、usage 或账单。
- 恶意测试 Skill 要求绕过控制时，Registry 仍返回 `permission_denied`、`approval_required`、`invalid_arguments`，handler 均未执行。

## 本次修改文件

- `backend/app/skills/context.py`
- `backend/app/skills/runtime.py`
- `backend/app/skills/__init__.py`
- `backend/app/evals/skill_context.py`
- `backend/app/agent/runtime.py`
- `backend/app/agent/manual_loop.py`
- `backend/app/agent/graph_runtime.py`
- `backend/app/agent/sdk_runtime.py`
- `backend/app/services/run_service.py`
- `backend/app/container.py`
- `backend/tests/test_skill_context.py`
- `backend/tests/test_container.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/stages/09-mcp-client-skills.md`
- `docs/continuity/decisions/ADR-0010-bounded-skill-runtime-context.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/handoffs/2026-07-20-m9-t5-skill-runtime-context.md`

## 实际验证

- M9-T4 恢复：10 项 Catalog/Resolver 测试与 52 个稳定任务/58 个 Markdown 连续性检查通过。
- M9-T5 聚焦：10 项新增测试通过；固定 LangGraph 离线评测 2/2 通过。
- 定向回归：12 个 Runtime、Skill、Container、工具安全相关模块共 151 项全部通过。
- 全量首轮：后端 294 项中 292 项通过、1 项既有 symlink 能力跳过、1 项 TypeScript MCP 启动超时；单项原命令重跑通过。
- 全量第二轮：后端 294 项中 293 项通过、1 项既有 symlink 能力跳过；Code Agent、依赖、Vue、MCP TypeScript 与 Docker Compose 配置门全部通过。
- 最终边界收紧后：75 项直接相关回归与后端全量 294 项再次通过；同次脚本随后因沙箱拒绝写 Vue `tsbuildinfo` 退出 1。Vue build 经批准在沙箱外重跑通过，MCP TypeScript build 和 Compose 配置分别退出 0。
- 连续性与 diff：新增 ADR 后 52 个稳定任务、59 个 Markdown 通过；tracked 与新增文件无尾随空白错误。

## 失败尝试与修复

- 设计审阅发现把 Skill 拼进用户输入会污染原始请求，因此把任务从 B 上调 A，改用独立 `prompt_context` 和 Runtime 装饰器，并新增 `ADR-0010`。
- 自审发现新字段最初位于 `execution_context` 前方，可能改变旧第三位置参数；在提交前移到末尾并增加兼容测试。
- 全量首轮一个 TypeScript MCP E2E 在本地进程启动时命中 `startup_timeout`。没有提高超时或改代码；原测试单独重跑和全量重跑均通过，因此记录为一次性时序波动而非静默忽略。
- 最终工作区全量脚本在 Vue 步骤遇到 `tsconfig.app.tsbuildinfo` 写入 `EPERM`；相同构建在沙箱外成功，未安装依赖。该脚本退出 1 与后续拆分通过都保留在 `V-20260720-007`。

## 警告与未验证范围

- 最终全量仍有 1 项既有 Code Agent symlink 能力测试因 Windows 环境跳过；没有修改系统策略或使用 junction 绕过。
- Starlette/httpx 弃用提示、测试预期 notifier warning 和 asyncio debug 慢回调诊断存在，但不影响最终退出码；没有按提示安装依赖。
- Compose 配置退出 0，但沙箱无法读取用户目录 Docker `config.json`，打印 access denied warning；没有启动 Docker Engine 或容器。
- `SkillAwareRuntime` 默认只包装 Container 自行创建的 Runtime；显式注入 Runtime 保持原对象，调用方需要时主动组合装饰器。
- 没有执行真实模型、读取 Key、访问模型网络或产生费用；真实模型指令遵循、Provider Token/usage/成本、线上质量和资源清理仍未验证。
- 没有实现 Skill 管理写接口、文件监听、跨进程刷新、审批 interrupt/resume、持久 usage/cost 账本或 M10 工作流。

## 未提交改动

M9-T5 代码、测试、ADR、阶段材料和首轮连续性记录已提交为 `a6ff518`。提交后只修改本 handoff、status 和 verification log 以固定实现锚点；这些记录由后续本地文档提交闭环，工作区没有任务外改动。

## 下一条原子动作

开始 `M9-T6` 里程碑验收前，只读盘点 M9-T1 至 M9-T5 的现有代码、阶段材料、精确命令、验证索引和 30 项大纲映射。先列出缺失的跟练、MCP/Function Calling/Skill 对照速查、概念/实操/场景题与费曼验收项，再按里程碑任务统一补齐；不要修改已验证 Runtime，不提前进入 M10。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_skill_context -q
.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.skill_context
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 10 项 SkillContext 测试通过；固定评测 2/2 通过，触发上下文 3153 字节/启发式 789 Token且不触发为 0；连续性在新增 handoff 后为 52 个稳定任务和 60 个 Markdown 文件。若一致，不要重做 M9-T1–M9-T5，直接进入 M9-T6 材料盘点。没有用户新的单次授权，不得读取 Key 或执行真实模型。
