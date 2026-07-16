# 已知问题与风险台账

表中的 `blocker` 表示阻塞最终课程或对应里程碑验收，不表示阻塞当前 C0 文档工作。当前任务是否阻塞只以 `status.md` 为准。

| ID | 严重度 | 状态 | 归属 | 问题 | 关闭证据 |
| --- | --- | --- | --- | --- | --- |
| KI-001 | blocker | mitigated | M8 | M8-T4 已完成离线可验证的生产 OpenAI Agents SDK 适配器、流式工具调用、聚合 usage 与提供方错误闭环；真实线上流式与工具调用仍待 M8-T6 | M8-T4 离线契约与 M8-T6 经单独授权的线上流式/工具冒烟均通过 |
| KI-002 | blocker | open | M9 | 只有 MCP Server，没有 Client 发现和协议调用 | MCP STDIO 端到端测试通过 |
| KI-003 | high | open | M8 | LangChain 只有依赖，没有对照实验 | 对照实验、测试和取舍文档通过 |
| KI-004 | high | open | M10 | LangGraph 没有 checkpoint、interrupt、resume 和恢复测试 | 中断、审批、重启恢复测试通过 |
| KI-005 | high | open | M10–M11 | 上下文选择、记忆注入和动态重规划未进入主 Run | 长对话、记忆纠错与失败重规划评测通过 |
| KI-006 | high | open | M11 | pgvector 只有 Fake Connection，没有真实数据库、Embedding 与检索指标 | PostgreSQL/pgvector 集成和固定评测集通过 |
| KI-007 | high | open | M12 | SSE 在 Run 完成后回放；前端再次调用 Research API 覆盖答案 | 单 Run 真流式、续传和刷新恢复 E2E 通过 |
| KI-008 | high | open | M12–M13 | 缺少前端、MCP 协议和真实数据库自动化测试 | 分层测试进入统一验证和 CI |
| KI-009 | medium | open | M13 | Compose 仅配置通过，镜像和容器健康未验证 | Docker 构建、健康和 Nginx SSE 验证通过 |
| KI-010 | high | open | M14 | 浏览器审批未绑定完整 URL/计划，且缺少私网、DNS 与重定向防护 | 真实浏览器安全和 SSRF 测试通过 |
| KI-011 | high | open | M13–M14 | 代码 Agent 在截断前完整缓冲输出，超时未证明清理进程树 | 有界流式输出和进程树测试通过 |
| KI-012 | medium | closed | C0 | M1 文档零依赖命令、硬编码 Python 路径、测试数量与当前实现漂移 | `V-20260716-001`：删除硬编码路径和固定测试数；禁用 `site-packages` 后 7 项测试与 Demo 通过 |
| KI-013 | medium | open | M10 | 当前多 Agent 是确定性节点，没有真实角色、handoff 和单 Agent 对照 | 多 Agent 与单 Agent 固定评测完成 |
| KI-014 | medium | open | M11 | ConversationMemory 未接入 Run 且不持久化 | Agent 上下文读取、纠正、删除和重启恢复通过 |
| KI-015 | high | mitigated | M8–M11 | M8-T3 已用 StartCommit/TerminalCommit 固定一次提交协议，并在内存 Run→Event 锁对内原子发布；PostgreSQL 同事务、多进程和连接结果未知重试尚未验证 | M11 PostgreSQL 继承合同测试，并通过同事务 CAS、精确重放、连接中断和多进程终态竞争 |
| KI-016 | high | open | M11–M13 | Runtime 开始后的过程事件 Store 故障或进程退出会保留 running Run；当前选择 fail closed，不通知、不伪造终态，但尚无 lease、恢复扫描和安全重调度 | 持久 lease/heartbeat、RunRecoveryService、结果未知重试与重启恢复测试通过 |
| KI-017 | medium | open | M8–M13 | ManualRuntime 在同步 Loop 完成后回放过程事件；OpenAI Agents SDK 适配器在 M10 前拒绝审批、写入和其他副作用工具，但允许的只读同步 handler 仍通过 `asyncio.to_thread` 执行。Run 取消可丢弃结果，却不能硬停止底层线程，线程可能在终态后继续运行并占用默认 executor | 真实 async Runtime 成为主链；同步工具使用隔离且有界的 executor 或进程，并通过协作取消、工具超时、取消后清理与副作用测试 |
| KI-018 | high | open | M8–M13 | 当前 `max_turns` 仅粗略约束模型调用；SDK 聚合 request/input usage 只能在流结束后校验，可能超出一个请求，`max_cost_usd` 尚未计算或强制执行。`AsyncOpenAI` HTTP timeout 只约束提供方传输请求，不是覆盖模型、工具和清理阶段的整次 Run 硬墙钟；定价源与持久 usage/cost 账本尚未接入 | 接入逐调用 usage、可版本化定价源与持久账本；明确并测试预算超限余量，以 fail-closed 处理未知费用；模型、工具、总 Run 超时故障测试和 M8-T6 经单独授权的低预算线上证据通过 |

## 状态值

- `open`：问题已确认，尚未满足关闭证据。
- `mitigated`：主要风险已降低，但关闭证据不完整。
- `closed`：关闭证据已写入 verification log。
- `accepted`：用户明确接受残余风险。
