# M8-T6 交接：在线冒烟门禁离线代码完成

- 日期：2026-07-17，Asia/Shanghai
- 完成任务：`M8-T6`
- 完成状态：`code_complete`；真实在线 E4 未授权且未执行
- 下一任务：`M8-T7 / planned`
- 验证基线 HEAD：`e03f8d6`
- M8-T5 实现提交：`e03f8d6`
- M8-T6 实现提交：待本轮本地 commit 固定
- 验证记录：`V-20260717-001`
- 分支：`main`
- 任务等级：`C`，外部在线付费门禁；离线准备时间盒 30-90 分钟
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 新增独立 `scripts/verify-online.ps1`，不进入默认 `scripts/verify.ps1`；支持 `-Suite M8`，缺少显式 `-Authorized` 时第一步拒绝。
2. 新增 `backend.app.online_smoke` 二次门禁；未授权时不读取环境，授权后才要求 `agents_sdk + openai + online=true + Key + model` 完整配置。
3. 固定低预算策略：2-4 steps、2 次模型调用、Run 60 秒、模型 30 秒、输入 4000 token、输出 512 token、零模型重试和最多 0.25 USD 的服务端 cap。
4. 要求调用者显式提供本次 input/output 每百万 token 费率；先校验声明的 token 上限估算不超过 cap，再按实际 usage 计算摘要估算。
5. 真实执行路径创建 `RunRecord`，经现有 `RunStore -> RunCoordinator -> agents_sdk Runtime -> EventStore` 执行固定 `add_numbers(2, 3)` 任务。
6. 验收要求持久事件具备连续 sequence、匹配 Run ID、流式 delta、配对且成功的 `add_numbers` start/completed、唯一正 usage 和完整 Run 生命周期。
7. 输出内容自由的安全 JSON 摘要，只含模型、时长、token、估算费用及来源、工具完成标记、事件数与退出码；不输出 prompt、answer、工具数据或 Key。
8. 新增 12 项关键离线测试，覆盖双门禁、低预算、价格上限、完整 Fake Runtime 持久纵切、证据缺失、usage 错误、失败脱敏和 PowerShell 原始退出码。

## 门禁与执行契约

未授权恢复检查只能运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-online.ps1 -Suite M8
```

原始 `powershell.exe` 进程应在启动 Python 前退出 64。只有用户针对当次调用重新明确授权、进程环境已由用户配置且费率来自用户核对的当前模型价格后，才允许增加：

```text
-Authorized
-InputPricePerMillionUsd <declared-current-rate>
-OutputPricePerMillionUsd <declared-current-rate>
```

同时需要以下进程环境契约；不得把 Key 放进命令行、源码、测试、文档或日志：

```text
AI_AGENT_RUNTIME=agents_sdk
AI_AGENT_MODEL_PROVIDER=openai
AI_AGENT_ONLINE_ENABLED=true
AI_AGENT_TRACE_INCLUDE_SENSITIVE=false
OPENAI_API_KEY=<process environment only>
OPENAI_MODEL=<explicit model>
AI_AGENT_MAX_STEPS=2..4
AI_AGENT_MAX_MODEL_CALLS=2
AI_AGENT_RUN_TIMEOUT_MS<=60000
AI_AGENT_MODEL_TIMEOUT_MS<=30000
AI_AGENT_MAX_INPUT_TOKENS<=4000
AI_AGENT_MAX_OUTPUT_TOKENS<=512
AI_AGENT_MAX_COST_USD<=0.25
AI_AGENT_MAX_MODEL_RETRIES=0
```

operator-supplied 费率只产生估算，不是 Provider 账单；usage 返回前无法进行准确成本阻断，仍由 `KI-018` 跟踪。

## 本次修改文件

- `backend/app/online_smoke.py`
- `backend/tests/test_online_smoke.py`
- `scripts/verify-online.ps1`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/handoffs/2026-07-17-m8-t6-online-smoke-gate.md`

## 实际验证

- 接手恢复：M8-T5 Demo、89 项最小恢复回归和连续性检查均通过；实际 HEAD `e03f8d6` 与 M8-T5 文件清单一致。
- 新增测试：12 项全部通过；未授权环境使用不可读取 Mapping，PowerShell 子进程只接收最小系统环境且原始退出码为 64。
- 最终定向回归：102 项通过；既有 Starlette/httpx 弃用警告和三条 notifier 负向用例日志不变。
- Fake Runtime 经真实 Run Store、Coordinator 和 Event Store 形成 E3 纵切；它没有访问网络，也不是 Provider E4 证据。
- `git diff --check` 通过；疑似凭据扫描预期无匹配，没有固定 Key 或 Token。
- 文档闭环后连续性检查通过：52 个稳定任务、51 个 Markdown 文件，当前任务、状态、链接和 handoff 有效。
- `KI-019` 已关闭：`V-20260717-001`、status 和本 handoff 均记录 M8-T5 实现提交 `e03f8d6`。

## 失败尝试

- 只读查找根目录 `pyproject.toml` 返回不存在；仓库实际沿用 `unittest` 与 `backend/requirements-m2.txt`，未新增工具。
- 新测试首轮 11 通过、1 失败：默认 Windows 执行策略在脚本逻辑前拒绝；测试改用仓库统一的 `-ExecutionPolicy Bypass` 后 12 项通过，没有修改系统策略。
- 一次疑似凭据扫描因 PowerShell 嵌套引号解析失败；使用单引号等价模式重跑后预期无匹配。
- 统一命令宿主直接运行预期失败脚本时把非零状态展示为 1；自动化通过 `subprocess.run` 验证 `powershell.exe` 原始退出码为 64。

## 未验证范围

- 没有用户新的单次授权，未运行带 `-Authorized` 的脚本，未读取真实 Key、访问 Provider 或产生费用。
- Provider strict schema、真实 streaming、真实工具调用、真实 usage、模型质量、在线费用和资源清理仍无 E4 证据；M8-T6 因此不能标记 `verified`。
- 没有运行 `scripts/verify.ps1` 全量门；任务没有修改依赖、锁文件、HTTP API、前端、跨前后端公共契约或发布配置，102 项定向回归覆盖修改边界。
- `KI-018` 的逐调用 usage、硬成本阻断、版本化定价源与持久账本未实现。
- Docker Engine、PostgreSQL/pgvector、Nginx、LangGraph 持久恢复和旧 HTTP/SSE 迁移均未验证。

## 未提交改动

handoff 创建时以上 7 个 M8-T6 文件均未提交；不得回滚或混入 M8-T7 实现。提交后应在下一条 verification 或 handoff 回填 M8-T6 实现提交。

## 下一条原子动作

开始 `M8-T7` 的 B 类里程碑验收：先只读审阅 `docs/stages/08-real-model-runtimes.md`、实施计划 M8-T7 和 30 项大纲映射，列出教程、跟练、自测、速查表、费曼复述和实际命令证据缺口。M8-T7 引用 M8-T6 `code_complete / online not authorized`，不得为了填表运行线上调用或把 Fake 证据描述成真实 Provider。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_online_smoke -q
.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_online_smoke backend.tests.test_settings backend.tests.test_container backend.tests.test_runtime_contract backend.tests.test_openai_agents_runtime backend.tests.test_run_coordinator -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify-online.ps1 -Suite M8
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

前两组测试应分别为 12 项和 102 项通过；未授权在线脚本的原始进程退出码应为 64，连续性检查应通过。若这些结果一致，不要重做 M8-T5/M8-T6，直接审阅 M8-T7 验收材料。
