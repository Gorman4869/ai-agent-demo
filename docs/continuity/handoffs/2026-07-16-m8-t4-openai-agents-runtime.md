# M8-T4 交接：OpenAI Agents SDK Runtime

- 日期：2026-07-16，Asia/Shanghai
- 任务：`M8-T4`
- 状态：`code_complete`
- 实现提交：`ac24dda`
- 验证记录：`V-20260716-006`
- 分支：`main`
- 远程仓库：未配置
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0

## 本次完成

1. 把原先只会构造 Agent 的脚手架扩展为生产边界清晰的 `OpenAIAgentsRuntime`，实际适配公开 `Runner.run_streamed()` 与 `stream_events()`。
2. 每 Run 延迟创建显式 `AsyncOpenAI + OpenAIResponsesModel`，关闭底层隐藏重试，有界关闭 client，不修改 SDK 全局 Key 或默认模型。
3. 每次 RunConfig 强制关闭 SDK Trace 和敏感 Trace，并显式设置 model、usage、输出上限与 SDK retry 策略。
4. 新增结构化 `answer` 增量解码：支持跨 chunk escape、Unicode 代理对和转义键；只发正文，并以安全 segment 区分多轮对象。
5. 新增 SDK 事件白名单：文本 delta、工具开始/完成/失败和 Run aggregate usage；raw Provider、SDK item、arguments、output、响应 ID 和异常文本不越界。
6. 新增共享 ToolRegistry → FunctionTool 桥；每 Run 身份/角色、定义快照、Schema、call ID、参数和输出全部重新校验并有界。
7. M10 审批 interruption/resume 完成前，只向 SDK 暴露低风险、无需审批、无副作用的工具；其他定义 fail closed。
8. 新增 immediate cancel + 原迭代器 drain + 有界清理语义；晚到事件不落库，sink/Store 失败不会被伪装成 Provider 失败或普通取消。
9. Container 只在完整 `agents_sdk + openai + online=true + Key + model + 安全 Trace` 配置门下注册 SDK Runtime，构造阶段不创建 client、不联网；默认 Manual/Mock 不变。
10. Coordinator 在执行前校验可信 principal 与 durable Run owner 一致；不一致时 Runtime 与 Store 均不启动。
11. 用 33 项 SDK 专项和 231/1 全量离线回归固定正常、失败、取消、竞态、脱敏、预算和兼容行为。

## 关键文件

- `backend/app/agent/sdk_runtime.py`
- `backend/app/agent/sdk_tools.py`
- `backend/app/container.py`
- `backend/app/services/run_coordinator.py`
- `backend/tests/test_openai_agents_runtime.py`
- `backend/tests/test_container.py`
- `backend/tests/test_run_coordinator.py`
- [ADR-0008](../decisions/ADR-0008-openai-agents-runtime-adapter.md)
- [M8 跟练文档](../../stages/08-real-model-runtimes.md)
- [实施计划 M8-T4](../../implementation-plan.md)
- [验证日志](../verification-log.md)
- [当前状态](../status.md)

## 已固定的数据流

```text
RunCoordinator
  -> OpenAIAgentsRuntime
       -> AgentFactory(per Run tools/context)
       -> ModelFactory(per Run explicit client/model)
       -> Runner.run_streamed
            -> original stream_events iterator
                 -> structured answer decoder
                 -> reviewed RuntimeEvent
                 -> await EventStore sink
            -> typed final_output + aggregate usage
  -> TerminalCommit
```

- Runtime 只发过程事件；`run.started/completed/failed/cancelled` 继续由 Coordinator 独占。
- SDK/Pydantic/Provider 对象不能出现在 `RuntimeResult`、EventStore 或普通日志。
- `model.output.delta` 在结构化模式只有 `delta` 与正整数 `segment`；同一对象跨 chunk segment 不变，新对象递增，typed final output 必须匹配最后 segment。
- 工具事件只保留 ID、名称、成功状态和稳定错误码；原始参数、结果和异常文本禁止持久化。
- `model.usage` 是 Run aggregate，不是一次模型调用；未知费用必须是 `None + unknown`。

## 审查中发现并修复

- 最初把结构化 raw delta 当普通文本；真实形状是 JSON framing。已改为增量解码并补 escape、代理对、转义键和多 segment 测试。
- 最初输出模型的 Pydantic 字段把 `minLength/maxLength` 放进 Provider strict schema；已从传输 schema 移除，空白与 UTF-8 字节限制仍在 Runtime 执行。
- 最初工具桥允许审批状态进入当前 Run；现阶段改为审批、高风险和副作用定义全部省略，等待 M10 持久 interruption/resume。
- 最初工具定义可能受注册后修改影响；现在每 Run 深拷贝、重新校验并放入隔离 registry。
- 最初工具输出只在完整序列化后看大小；现在先限制循环、深度、节点与累计 UTF-8 字节，避免序列化放大。
- 最初 owner 与工具 principal 没有在 active 执行前绑定；Coordinator 已提前拒绝不一致身份。
- 最初 `max_turns` 没有表达两个预算的较紧者；现在使用 `min(max_steps,max_model_calls)` 并映射对应稳定错误码。
- 最初外层取消与 sink 失败竞态可能隐藏 Store 故障；现在完成清理后 Store 失败优先传播。
- 最初 client 清理没有硬上限；现在每 Run close 有限时保护。

## 实际验证摘要

- SDK Runtime/工具/Coordinator 专项：33 项通过。
- `scripts/verify.ps1`：231 项后端测试通过，1 项既有 Windows 符号链接能力测试跳过。
- Controlled Code-Agent Demo、`pip check`、Vue 生产构建、MCP TypeScript 构建和 Compose 配置均通过。
- 本地版本：`openai-agents==0.18.2`、`openai==2.45.0`；没有安装或升级依赖。
- 三份独立只读复审覆盖 SDK 公共 API、Runtime 契约/取消竞态和工具/身份/输出安全；阻断项与高风险代码问题清零。
- `compileall` 辅助命令因既有 `__pycache__` 写权限得到 `WinError 5`；未改权限，231 项测试已实际导入执行模块。

## 预算必须这样解释

| 能力 | 当前事实 |
| --- | --- |
| turn | `max_turns=min(max_steps,max_model_calls)`，属于 SDK 执行上限 |
| output | `max_output_tokens` 传给每次模型请求；Runtime 另做流式字节和最终字节保护 |
| retry | SDK retry 有界，底层 OpenAI client retry 为 0，避免双层重试 |
| requests/input/output usage | Run 结束后读取 aggregate 并核对，属于事后发现，不是超额前硬关闭 |
| cost | 没有可信定价和 ledger；`max_cost_usd` 尚未执行，未知费用不填 0 |
| timeout | HTTP timeout 不是整个工作流的硬墙钟；Run deadline 由 Coordinator 控制，清理和提交仍需有限时间 |

不要把 Settings 有字段、ModelSettings 有参数或 usage 能读取描述成“生产级成本硬门禁已完成”。该缺口由 `KI-018` 跟踪。

## 残余风险

- `KI-001`：mitigated。离线生产适配器完成；真实 Provider streaming、工具和 usage 仍待 M8-T6。
- `KI-016`：open。Runtime 已开始后的过程 Store 故障仍需要 lease、扫描和重启恢复。
- `KI-017`：open。允许的只读同步工具经 `asyncio.to_thread()` 执行，取消不能硬杀线程，可能继续占用默认 executor。
- `KI-018`：open。模型请求数/输入 Token 只近似或事后校验，费用未执行，HTTP timeout 不是整次 Run 硬期限。
- Provider strict schema 接受度、真实流、真实 usage、真实费用、模型质量和 Provider 侧资源清理没有在线证据。
- Docker Engine、PostgreSQL/pgvector、Nginx 和真实容器健康仍未验证。
- 既有 Starlette/httpx 弃用警告、Docker config 警告和 Windows symlink skip 保持不变。

## 下一条原子动作

开始 `M8-T5`，继续保持 offline：

1. 为 Manual、Agents SDK 与现有 LangGraph 建立同一组输入、工具、事件、结果和失败契约用例。
2. 在 `labs/langchain-agent/` 建立真实进入调用链的最小 LangChain 对照，不把依赖存在冒充完成。
3. 用同一计算工具和同一错误用例比较三条 Runtime；记录抽象收益、可观测性、取消、状态恢复和迁移成本。
4. 不修改 M8-T6 在线门；没有用户新的单次授权，不读取 Key、不运行真实模型。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_openai_agents_runtime backend.tests.test_runtime_contract backend.tests.test_run_coordinator -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

若实现提交 `ac24dda` 存在、SDK 专项 33 项和全量 231/1 证据可在 `V-20260716-006` 找到，不要重做 M8-T4；从 M8-T5 三运行时共同 fixture 开始。M8-T4 只有在线部分待 M8-T6 验证。
