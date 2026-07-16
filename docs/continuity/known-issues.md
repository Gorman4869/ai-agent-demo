# 已知问题与风险台账

表中的 `blocker` 表示阻塞最终课程或对应里程碑验收，不表示阻塞当前 C0 文档工作。当前任务是否阻塞只以 `status.md` 为准。

| ID | 严重度 | 状态 | 归属 | 问题 | 关闭证据 |
| --- | --- | --- | --- | --- | --- |
| KI-001 | blocker | open | M8 | 没有真实 LLM Runner、流式工具调用、usage 和提供方错误闭环 | M8 在线冒烟与离线契约均通过 |
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

## 状态值

- `open`：问题已确认，尚未满足关闭证据。
- `mitigated`：主要风险已降低，但关闭证据不完整。
- `closed`：关闭证据已写入 verification log。
- `accepted`：用户明确接受残余风险。
