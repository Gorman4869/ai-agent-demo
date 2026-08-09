# 已知问题与风险台账

表中的 `blocker` 表示阻塞最终课程或对应里程碑验收，不表示阻塞当前 C0 文档工作。当前任务是否阻塞只以 `status.md` 为准。

| ID | 严重度 | 状态 | 归属 | 问题 | 关闭证据 |
| --- | --- | --- | --- | --- | --- |
| KI-001 | blocker | mitigated | M8 | M8-T4/M8-T5 已完成 SDK 适配与共享契约，M8-T6 已完成双重授权门和 E3 离线纵切，M8-T7 已完成课程材料与全量离线门；没有新的单次授权，真实线上流式、工具与 usage 仍未执行 | M8-T4/M8-T5 离线契约与 M8-T6 经单独授权的线上流式/工具冒烟均通过 |
| KI-002 | blocker | closed | M9 | M9-T1–T3 已完成真实 SDK 生命周期、可信工具映射，并对构建后的 TypeScript Knowledge Server 执行 initialize、list_tools、有效/无效 call_tool 与关闭；M9-T6 已完成课程和里程碑回归 | `V-20260720-003`：TypeScript MCP STDIO E2E；`V-20260720-009`：M9 40 项聚焦与全量离线门通过 |
| KI-003 | high | closed | M8 | LangChain 已通过 `create_agent().invoke()` 实际执行离线工具循环，并保留不接入主 Run 的取舍结论 | `V-20260716-008`：对照实验、零网络测试和取舍文档通过 |
| KI-004 | high | mitigated | M10–M12 | M10 已完成审批与同进程结果未知故障边界；M11-T1 已跨进程恢复 checkpoint、审批私有状态和 ToolExecution，并把 lease、scanner、quiesce、async façade 与默认 opt-in Container/FastAPI 生命周期接通。真实应用 fact 可跨两个 lifespan 恢复，但旧 Run HTTP 仍是内存 service | `V-20260722-009`、`V-20260803-001`、`V-20260803-003`、`V-20260803-005`、`V-20260808-002`、`V-20260808-005`、`V-20260808-007`、`V-20260808-009`、`V-20260808-013`；M12 统一 durable Run API 的进程重启/续传证据通过后关闭 |
| KI-005 | high | mitigated | M10–M12 | M10-T3 已把有界动态计划、失败诊断、白名单重规划、预算/循环停止和副作用禁重放接入可注入的 durable Coordinator Run；M11-T1 已迁移默认 opt-in PostgreSQL Container，但旧 Run/ContextAssembler 的上下文选择和记忆注入仍未进入统一主链 | `V-20260722-001`、`V-20260808-013`；M11 长对话、记忆纠错与 M12 统一 Run 上下文评测通过后关闭 |
| KI-006 | high | mitigated | M11 | M11-T2 已完成真实 pgvector schema/CRUD/seed；M11-T3 已完成确定性离线 Embedding、批次/维度元数据、版本化进程内缓存、显式暂时性批次 retry，以及在线 SDK Adapter/Settings 的离线协议验证。真实在线 Provider、持久/跨进程缓存与固定检索指标仍未完成 | `V-20260809-001`：真实 pgvector；`V-20260809-003`：离线 Embedding 批次 E3；`V-20260809-004`：缓存/retry E3；`V-20260809-006`：真实 SDK `MockTransport` Adapter 与完整离线门；最终关闭仍需 M11-T6 固定评测集，在线 E4 由 M11-T7 独立记录 |
| KI-007 | high | open | M12 | SSE 在 Run 完成后回放；前端再次调用 Research API 覆盖答案 | 单 Run 真流式、续传和刷新恢复 E2E 通过 |
| KI-008 | high | open | M12–M13 | M9-T3 已补 TypeScript MCP STDIO 协议自动化；仍缺前端和真实数据库自动化测试及统一分层门 | 分层测试进入统一验证和 CI |
| KI-009 | medium | open | M13 | Compose 仅配置通过，镜像和容器健康未验证 | Docker 构建、健康和 Nginx SSE 验证通过 |
| KI-010 | high | open | M14 | 浏览器审批未绑定完整 URL/计划，且缺少私网、DNS 与重定向防护 | 真实浏览器安全和 SSRF 测试通过 |
| KI-011 | high | open | M13–M14 | 代码 Agent 在截断前完整缓冲输出，超时未证明清理进程树 | 有界流式输出和进程树测试通过 |
| KI-012 | medium | closed | C0 | M1 文档零依赖命令、硬编码 Python 路径、测试数量与当前实现漂移 | `V-20260716-001`：删除硬编码路径和固定测试数；禁用 `site-packages` 后 7 项测试与 Demo 通过 |
| KI-013 | medium | closed | M10 | M10-T4 已通过公开 `Agent.as_tool()`/`Runner.run()` 实现 researcher、writer、reviewer manager-as-tools，并与同工具单 Agent 完成固定质量、失败率、本地延迟、fixture usage 和复杂度对照；无质量收益，保留单 Agent | `V-20260722-003`：14 项专项与 93 项定向回归通过，固定 3 例对照完成 |
| KI-014 | medium | mitigated | M11 | M11-T1 已让默认 opt-in Container 和记忆 HTTP 使用 PostgreSQL async façade，并由两个完整 FastAPI lifespan 先写后删同一长期 fact；旧 Run/ContextAssembler 尚未读取该持久记忆 | `V-20260803-001`、`V-20260808-013`；Agent 上下文读取、纠正、删除和统一 Run 重启恢复通过后关闭 |
| KI-015 | high | mitigated | M8–M11 | M8-T3 已用 StartCommit/TerminalCommit 固定一次提交协议。M11-T1 首个纵切的 PostgreSQL Run/Event 已证明生命周期同事务与并发终态 CAS；第三纵切又证明 ToolExecution terminal commit 后进程异常退出可由新进程读取并幂等 replay。Run/Event 自身的连接结果未知、多进程终态竞争及其与 ToolExecution 的跨域一致性仍未验证 | `V-20260722-009`、`V-20260803-003`；后续再通过 Run/Event 连接中断结果仲裁和多进程终态竞争后关闭 |
| KI-016 | high | mitigated | M11–M13 | M11-T1 已把持久 lease、scanner、Coordinator/supervisor/composition 注入默认 opt-in Container；共享 ASGI/command admission 覆盖完整响应 body，并固定 drain 后再关闭 composition/MCP。仍缺统一 durable HTTP 命令的硬进程中断与生产级故障注入 | `V-20260803-005`、`V-20260808-002`、`V-20260808-005`、`V-20260808-007`、`V-20260808-009`、`V-20260808-013`；M12/M13 的统一 API、硬进程中断和部署故障测试通过后关闭 |
| KI-017 | medium | open | M8–M13 | ManualRuntime 在同步 Loop 完成后回放过程事件；OpenAI Agents SDK 适配器尚未实现 M10 审批暂停协议，仍拒绝审批、写入和其他副作用工具，但允许的只读同步 handler 仍通过 `asyncio.to_thread` 执行。Run 取消可丢弃结果，却不能硬停止底层线程，线程可能在终态后继续运行并占用默认 executor | 真实 async Runtime 成为主链；同步工具使用隔离且有界的 executor 或进程，并通过协作取消、工具超时、取消后清理与副作用测试 |
| KI-018 | high | open | M8–M13 | 当前 `max_turns` 仅粗略约束模型调用；SDK 聚合 request/input usage 只能在流结束后校验，可能超出一个请求，`max_cost_usd` 尚未计算或强制执行。M9-T5 只增加明确标注的 Skill 上下文字节与 `ceil(bytes / 4)` Token 启发式，不是 Provider usage 或费用。`AsyncOpenAI` HTTP timeout 只约束提供方传输请求，不是覆盖模型、工具和清理阶段的整次 Run 硬墙钟；定价源与持久 usage/cost 账本尚未接入 | 接入逐调用 usage、可版本化定价源与持久账本；明确并测试预算超限余量，以 fail-closed 处理未知费用；模型、工具、总 Run 超时故障测试和 M8-T6 经单独授权的低预算线上证据通过 |
| KI-019 | low | closed | C0 | M8-T5 实现提交 `e03f8d6` 已由 `V-20260717-001` 和 M8-T6 handoff 记录，动态 status 同步更新 | 新 verification 或 handoff 记录 `e03f8d6`，并更新动态 status 后通过连续性检查 |
| KI-020 | low | closed | M10 | Stage 10 的 20% 关键知识表曾把“多 Agent 取舍”误映射到 M10-T5，与实施计划 M10-T4 和实际验证冲突；M10-T5 故障矩阵复审时已修正为 M10-T4 | `V-20260722-005`：Stage 映射修正并通过连续性检查 |
| KI-021 | low | closed | M10 | M10-T6 恢复审计发现三处动态文档仍停在 M10-T4/T5 提交前措辞，且实施计划“关闭 KI-004/重启恢复”与 accepted ADR 的 M11 PostgreSQL 真重启边界冲突；现已修正动态状态和里程碑措辞，旧 handoff 保持不可变并由新交接澄清 | `V-20260722-007`：课程链接、52 个稳定任务/72 个 Markdown 连续性与完整离线门通过；`KI-004` 正确保留为 mitigated |
| KI-022 | low | closed | M11 | M11-T1 第二纵切恢复审计发现 `status.md` 顶部“最近已确认实现提交”仍为 M10 的 `1e332f3`，但 Git、M11 专项字段、handoff 和 `V-20260722-010` 均已固定首个 PostgreSQL 纵切实现提交 `8c6b011`；动态 status 已修正 | `V-20260803-001`：首个纵切 35 项恢复、第二纵切 53 项 PostgreSQL、连续性与 Git 事实一致 |
| KI-023 | high | closed | M11–M12 | `bffeab7` 提供共享有界 bridge 与 async façade；`be2c818` 让默认 opt-in Container、memory HTTP 和 application approval 使用 façade，并用共享 ASGI/command admission 固定完整 response drain、composition 与 MCP 关闭顺序 | `V-20260808-011`、`V-20260808-013`：queued/running timeout、取消、pool 耗尽、application startup rollback、streaming drain、真实 PostgreSQL 重启和完整门通过；显式同步 compatibility 调用仍是调用方所有边界 |
| KI-024 | low | closed | M1/M11 连续性 | M11 第四纵切 handoff 固定的 M1 恢复数量为当时的 7 项；后续学习者提交 `beefc1a` 新增 3 项且未修改 M11 lease/Coordinator，当前同一隔离命令实际通过 10 项。历史 handoff 保持不可变，新恢复记录更新当前基线 | `V-20260808-001`：PostgreSQL 76 项、M1 10 项和连续性 52/80 通过 |

## 状态值

- `open`：问题已确认，尚未满足关闭证据。
- `mitigated`：主要风险已降低，但关闭证据不完整。
- `closed`：关闭证据已写入 verification log。
- `accepted`：用户明确接受残余风险。
