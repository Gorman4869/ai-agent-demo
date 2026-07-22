# 当前实施状态

- 更新时间：2026-07-22，Asia/Shanghai
- 计划版本：2.0
- 当前分支：`main`
- 最近已确认实现提交：`eba696b`
- 最近 M8-T4 文档闭环提交：`176d182`
- 本轮协议修改基线提交：`ed5ad9c`
- M8-T5 验证基线提交：`f83cbbc`
- M8-T5 实现提交：`e03f8d6`
- M8-T6 验证基线提交：`e03f8d6`
- M8-T6 实现提交：`bd6c09a`
- M8-T7 验证基线提交：`6e86e1e`
- M8-T7 课程文档提交：`ba7adf9`
- M9-T1 验证基线提交：`ba7adf9`；实现提交：`f8b59d2`
- M9-T2 验证基线提交：`f8b59d2`；实现提交：`40b1257`
- M9-T3 验证基线提交：`c3972b6`；实现提交：`5aba130`
- M9-T4 验证基线提交：`83a5234`；实现提交：`de8a63d`
- M9-T5 验证基线提交：`c820c7e`；实现提交：`a6ff518`
- M9-T6 验证基线提交：`19b5596`；课程提交：`fdeb9b5`
- M10-T1 验证基线提交：`c4d4efe`；实现提交：`b6dfa0b`
- M10-T2 验证基线提交：`cdc9436`；实现提交：`eba696b`
- M10-T3 验证基线提交：`545d5af`；实现提交：待本地提交固定
- 远程仓库：未配置
- 在线付费调用：未授权执行

## 当前任务

| 字段 | 内容 |
| --- | --- |
| 任务 ID | `M10-T4` |
| 状态 | `planned` |
| 目标 | 实现至少一种真实多 Agent 协作模式，并与单 Agent 对照质量、延迟、Token、失败率和复杂度；没有收益时保留单 Agent 结论 |
| 设计依据 | `docs/stages/10-durable-langgraph.md`、实施计划 M10-T4、M8-T4 Runtime/Agents SDK 证据、`ADR-0013` 与既有 AgentRuntime/ToolRegistry 契约 |
| 执行协议 | 课程优先、里程碑验收；见 `docs/continuity/course-delivery-playbook.md` |
| 当前修改 | M10-T3 已完成真实 `plan -> execute -> diagnose -> replan` StateGraph、版本化任务状态、错误码白名单、步骤/重规划预算、循环检测、审批阻断、已完成/结果未知副作用禁重放、同进程只读 checkpoint 恢复和 durable Coordinator/EventStore 纵切；默认 Container 未迁移 |
| 前置证据 | `V-20260722-001`、`ADR-0013`、`V-20260720-014`、`ADR-0012`、`ADR-0011` |
| 下一动作 | 只读审阅实施计划 M10-T4、现有 Agents SDK handoff 拒绝边界、LangGraph/ToolRegistry 角色隔离和 M8-T4 评测 fixture；先固定 manager-as-tools 或 handoff 的单一最小模式、角色契约和单 Agent 对照指标，不提前进入 M10-T5 |

## 里程碑状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| M0–M7 历史基线 | `code_complete` | 现有产物已落盘但审计后仅部分覆盖；未满足项由 M8–M14 接管，旧链暂不标记 `superseded` |
| C0 连续性基线 | `verified` | 计划基线 `6f8490a`；验证见 `V-20260716-001`、`V-20260716-002` |
| M8 真实模型与运行时 | `code_complete` | M8-T1、M8-T2、M8-T3、M8-T5、M8-T7 verified；M8-T4、M8-T6 code_complete；全量离线门通过，真实在线 E4 未授权，不能 accepted |
| M9 MCP Client 与 Skill | `verified` | M9-T1–M9-T6 verified，`KI-002` closed；本地 Python/Node STDIO、共同工具边界、只读 Skill/Runtime 上下文、课程材料和离线全量门均有证据，远程/生产 E4 不在本里程碑证据内 |
| M10 LangGraph 持久工作流 | `in_progress` | M10-T1–M10-T3 verified；checkpoint、服务端审批 resume、结构化动态计划、白名单重规划和副作用禁重放均有同进程 E3，M10-T4 多 Agent 对照待实现；进程重启仍属 M11 |
| M11 上下文、记忆与真实 RAG | `planned` | 依赖 M10 状态和 Store 协议 |
| M12 统一 Run 与实时 UI | `planned` | 依赖 M10、M11 |
| M13 生产工程闭环 | `planned` | 依赖 M12 主链路 |
| M14 高级 Agent 作品集 | `planned` | 依赖 M13 安全、观测和部署门禁 |

## 当前阻塞

- Docker Engine 未运行；不阻塞文档和离线测试，但阻塞容器、PostgreSQL/pgvector 和 Nginx 实际验收。
- 真实模型在线冒烟测试尚未获得单次执行授权；不阻塞离线实现与测试。
- 远程 Git 地址尚未提供；不阻塞本地提交。

## 未验证范围

- M10-T3 见 `V-20260722-001`：专项 14 项、定向 124 项和 M1 隔离 7 项通过；真实 `StateGraph`、共享 saver、durable Coordinator/EventStore 均执行。没有依赖、构建配置、默认 Container 或既有公共协议变化，因此未运行全仓构建门。
- M10-T3 planner/executor 为确定性离线 fixture；只证明 LangGraph 与领域契约的 E3，不证明真实模型规划质量、在线 Provider、Token/费用、生产延迟或容量。计划 step 的副作用/审批标记不是授权来源，真实工具仍必须经过 `ToolRegistry` 和 M10-T2 审批。
- M10-T3 的恢复仍使用同进程 `InMemorySaver`。只读 pending step 可恢复；pending 副作用结果未知时 fail closed 且不重放，但没有持久 ToolExecution 结果仲裁、lease、进程重启或跨崩溃恰好一次证据，这些由 M10-T5/M11 承接。
- M10-T3 只通过显式 Runtime 注入进入程序化 durable Run，没有迁移默认 Container、旧 HTTP/SSE 或 Agents SDK，也没有实现 M10-T4 多 Agent。
- M10-T2 见 `V-20260720-013`：审批/Store 专项 42 项、定向 85 项和统一全量门通过；最终后端 316 项通过、1 项既有 Windows symlink 能力测试跳过。全量沙箱首轮在 Vue `tsbuildinfo` 写入处 `EPERM`，竞态补丁前后相同脚本均经批准在沙箱外退出 0，失败与最终事实均保留。
- M10-T2 的 ApprovalRequest、原始工具参数、saver、RunStore 和 EventStore 均为同进程内存对象；只验证新 Runtime/Coordinator 实例复用共享对象后的恢复，不是操作系统进程重启、多进程或 PostgreSQL 证据。
- 正常批准、拒绝、过期、篡改和并发重复 resume 已证明 handler 最多执行一次；没有证明副作用完成但 terminal commit 结果未知时的跨崩溃恰好一次。持久 ToolExecution 幂等、lease 和恢复扫描由 M10-T5/M11 验收。
- M10-T2 没有迁移默认 Container、旧 HTTP/SSE 或 Agents SDK 审批路径；M12 才提供统一审批端点。其 M10-T3 重规划缺口已由 `V-20260722-001` 补齐，M10-T4 多 Agent 仍未实现。
- M10-T1 见 `V-20260720-011`：10 项 checkpoint 专项、73 项定向回归和统一全量门通过；后端 304 项中 303 项通过、1 项既有 Windows symlink 能力测试跳过。全量沙箱内首轮在 Vue `tsbuildinfo` 写入处 `EPERM`，相同脚本经批准在沙箱外退出 0，两次事实均保留。
- M10-T1 的 `InMemorySaver` 只验证同一进程中共享 saver 的跨 Runtime invocation 恢复；没有进程重启、多进程、PostgreSQL、加密、容量、清理或同 thread 跨进程并发证据，真正重启持久化仍由 M11 验收。
- M10-T1 的旧缺口中，interrupt、`Command(resume=...)`、审批状态机与正常/重复恢复已由 M10-T2 补齐，动态重规划已由 M10-T3 补齐；结果未知故障、多 Agent 和默认主链迁移仍未完成，`KI-004` 保持 mitigated。
- M9-T6 见 `V-20260720-009`：M9 聚焦 40 项全部通过；全量后端 294 项中 293 项通过、1 项既有 Windows symlink 能力测试跳过，Code Agent Demo、依赖、Vue、MCP TypeScript 与 Compose 配置门通过。
- 本轮全量首轮在后端、Code Agent 和依赖门通过后，因沙箱拒绝写 Vue `tsbuildinfo` 退出 1；相同完整脚本经工作区构建权限批准后在沙箱外退出 0。两次结果均保留，不能删除首次失败事实。
- 当前 Windows 环境仍无法为既有 Code Agent 测试创建真实 symlink；M9 Skill 的 `../`/嵌套逃逸由实际文件系统测试拒绝，symlink 拒绝只完成受控分支覆盖，不能描述为 OS 级实证。
- M9 的 Python/Node STDIO 证据最高为本地 E3；没有验证远程 transport、Linux/macOS、断线重连、健康恢复、调用幂等、副作用恢复或生产容量。MCP roots 当前也未实现，课程只验收其非 OS 安全边界解释。
- M9 固定离线评测真实执行 LangGraph Runtime，但使用确定性 fixture 模型。触发片段 3153 UTF-8 字节、启发式 789 Token；Provider usage 不可用、美元费用未知，不能描述为在线模型质量、真实 tokenizer 或账单，`KI-018` 保持 open。
- M9 没有实现 Skill 写接口、热加载、跨进程刷新、审批恢复或持久成本账本；这些不属于 M9-T6 课程验收。
- 学习者个人尚未完成 M9 题库、速查练习和费曼复述；工程 `verified` 不代替 `docs/progress.md` 的个人通关记录。
- M8-T7 课程验收见 `V-20260717-003`：Provider 故障命令 1 项、框架对照 12 项和全量后端 252 项通过，1 项既有 Windows symlink 跳过；Vue、MCP 与 Compose 配置门通过。
- M8-T6 工作区验证见 `V-20260717-001`，实现提交 `bd6c09a` 的恢复锚点见 `V-20260717-002`：12 项新增关键测试与 102 项定向回归通过，Fake Runtime 经实际 Store/Coordinator 纵切；这只是 E3，不是在线 Provider 证据。
- 没有用户新的单次授权，因此没有读取真实 Key、运行带 `-Authorized` 的脚本、访问模型服务或产生费用；Provider strict schema、真实 streaming、工具调用、usage、模型质量、费用和资源清理仍无 E4 证据。
- `KI-018` 的逐调用硬成本门、版本化定价源与持久 usage/cost 账本仍未实现；本次 operator-supplied 费用估算不得描述成账单事实。
- M8 课程和离线工程已 `code_complete`，但没有真实在线 E4，不能标记 `accepted`；学习者个人自测与费曼勾选仍只写 `docs/progress.md`。
- `KI-001` 保持 mitigated；`KI-016`、`KI-017`、`KI-018` 的生产缺口不变，后续分别由 M11-M13 承接。

## 恢复入口

若本轮中断，先阅读 `docs/continuity/course-delivery-playbook.md` 与 `docs/continuity/handoffs/2026-07-22-m10-t3-bounded-replanning.md`，再核对 `V-20260722-001`、`ADR-0013`、`V-20260720-014`、实施计划 M10-T4 和 `docs/stages/10-durable-langgraph.md`。若重规划专项 14 项、M1 7 项与连续性检查仍一致，不要重做 checkpoint、审批或动态重规划；下一步只读审阅 manager-as-tools/handoff 方案、角色工具边界和单 Agent 对照指标，不提前进入 M10-T5。没有用户新的单次授权，不得读取 Key 或执行真实模型。
