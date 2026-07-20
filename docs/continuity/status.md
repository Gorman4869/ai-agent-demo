# 当前实施状态

- 更新时间：2026-07-20，Asia/Shanghai
- 计划版本：2.0
- 当前分支：`main`
- 最近已确认实现提交：`de8a63d`
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
- M9-T5 验证基线提交：`c820c7e`；实现提交由本轮后续本地 commit 固定
- 远程仓库：未配置
- 在线付费调用：未授权执行

## 当前任务

| 字段 | 内容 |
| --- | --- |
| 任务 ID | `M9-T6` |
| 状态 | `planned` |
| 目标 | 汇总 M9-T1 至 M9-T5 的 MCP Client、共同工具适配与 Skill Runtime 纵切，形成完整跟练、速查、自测、费曼材料和里程碑验收证据 |
| 设计依据 | `docs/stages/09-mcp-client-skills.md`、实施计划 M9-T6、M9-T1 至 M9-T5 代码/验证、`ADR-0009` 与 `ADR-0010` |
| 执行协议 | 课程优先、里程碑验收；见 `docs/continuity/course-delivery-playbook.md` |
| 当前修改 | M9-T5 已实现路径脱敏且双层有界的 SkillContext、默认三 Runtime 注入、固定 LangGraph 离线效果/开销评测和权限不变性；10 项新增测试、151 项定向集、后端 294 项及构建/配置门通过，状态为 `verified` |
| 前置证据 | `V-20260720-007`、`V-20260720-006`、`V-20260720-003` |
| 下一动作 | 按实施计划只读盘点 M9-T1 至 M9-T5 的现有阶段材料、命令、验证和 30 项映射缺口，先列出 M9-T6 里程碑验收清单，不修改 Runtime、不提前进入 M10 |

## 里程碑状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| M0–M7 历史基线 | `code_complete` | 现有产物已落盘但审计后仅部分覆盖；未满足项由 M8–M14 接管，旧链暂不标记 `superseded` |
| C0 连续性基线 | `verified` | 计划基线 `6f8490a`；验证见 `V-20260716-001`、`V-20260716-002` |
| M8 真实模型与运行时 | `code_complete` | M8-T1、M8-T2、M8-T3、M8-T5、M8-T7 verified；M8-T4、M8-T6 code_complete；全量离线门通过，真实在线 E4 未授权，不能 accepted |
| M9 MCP Client 与 Skill | `in_progress` | M9-T1–M9-T5 verified，`KI-002` closed；当前任务 M9-T6，待汇总完整跟练、考核、速查、费曼材料和里程碑验收 |
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

- M9-T5 见 `V-20260720-007`：10 项新增测试、151 项共享 Runtime/Skill/安全定向集与全量门通过。全量首轮一个 TypeScript MCP E2E 命中启动超时，单项与全量重跑均通过；最终后端 294 项中 293 项通过、1 项既有 Windows symlink 能力跳过。
- 最终边界收紧后的全量脚本在后端 294 项、Code Agent 和依赖门通过后，因沙箱拒绝写 Vue `tsbuildinfo` 退出 1；相同 Vue build 经批准在沙箱外通过，MCP build 和 Compose 配置随后分别退出 0。完整顺序见 `V-20260720-007`。
- M9-T5 固定离线评测真实执行 LangGraph Runtime，但使用确定性 fixture 模型。触发片段 3153 UTF-8 字节、启发式 789 Token；不触发增加 0 字节。Provider usage 不可用、美元费用未知，不能描述为在线模型质量、真实 tokenizer 或账单证据，`KI-018` 保持 open。
- M9-T5 没有实现 Skill 写接口、热加载、跨进程刷新、审批恢复、持久成本账本或真实模型评测；M9-T6 只汇总课程验收，不应借机进入 M10/M13 的生产强化。
- M9-T4 见 `V-20260720-005`：10 项新增测试全部通过；与 Code Agent 路径边界合并的 17 项定向集为 16 项通过、1 项既有 Windows symlink 能力跳过。
- M9-T4 在当前 Windows 环境无法创建真实测试 symlink；实际 `../`/嵌套逃逸已由文件系统测试拒绝，符号链接拒绝只完成受控分支覆盖，不能描述为 OS 级 symlink 实证。
- M9-T4 尚未把 Skill 注入 Manual/SDK/LangGraph Runtime，也未执行触发效果、成本或权限不变性评测；这些由 M9-T5 接管。
- M9-T4 没有修改依赖/锁文件、公共 Runtime 契约、HTTP Schema 或前端，因此按 B 类协议只运行 Skill/路径安全定向回归，没有重复执行 `scripts/verify.ps1` 全量门。
- M8-T7 课程验收见 `V-20260717-003`：Provider 故障命令 1 项、框架对照 12 项和全量后端 252 项通过，1 项既有 Windows symlink 跳过；Vue、MCP 与 Compose 配置门通过。
- M8-T6 工作区验证见 `V-20260717-001`，实现提交 `bd6c09a` 的恢复锚点见 `V-20260717-002`：12 项新增关键测试与 102 项定向回归通过，Fake Runtime 经实际 Store/Coordinator 纵切；这只是 E3，不是在线 Provider 证据。
- 没有用户新的单次授权，因此没有读取真实 Key、运行带 `-Authorized` 的脚本、访问模型服务或产生费用；Provider strict schema、真实 streaming、工具调用、usage、模型质量、费用和资源清理仍无 E4 证据。
- `KI-018` 的逐调用硬成本门、版本化定价源与持久 usage/cost 账本仍未实现；本次 operator-supplied 费用估算不得描述成账单事实。
- M8 课程和离线工程已 `code_complete`，但没有真实在线 E4，不能标记 `accepted`；学习者个人自测与费曼勾选仍只写 `docs/progress.md`。
- `KI-001` 保持 mitigated；`KI-016`、`KI-017`、`KI-018` 的生产缺口不变，后续分别由 M11-M13 承接。

## 恢复入口

若本轮中断，先阅读 `docs/continuity/course-delivery-playbook.md` 与 `docs/continuity/handoffs/2026-07-20-m9-t5-skill-runtime-context.md`，再核对 `V-20260720-007`、`ADR-0010`、实施计划 M9-T6 和 `docs/stages/09-mcp-client-skills.md`。若 10 项 SkillContext 测试、固定 2 项离线评测、最终全量门和连续性检查仍一致，不要重做 M9-T1–M9-T5；下一步只盘点并汇总 M9 课程验收材料，不提前执行 M10。没有用户新的单次授权，不得读取 Key 或执行真实模型。
