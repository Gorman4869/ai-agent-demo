# 当前实施状态

- 更新时间：2026-08-08，Asia/Shanghai
- 计划版本：2.0
- 当前分支：`main`
- 最近已确认实现提交：`be2c818`
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
- M10-T3 验证基线提交：`545d5af`；实现提交：`e27a8ef`
- M10-T4 验证基线提交：`ae9e3aa`；实现提交：`abdc409`
- M10-T5 验证基线提交：`7538fb4`；实现提交：`1e332f3`
- M10-T6 验证基线提交：`07741db`；课程提交：`1766875`
- M11-T1 首个纵切验证基线提交：`8af705b`；实现提交：`8c6b011`
- M11-T1 第二纵切验证基线提交：`bf875be`；实现提交：`cb4fd52`
- M11-T1 第三纵切验证基线提交：`bb36875`；实现提交：`0de735d`
- M11-T1 第四纵切验证基线提交：`1219737`；实现提交：`1fc55fb`
- M11-T1 第五纵切验证基线提交：`beefc1a`；实现提交：`003c7be`
- M11-T1 第六纵切验证基线提交：`8297ac0`；实现提交：`e63d718`
- M11-T1 第七纵切验证基线提交：`e6e53dd`；实现提交：`1d4386c`
- M11-T1 第八纵切验证基线提交：`acd4f40`；实现提交：`2e94640`
- M11-T1 第九纵切验证基线提交：`0c30a28`；实现提交：`bffeab7`
- M11-T1 第十纵切验证基线提交：`1e867bc`；实现提交：`be2c818`
- 远程仓库：未配置
- 在线付费调用：未授权执行

## 当前任务

| 字段 | 内容 |
| --- | --- |
| 任务 ID | `M11-T2` |
| 状态 | `planned` |
| 目标 | 在真实 PostgreSQL/pgvector 中完成文档、切片、向量维度、索引、增删改与相似度检索闭环 |
| 设计依据 | 实施计划 M11-T2、`ADR-0001`、M11-T1 已验收 persistence/application lifecycle，以及现有 `PgVectorKnowledgeBase` 边界 |
| 执行协议 | 课程优先、里程碑验收；见 `docs/continuity/course-delivery-playbook.md` |
| 当前修改 | M11-T1 已由第十纵切完成验收：显式 persistence gate、PostgreSQL async Container open、FastAPI lifespan、完整 ASGI/command admission、Approval/Memory async façade 与 startup/shutdown rollback/顺序；实现提交 `be2c818` |
| 前置证据 | `V-20260808-013`、`ADR-0022`、M11-T1 前九纵切 verification/ADR，以及实现提交 `be2c818` |
| 下一动作 | 进入 M11-T2 的首个 A 类设计/实现纵切：先审计现有 `PgVectorKnowledgeBase`、PostgreSQL image/extension 与表/索引契约，新增 ADR 后只实现真实 pgvector migration + 最小 CRUD/相似度检索测试；默认离线、不得安装依赖或执行在线 Embedding |

## 里程碑状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| M0–M7 历史基线 | `code_complete` | 现有产物已落盘但审计后仅部分覆盖；未满足项由 M8–M14 接管，旧链暂不标记 `superseded` |
| C0 连续性基线 | `verified` | 计划基线 `6f8490a`；验证见 `V-20260716-001`、`V-20260716-002` |
| M8 真实模型与运行时 | `code_complete` | M8-T1、M8-T2、M8-T3、M8-T5、M8-T7 verified；M8-T4、M8-T6 code_complete；全量离线门通过，真实在线 E4 未授权，不能 accepted |
| M9 MCP Client 与 Skill | `verified` | M9-T1–M9-T6 verified，`KI-002` closed；本地 Python/Node STDIO、共同工具边界、只读 Skill/Runtime 上下文、课程材料和离线全量门均有证据，远程/生产 E4 不在本里程碑证据内 |
| M10 LangGraph 持久工作流 | `verified` | M10-T1–M10-T6 verified；checkpoint、服务端审批 resume、结构化重规划、真实 manager-as-tools/单 Agent 对照、10 场景故障矩阵、课程材料与完整离线门均有证据；真正进程重启、PostgreSQL 和持久 ToolExecution 仍属 M11，`KI-004` 保持 mitigated |
| M11 上下文、记忆与真实 RAG | `in_progress` | M11-T1 十个 PostgreSQL 纵切已 `verified`：Store/checkpoint、ToolExecution、lease/recovery、composition/quiesce、sync bridge 与默认 opt-in Container/FastAPI application lifecycle 均有真实数据库和完整门证据；M11-T2 以后任务尚未完成 |
| M12 统一 Run 与实时 UI | `planned` | 依赖 M10、M11 |
| M13 生产工程闭环 | `planned` | 依赖 M12 主链路 |
| M14 高级 Agent 作品集 | `planned` | 依赖 M13 安全、观测和部署门禁 |

## 当前阻塞

- Docker Engine 与本地 PostgreSQL 17.10 测试容器在本轮恢复后健康运行；这不是持续可用或生产部署证据，后续会话仍须先检查实际状态。
- 真实模型在线冒烟测试尚未获得单次执行授权；不阻塞离线实现与测试。
- 远程 Git 地址尚未提供；不阻塞本地提交。

## 未验证范围

- M11-T1 第十纵切见 `V-20260808-013`：真实 PostgreSQL 91 项、受影响定向 98 项、最终完整门后端 463 项通过且 1 项既有 Windows symlink 跳过，M1 隔离 10 项通过；实现提交为 `be2c818`，提交后 63 项默认路径与 2 项真实 PostgreSQL application 专项再次通过。
- 默认仍是 memory；只有显式 `AI_AGENT_PERSISTENCE=postgres` 才在 FastAPI lifespan 打开数据库。旧 Run HTTP/SSE 仍是 legacy `InMemoryRunService` 且不双写，统一 durable Run/审批/取消/事件 API 属于 M12。
- application async 路径只使用 Approval/Memory façade，并由共享 ASGI/command admission 排空；显式同步 compatibility 调用仍不受 bridge 追踪。Windows PostgreSQL host 还需在 loop 创建前选择 Selector policy；本地 trust/tmpfs 证据不是生产部署或外部副作用 exactly-once。
- 完整门首次遇到 TypeScript MCP E2E 5 秒启动抖动，单独 4 项立即通过；第二次在 Vue tsbuildinfo 写入处遇到沙箱 `TS5033/EPERM`。相同门获工作区写权限后通过，最终 ASGI admission 复审后再次完整通过，失败与最终事实均记录在 `V-20260808-013`。
- M11-T1 第九纵切见 `V-20260808-011`：async bridge 单元 9 项、真实 PostgreSQL 89 项、受影响 Approval/Memory/quiesce/composition/Runtime 56 项和 M1 隔离 10 项通过；实现提交为 `bffeab7`，提交后新增单元与真实数据库专项 12 项再次通过。
- 第九纵切没有修改依赖、migration、同步 Store Protocol、默认 Container/HTTP 或跨前后端契约，也不是里程碑验收/发布门；真实 PostgreSQL 与定向回归已覆盖共享 persistence 兼容性，因此没有重复运行 `scripts/verify.ps1`、Vue、MCP TypeScript 或 Compose 全量门。第五纵切完整门继续引用 `V-20260808-002`/`003`。
- 第九纵切的 async façade 调用由共享 bridge 追踪；queued timeout 可取消未开始操作，running timeout/cancel 不能硬取消线程且结果可能未知，不得自动重试。直接同步 compatibility 调用不受 bridge 追踪。其当时缺少的默认 Container/FastAPI 接线已由 `V-20260808-013` 完成，`KI-023` 已关闭。
- M11-T1 第八纵切见 `V-20260808-009`：quiesce+composition 单元 18 项、真实 PostgreSQL 86 项、核心 composition/Run/Store/Coordinator/recovery/LangGraph 164 项、API/Container/SDK 68 项和 M1 隔离 10 项通过；实现提交为 `2e94640`。
- 第八纵切没有修改依赖、migration、Store Protocol、默认 HTTP 或跨前后端契约，也不是里程碑验收/发布门；核心和 API/Container 定向回归已覆盖共享 Coordinator 兼容性，因此没有重复运行 `scripts/verify.ps1`、Vue、MCP TypeScript 或 Compose 全量门。第五纵切完整门继续引用 `V-20260808-002`/`003`。
- quiesce timeout 只是自然完成宽限期；非协作 Runtime 可能让清理超过 timeout。第八纵切当时只覆盖 execute/resume admission；`V-20260808-011` 已补同步 Store async 隔离，`V-20260808-013` 已补默认 HTTP/command admission 与 lifespan。硬线程终止和外部副作用 exactly-once 仍未提供。
- M11-T1 第七纵切见 `V-20260808-007`：composition 生命周期 9 项、真实 PostgreSQL 84 项、核心 composition/Run/Store/Coordinator/recovery/LangGraph 155 项和 M1 隔离 10 项通过；不同 PID 的新 composition 自动收敛旧 holder 的 `run_orphaned`，实现提交为 `1d4386c`。
- 第七纵切没有修改依赖、migration、公共 Store Protocol、默认 Container/HTTP 或跨前后端契约，也不是里程碑验收/发布门，因此按课程交付协议没有重复运行 `scripts/verify.ps1`、Vue、MCP TypeScript 或 Compose 全量门；第五纵切完整门证据继续引用 `V-20260808-002`/`003`。
- 第七纵切结束时 composition close 仍要求调用方自行停止 execute/resume；`V-20260808-009` 已补 Coordinator drain，`V-20260808-011` 已补同步 Store async 边界，`V-20260808-013` 已补默认 Container/FastAPI lifespan。强制终止 Runtime 仍不在当前合同内。
- M11-T1 第六纵切见 `V-20260808-005`：recovery/supervisor 14 项、真实 PostgreSQL 83 项、核心 Run/Store/Coordinator/recovery/LangGraph 154 项和 M1 隔离 10 项通过；真实 supervisor 自动 claim、提交 `run_orphaned`、release 并关闭。
- 第六纵切没有修改依赖、migration、公共 Store Protocol、默认 composition、HTTP 或跨前后端契约，也不是里程碑验收/发布门，因此按课程交付协议没有重复运行 `scripts/verify.ps1`、Vue、MCP TypeScript 或 Compose 全量门；第五纵切完整门证据继续引用 `V-20260808-002`/`003`。
- 第六纵切当时 supervisor 仍需调用方显式 start/close；后续 `V-20260808-007` 至 `013` 已补 composition、quiesce、bridge 与默认 lifespan。shutdown 中断后已提交状态和陈旧 lease 仍依赖下一应用生命周期收敛；这不是任意网络中断点立即清理或外部副作用 exactly-once 证据。
- M11-T1 第五纵切见 `V-20260808-002`/`003`：内存 Coordinator/lease 41 项、真实 PostgreSQL 82 项、核心 Run/Store/Coordinator/LangGraph 134 项、API/Container/SDK 68 项和 M1 隔离 10 项通过；公共 Store 契约变化触发完整门，后端 410 项通过、1 项既有 Windows symlink 跳过，Code Agent、依赖、Vue、MCP TypeScript 和 Compose 配置通过。
- 第五纵切的真实 PostgreSQL Coordinator 已证明 queued reservation 早于 `run.started`、heartbeat version 推进、terminal release；数据库强制过期时 Runtime 被取消且旧执行者不提交终态，显式 scanner 随后把 Run 收敛为 `run_orphaned`。`V-20260808-013` 已把同一 composition 接入默认 opt-in 应用，但仍不证明外部副作用 exactly-once。
- 第五纵切当时没有默认 Container/HTTP、lifespan scanner、统一 composition 或同步 Approval/Memory async 线程边界；后续第六至第十纵切已补 supervisor/composition/quiesce/async bridge 与默认 application lifecycle。release 失败后的陈旧 lease 仍依赖 scanner 收敛，统一 durable HTTP 留给 M12。
- 第五纵切完整门沙箱首轮在后端 410 项、Code Agent 和依赖通过后因 Vue `tsconfig.app.tsbuildinfo` 写入 `TS5033`/`EPERM` 退出 1；相同脚本获工作区构建权限后退出 0。后端仍有一条既有 `StarletteDeprecationWarning` 和一项 Windows symlink 能力跳过。
- M11-T1 第四纵切见 `V-20260803-005`：内存 lease/recovery 13 项、完整真实 PostgreSQL 76 项、受影响 Run/Store/Coordinator/LangGraph 131 项和 M1 隔离 7 项通过；最终完整门后端 394 项通过、1 项既有 Windows symlink 跳过，Code Agent、依赖、Vue、MCP TypeScript 和 Compose 配置通过。
- 四个 PID 不同的 probe 进程证明持有 execution lease 的进程以 17 退出后，两个 scanner 竞争同一过期记录时只有一个恢复者；审计进程读取到 running ToolExecution=unknown、pending=cancelled、Run=`run_orphaned` 且租约已释放。后续默认 application lifecycle 已调度同一 scanner，但该 probe 仍只证明本地数据库仲裁，不证明外部副作用 exactly-once。
- PostgreSQL 只保存 lease token SHA-256，过期判断使用数据库时钟；heartbeat/release 绑定未过期 token/version 和 Run 状态。ToolExecution、Run/Event 和 lease release 仍是分离事务，真实触发器故障证明中间状态可由下一次扫描收敛，但收敛前可能短暂观察到工具已终态而 Run 仍 running。
- 第四纵切当时没有 Coordinator heartbeat、supervisor、统一 composition 或同步 Approval/Memory async 边界；后续第五至第十纵切已补这些能力及默认 opt-in Container/lifespan。生产数据库能力和 M11-T2 pgvector 仍未完成；`KI-023` 已关闭，`KI-004`、`KI-016` 保持 mitigated。
- 第四纵切完整门沙箱首轮在后端 393 项、Code Agent 和依赖通过后因 Vue `tsconfig.app.tsbuildinfo` 写入 `TS5033`/`EPERM` 退出 1；相同脚本获批后退出 0。锁序复审补两项合同后，最终完整门以后端 394 项再次退出 0；仍有一条既有 `StarletteDeprecationWarning`。
- M11-T1 第三纵切见 `V-20260803-003`：内存/PostgreSQL 各 10 项 ToolExecution 共同合同、完整 PostgreSQL 65 项、受影响 Run/Coordinator/LangGraph 108 项、M1 隔离 7 项通过；完整门后端 381 项通过、1 项既有 Windows symlink 跳过，Code Agent、依赖、Vue、MCP TypeScript 和 Compose 配置通过。
- 三个 PID 不同的 probe 进程证明 terminal commit 后进程以 17 退出且未发送完成确认时，新进程能读取 completed 并按幂等键 replay；同一批中遗留 running 记录只能显式转为 terminal unknown。它证明本地数据库仲裁，不证明外部工具副作用与数据库 exactly-once。
- `0003` 只保存参数/幂等键/结果摘要和有界安全摘要；没有原始参数、原始 key 或原始结果。ToolExecution 与 Run/Event/checkpoint、同步 Approval pool 和外部系统不共享事务，尚无 lease、heartbeat、自动恢复扫描、业务补偿或默认主链接线。
- 第三纵切完整门沙箱首轮在后端 381 项、Code Agent 和依赖通过后因 Vue `tsconfig.app.tsbuildinfo` 写入 `TS5033`/`EPERM` 退出 1；相同脚本获批后退出 0。后端仍有一条既有 `StarletteDeprecationWarning`。
- M11-T1 第二纵切见 `V-20260803-001`：真实 PostgreSQL Approval/Memory/Run/Event/checkpointer 集成 53 项、受影响 Runtime/API/Container 回归 80 项、M1 隔离 7 项通过；最终完整门后端 371 项通过、1 项既有 Windows symlink 能力跳过，Code Agent、依赖、Vue、MCP TypeScript 和 Compose 配置通过。
- 第二纵切的两个 PID probe 已恢复私有审批参数、完成决议与单次 grant 消费，并恢复消息和长期事实；probe 只输出 ID、计数和布尔结果。`V-20260808-013` 已把 async façade 注入默认 opt-in Container 和记忆 HTTP，但 M10 审批 Runtime/ContextAssembler 与统一 Run API 尚未迁移。
- 为兼容既有同步 ToolRegistry，PostgreSQL Approval/Memory 使用共享同步 pool，Run/Event/checkpoint 继续使用异步 pool；它们共享 DSN 和生命周期但不共享事务。`V-20260808-011` 已验证 bridge，`V-20260808-013` 已完成默认 application façade 接线；跨 pool 原子性与 exactly-once 仍未验证。
- `0002` 私有参数和记忆为本地课程数据库中的明文 JSON/text；没有应用层加密、生产 TLS、备份、密钥管理或数据保留证据。默认 Container 已由第十纵切接入，M11-T1 为 `verified`；M11-T2 pgvector 尚未实现。
- 第二纵切完整门沙箱首轮在当时后端 370 项、受控 Code Agent 和依赖检查通过后，因 Vue `tsconfig.app.tsbuildinfo` 写入 `TS5033`/`EPERM` 退出 1；相同脚本获批后退出 0。聚焦复审补一项授权伪造合同后，最终完整门以后端 371 项再次退出 0。后端仍有一条既有 `StarletteDeprecationWarning`。
- M11-T1 首个纵切见 `V-20260722-009`：真实 PostgreSQL migration/Run/Event/checkpointer 集成 35 项、受影响 Store/Coordinator/LangGraph 回归 71 项、M1 隔离 7 项和完整发布门通过；发布门后端 354 项通过、1 项既有 Windows symlink 能力跳过。
- 首个纵切的两个 PID 已通过官方 AsyncPostgresSaver 恢复同一可信 thread，但没有验证数据库容器重启、跨主机、同 thread 并发写、多进程终态竞争或生产容量。后续九个纵切已补其余 Store、lease/recovery 与默认 application lifecycle；统一 durable HTTP 仍由 M12 承接。
- 本地 Compose 使用仅绑定 `127.0.0.1` 的 trust/tmpfs 测试实例；它不是生产鉴权、持久卷、备份、TLS、高可用或灾备证据。没有读取 Key、调用在线模型或产生付费调用。
- M11 发布门沙箱首轮在后端 354 项、受控代码 Agent 和依赖检查通过后，因拒绝写入 Vue `tsconfig.app.tsbuildinfo` 以 `TS5033`/`EPERM` 退出 1；相同脚本经工作区构建权限批准后完整退出 0。后端仍有一条既有 `StarletteDeprecationWarning`。
- M10-T6 见 `V-20260722-007`：M10 聚焦 58 项通过；完整离线门的后端 354 项通过、1 项因 Windows 符号链接能力跳过，受控代码 Agent、依赖检查、Vue 生产构建、MCP TypeScript 构建和 Compose 配置均通过。
- 完整门沙箱首轮在后端 354 项、受控代码 Agent 和依赖检查通过后，因拒绝写入 Vue `tsconfig.app.tsbuildinfo` 以 `EPERM` 退出 1；相同脚本经工作区构建权限批准后退出 0。首次失败和最终通过均保留，另有一条既有 `StarletteDeprecationWarning`。
- M10 工程里程碑已 `verified`，但所有模型与多 Agent 结论仍来自确定性离线 fixture；没有在线 Provider、真实 Token/账单、生产质量或容量证据。真正操作系统进程重启、PostgreSQL checkpointer、持久 ToolExecution、lease 和恢复扫描由 M11 承接。
- 学习者个人尚未完成 M10 题库、速查练习和费曼复述；工程 `verified` 不代替 `docs/progress.md` 的个人通关记录。
- M10-T5 见 `V-20260722-005`：新增故障矩阵 10 项、M10-T1–T5/Coordinator/Store/ToolRegistry 定向 123 项和 M1 隔离 7 项通过；真实 `StateGraph`、故障 saver、共享内存 saver、RunCoordinator/EventStore 和 ToolRegistry 均执行。
- 结果未知审批路径只证明同一进程中 grant 已消费后，新 Runtime 不重放 handler并返回 `side_effect_resume_unsafe`/`approval.stopped`；重规划路径产生同类终态和 `plan.stopped`。这不是跨进程 exactly-once、PostgreSQL、持久 ToolExecution、lease 或恢复扫描证据。
- M10-T5 未修改依赖、锁文件、默认 Container、公共 Runtime/Store Protocol、HTTP/SSE 或前端，因此未运行全仓 `scripts/verify.ps1`；M10-T6 里程碑验收再执行计划要求的完整门。
- M10-T4 见 `V-20260722-003`：公开 `Runner.run()` 实际执行 manager 和三个 `Agent.as_tool()` specialist，14 项专项、93 项 M8/M10 定向回归和 M1 隔离 7 项通过。3 个固定案例中两组质量均为 1.0、失败率均为 0；无收益时保留单 Agent，`KI-013` closed。
- 多 Agent 每例 9 次 request/108 Token、单 Agent 每例 3 次/36 Token均来自确定性 Model 的 SDK aggregate usage；本地延迟包含固定 1 ms/调用的 fixture delay 和 SDK 开销。它们不是 Provider tokenizer、账单、线上质量、费用或生产容量证据。
- M10-T4 是显式离线评测，不接入默认 Container、`RunCoordinator`、HTTP/SSE 或现有 `OpenAIAgentsRuntime`；后者对 handoff event 的 fail-closed 契约保持不变。评测进程安装无 exporter 的禁用 Trace provider，不能嵌入应用进程或覆盖应用观测配置。
- M10-T3 见 `V-20260722-001`：专项 14 项、定向 124 项和 M1 隔离 7 项通过；真实 `StateGraph`、共享 saver、durable Coordinator/EventStore 均执行。没有依赖、构建配置、默认 Container 或既有公共协议变化，因此未运行全仓构建门。
- M10-T3 planner/executor 为确定性离线 fixture；只证明 LangGraph 与领域契约的 E3，不证明真实模型规划质量、在线 Provider、Token/费用、生产延迟或容量。计划 step 的副作用/审批标记不是授权来源，真实工具仍必须经过 `ToolRegistry` 和 M10-T2 审批。
- M10-T3 的恢复使用同进程 `InMemorySaver`；M10-T5 的该组证据本身没有持久 ToolExecution、进程重启或跨崩溃仲裁。M11 的 `V-20260803-003` 已补持久 ToolExecution 与进程异常退出恢复；lease、自动扫描和跨外部系统 exactly-once 仍未实现。
- M10-T3 只通过显式 Runtime 注入进入程序化 durable Run，没有迁移默认 Container、旧 HTTP/SSE 或 Agents SDK；M10-T4 的独立多 Agent 对照没有改变该边界。
- M10-T2 见 `V-20260720-013`：审批/Store 专项 42 项、定向 85 项和统一全量门通过；最终后端 316 项通过、1 项既有 Windows symlink 能力测试跳过。全量沙箱首轮在 Vue `tsbuildinfo` 写入处 `EPERM`，竞态补丁前后相同脚本均经批准在沙箱外退出 0，失败与最终事实均保留。
- M10-T2 的 ApprovalRequest、原始工具参数、saver、RunStore 和 EventStore 均为同进程内存对象；只验证新 Runtime/Coordinator 实例复用共享对象后的恢复，不是操作系统进程重启、多进程或 PostgreSQL 证据。
- 正常批准、拒绝、过期、篡改和并发重复 resume 已证明 handler 最多执行一次；M10-T5 进一步证明同进程 checkpoint 写失败后的恢复不会重放已消费 handler。跨崩溃 exactly-once、持久 ToolExecution、lease 和恢复扫描仍由 M11 验收。
- M10-T2 没有迁移默认 Container、旧 HTTP/SSE 或 Agents SDK 审批路径；M12 才提供统一审批端点。其 M10-T3 重规划和 M10-T4 多 Agent 对照缺口已分别由 `V-20260722-001`、`V-20260722-003` 补齐。
- M10-T1 见 `V-20260720-011`：10 项 checkpoint 专项、73 项定向回归和统一全量门通过；后端 304 项中 303 项通过、1 项既有 Windows symlink 能力测试跳过。全量沙箱内首轮在 Vue `tsbuildinfo` 写入处 `EPERM`，相同脚本经批准在沙箱外退出 0，两次事实均保留。
- M10-T1 的 `InMemorySaver` 只验证同一进程中共享 saver 的跨 Runtime invocation 恢复；没有进程重启、多进程、PostgreSQL、加密、容量、清理或同 thread 跨进程并发证据，真正重启持久化仍由 M11 验收。
- M10-T1 的旧缺口中，interrupt、`Command(resume=...)`、审批状态机与正常/重复恢复已由 M10-T2 补齐，动态重规划已由 M10-T3 补齐，多 Agent 对照已由 M10-T4 补齐，结果未知故障已由 M10-T5 补齐；默认主链、PostgreSQL 和跨进程恢复仍未完成，`KI-004` 保持 mitigated。
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

若本轮中断，先阅读 `docs/continuity/course-delivery-playbook.md` 与 `docs/continuity/handoffs/2026-08-08-m11-t1-postgres-application-lifecycle.md`，再核对 `V-20260808-014`、`V-20260808-013`、`ADR-0022`、实施计划 M11-T1/M11-T2 和实际 application lifecycle/composition/async facade/PostgreSQL adapters。先确认 Docker 与本地测试容器状态，再按 handoff 重跑 PostgreSQL 91 项、提交后默认路径 63 项、真实 application 专项 2 项、M1 10 项和连续性检查；若一致，不要重做 M11-T1 十个纵切，下一步只进入 M11-T2 首个真实 pgvector 原子纵切。没有用户新的明确授权，不得安装依赖、读取 Key、执行在线/付费调用、配置远程 Git、新增部署配置或执行在线 Embedding。
