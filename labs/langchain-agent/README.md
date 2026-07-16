# LangChain Agent 最小对照实验

本实验只处理 `M8-T5` 的框架对照：使用本地确定性 ChatModel 作为 Provider 边界，但实际调用 LangChain 1.3.13 的 `create_agent()`、`agent.invoke()` 和工具节点。它达到 E2 离线框架调用链证据，不是在线模型或 Provider 兼容证据，也不接入主 `RunCoordinator`。

## 运行

在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe -B .\labs\langchain-agent\demo.py
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_langchain_agent_lab -v
```

预期结果包含一次 `add_numbers` 调用、一个 `ToolMessage` 和最终答案 `计算结果是 5`。整个实验不读取 API Key、不访问网络、费用为 0。

## 真实调用链

```text
固定用户输入
  -> langchain.agents.create_agent
  -> agent.invoke
  -> _ToolCallingFakeModel 返回结构化 tool_call
  -> LangChain ToolNode 执行 @tool add_numbers
  -> ToolMessage 回到 Agent 图
  -> 固定模型返回最终答案
```

Fake 只替代外部模型响应；Agent 图、消息编排、工具绑定和工具执行均由 LangChain 的公开 API 完成。仅成功 import、构造模型或直接调用本地函数都不能替代本实验。

## 框架取舍报告

| 方案 | 主要收益 | 主要成本 | 适用边界 |
| --- | --- | --- | --- |
| Manual Loop | 控制流、重试和事件完全可见，最适合理解原理 | 每个工具循环、流式和错误分支都要手写 | 教学、确定性小循环、需要完全控制的核心链路 |
| OpenAI Agents SDK | Runner、工具、结构化输出和 Provider 流整合较完整 | SDK/Provider 数据形状需要严格适配，在线证据必须单独取得 | 以 OpenAI Agent Runtime 为主、希望少写通用循环的场景 |
| LangChain | `create_agent` 快速组合模型、工具和中间件，生态连接丰富 | 默认消息/事件不是本项目领域契约，接入主 Run 仍需适配和脱敏 | 快速集成工具与模型、验证生态组件；本任务只做独立对照 |
| LangGraph | 状态、节点、边和分支显式，便于扩展持久化、interrupt 和 resume | 状态 Schema、循环终止和恢复语义需要自行设计 | 长流程、审批、恢复和可观察控制流；持久能力由 M10 验收 |

本阶段保留 Manual、Agents SDK 和 LangGraph 的统一 `AgentRuntime`，不把 LangChain 接入主 Run。这样能比较抽象收益，同时避免在 M8 提前引入第二套主运行时事件映射；若未来需要主链 LangChain 适配，应先定义它对共享 Runtime 契约的实际增益。
