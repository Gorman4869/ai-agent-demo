# 当前实施状态

- 更新时间：2026-07-20，Asia/Shanghai
- 计划版本：2.0
- 当前分支：`main`
- 最近已确认实现提交：`a6ff518`
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
- M9-T6 验证基线提交：`19b5596`
- 远程仓库：未配置
- 在线付费调用：未授权执行

## 当前任务

| 字段 | 内容 |
| --- | --- |
| 任务 ID | `M10-T1` |
| 状态 | `planned` |
| 目标 | 建立具有稳定 graph state、thread ID、共享内存 checkpointer、状态版本和迁移边界的可持久 StateGraph 纵切 |
| 设计依据 | `docs/stages/10-durable-langgraph.md`、实施计划 M10-T1、M8-T3 Runtime/Coordinator 与 M9-T2 共同工具契约 |
| 执行协议 | 课程优先、里程碑验收；见 `docs/continuity/course-delivery-playbook.md` |
| 当前修改 | M9-T6 已完成四次里程碑跟练、三者对照、roots 边界、三类考核、一页速查、费曼任务和 30 项映射；M9 聚焦 40 项与全量离线门通过，状态为 `verified` |
| 前置证据 | `V-20260720-009`、`V-20260720-008`、`V-20260720-004` |
| 下一动作 | 只读审阅 M10-T1、阶段 10、现有 LangGraph Runtime 与已安装 checkpointer API，先固定 state/thread/version/迁移和进程内持久边界；不提前实现 M10-T2 interrupt/resume |

## 里程碑状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| M0–M7 历史基线 | `code_complete` | 现有产物已落盘但审计后仅部分覆盖；未满足项由 M8–M14 接管，旧链暂不标记 `superseded` |
| C0 连续性基线 | `verified` | 计划基线 `6f8490a`；验证见 `V-20260716-001`、`V-20260716-002` |
| M8 真实模型与运行时 | `code_complete` | M8-T1、M8-T2、M8-T3、M8-T5、M8-T7 verified；M8-T4、M8-T6 code_complete；全量离线门通过，真实在线 E4 未授权，不能 accepted |
| M9 MCP Client 与 Skill | `verified` | M9-T1–M9-T6 verified，`KI-002` closed；本地 Python/Node STDIO、共同工具边界、只读 Skill/Runtime 上下文、课程材料和离线全量门均有证据，远程/生产 E4 不在本里程碑证据内 |
| M10 LangGraph 持久工作流 | `planned` | 依赖 M8、M9 |
| M11 上下文、记忆与真实 RAG | `planned` | 依赖 M10 状态和 Store 协议 |
| M12 统一 Run 与实时 UI | `planned` | 依赖 M10、M11 |
| M13 生产工程闭环 | `planned` | 依赖 M12 主链路 |
| M14 高级 Agent 作品集 | `planned` | 依赖 M13 安全、观测和部署门禁 |

## 当前阻塞

- Docker Engine 未运行；不阻塞文档和离线测试，但阻塞容器、PostgreSQL/pgvector 和 Nginx 实际验收。
- 真实模型在线冒烟测试尚未获得单次执行授权；不阻塞离线实现与测试。
- 远程 Git 地址尚未提供；不阻塞本地提交。

## 未验证范围

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

若本轮中断，先阅读 `docs/continuity/course-delivery-playbook.md` 与 `docs/continuity/handoffs/2026-07-20-m9-t6-course-acceptance.md`，再核对 `V-20260720-009`、实施计划 M10-T1 和 `docs/stages/10-durable-langgraph.md`。若 M9 聚焦 40 项、固定 2 项离线评测与连续性检查仍一致，不要重做 M9；下一步只读审阅现有 LangGraph Runtime、checkpointer API 与状态契约，不提前实现 M10-T2。没有用户新的单次授权，不得读取 Key 或执行真实模型。
