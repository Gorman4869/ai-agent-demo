# M8-T5 交接：三 Runtime 契约与 LangChain 对照

- 日期：2026-07-16，Asia/Shanghai
- 完成任务：`M8-T5`
- 完成状态：`verified`
- 下一任务：`M8-T6 / planned`
- 验证基线 HEAD：`f83cbbc`
- 验证记录：`V-20260716-008`
- 分支：`main`
- 任务等级：`B`，普通离线框架对照，时间盒 60–90 分钟
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 新增 `LangGraphRuntime`，通过实际 `StateGraph.compile().ainvoke()` 实现共享 `AgentRuntime`，包含模型/工具条件循环、安全结果、稳定错误、协作取消和 Event sink 传播。
2. Container 在 `runtime=langgraph + provider=mock` 时注册 LangGraph Runtime；现有 Manual 默认、Agents SDK 显式在线门和旧 HTTP/SSE 不变。
3. 新增三 Runtime 共用 fixture：相同输入、相同 `add_numbers` ToolRegistry、成功结果和缺参错误分别经过 Manual、Agents SDK FunctionTool 桥与 LangGraph。
4. 新增 6 个共享 Runtime 测试方法，通过参数化子用例证明成功/失败语义、handler 执行边界、事件脱敏、预取消、模型错误和 Store 失败传播。
5. 新增 `labs/langchain-agent/`：使用锁定 LangChain 1.3.13 的公开 `create_agent()` 与 `agent.invoke()`，实际执行 ToolNode 和消息循环。
6. 新增 3 个 LangChain 测试，覆盖工具调用、socket 双守卫和输入边界；README 记录四种方案取舍及 E2 证据边界。
7. 在 M8 阶段文档加入 M8-T5 入口；实施计划、known issue、verification 和 status 已按职责更新。

## 已固定的对照语义

```text
同一 RuntimeRequest + 同一 ToolDefinition
  -> ManualRuntime / OpenAIAgentsRuntime / LangGraphRuntime
  -> tool.started
  -> ToolRegistry 参数校验与执行
  -> tool.completed | tool.failed(error_code)
  -> 同一 RuntimeResult(completed, answer)
```

- 成功 case：`a=2,b=3`，三个 Runtime 各执行 handler 一次，结果为 5。
- 失败 case：缺少必需参数 `b`，三个 Runtime 均返回 `invalid_arguments`，handler 不执行，随后返回相同安全 fallback。
- 共享事件不持久化 arguments、value 或 error_message。Agents SDK 可有额外的安全输出 delta 与 Run aggregate usage，这不破坏工具语义一致性。
- Agents SDK 测试是 fake Runner 边界下的真实 FunctionTool/Runtime 路径；LangChain 使用确定性 ChatModel。两者都不是在线 Provider 证据。

## 框架边界

- Manual 保留原理教学和完全显式控制；不改写旧同步 Loop。
- Agents SDK 保留主 SDK 对照；真实 Provider 仍由 M8-T6 单次授权验证。
- LangGraph 当前只是无 checkpoint 的共享 Runtime；持久状态、interrupt、resume 和恢复由 M10 单独实现。
- LangChain 只在独立 lab 中比较生态抽象，不注册为主 Runtime，不接入 Coordinator，也不新增第二套持久事件映射。

## 本次修改文件

- `backend/app/agent/graph_runtime.py`
- `backend/app/container.py`
- `backend/app/services/run_service.py`
- `backend/tests/runtime_comparison_fixtures.py`
- `backend/tests/test_runtime_comparison.py`
- `backend/tests/test_langchain_agent_lab.py`
- `backend/tests/test_container.py`
- `labs/langchain-agent/demo.py`
- `labs/langchain-agent/README.md`
- `docs/stages/08-real-model-runtimes.md`
- `docs/implementation-plan.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/handoffs/2026-07-16-m8-t5-runtime-framework-comparison.md`

## 实际验证

- 接手恢复：连续性检查通过；handoff 最小恢复集 64 项通过。
- LangChain Demo：`create_agent -> agent.invoke -> ToolNode` 实际执行一次，答案 5，消息序列包含 `ToolMessage`。
- 最终定向回归：89 项通过；三条 notifier 失败日志是既有负向用例，另有既有 Starlette/httpx 弃用警告。
- M1 零依赖兼容：`python -S` 下 7 项手写 Loop 测试与 Demo 均通过；LangGraph Runtime 未从 `backend.app.agent` 顶层导出。
- `git diff --check` 通过，无空白错误，仅有既有 LF/CRLF 转换提示。
- 文档闭环后连续性检查通过：52 个稳定任务、50 个 Markdown 文件，任务 ID、当前任务、相对链接和大纲映射有效。
- 依赖版本只读确认：Python 3.12.10、LangChain 1.3.13、LangGraph 1.2.9、OpenAI Agents 0.18.2。

## 失败尝试

- 首次读取 `AGENTS.md` 未指定 UTF-8，PowerShell 输出乱码；改用 `Get-Content -Encoding utf8` 后正常。
- 两次只读 `rg` 探测包含不存在的根目录文件和 Windows 不接受的路径通配符，返回非零；改用明确路径后确认依赖与代码位置。
- 首次新增 lab 文件时父目录不存在；沙箱内 `New-Item` 被拒绝，经工作区目录创建授权后成功，没有安装依赖或访问网络。
- 首次直接运行 lab 的中文控制台输出乱码但退出码为 0；使用 `python -X utf8` 重跑后可读，Unicode 自动化断言一直通过。

## 未验证范围

- 没有运行 `scripts/verify.ps1` 全量门；本任务无依赖、锁文件、前端、HTTP API 或发布配置变化，最终 89 项定向回归覆盖修改边界。
- 没有读取真实 Key、运行在线 Provider、产生费用或执行 M8-T6。
- Provider strict schema、真实 streaming、真实工具调用、真实 usage/费用和资源清理仍无证据。
- Docker Engine、PostgreSQL/pgvector、Nginx、LangGraph 持久恢复和旧 HTTP/SSE 迁移均未验证。

## 下一条原子动作

开始 `M8-T6` 的 C 类离线准备：只读核对 Settings/ADR-0002/ADR-0005/ADR-0008，设计 `scripts/verify-online.ps1` 的显式开关、模型名、Key 存在性、单次授权参数、低预算和脱敏退出条件。没有用户新的明确单次授权时，只实现和测试 fail-closed 门，不读取 Key、不运行真实模型、不产生费用。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B .\labs\langchain-agent\demo.py
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_runtime_comparison backend.tests.test_langchain_agent_lab backend.tests.test_runtime_contract backend.tests.test_openai_agents_runtime backend.tests.test_run_coordinator backend.tests.test_container backend.tests.test_framework_runtimes -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

若 Demo、89 项定向回归和连续性检查仍通过，不要重做 M8-T5。下一步仍是 M8-T6 的 fail-closed 脚本设计；在线执行必须重新取得用户单次授权。
