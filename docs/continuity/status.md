# 当前实施状态

- 更新时间：2026-07-17，Asia/Shanghai
- 计划版本：2.0
- 当前分支：`main`
- 最近已确认实现提交：`bd6c09a`
- 最近 M8-T4 文档闭环提交：`176d182`
- 本轮协议修改基线提交：`ed5ad9c`
- M8-T5 验证基线提交：`f83cbbc`
- M8-T5 实现提交：`e03f8d6`
- M8-T6 验证基线提交：`e03f8d6`
- M8-T6 实现提交：`bd6c09a`
- M8-T7 验证基线提交：`6e86e1e`；课程文档提交待本轮本地 commit 固定
- 远程仓库：未配置
- 在线付费调用：未授权执行

## 当前任务

| 字段 | 内容 |
| --- | --- |
| 任务 ID | `M9-T1` |
| 状态 | `planned` |
| 目标 | 建立允许配置驱动的 MCP Client 生命周期，在 FastAPI lifespan 中完成连接、超时、关闭与稳定失败诊断 |
| 设计依据 | `docs/stages/09-mcp-client-skills.md`、实施计划 M9-T1、`ADR-0001`、现有 M8 Runtime/Container 契约 |
| 执行协议 | 课程优先、里程碑验收；见 `docs/continuity/course-delivery-playbook.md` |
| 当前修改 | M8-T7 已在基线 `6e86e1e` 上补齐四次跟练、Provider 故障演练、三类自测、一页速查表、费曼任务和 30 项映射；全量离线门通过，状态为 `verified` |
| 前置证据 | `V-20260717-003` |
| 下一动作 | 按 B 类普通框架任务只读审阅实施计划 M9-T1、阶段 09、现有 TypeScript MCP Server 和锁定 Python MCP 依赖，先定义允许的 Server 配置与 Client 生命周期；不实现 M9-T2 工具映射 |

## 里程碑状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| M0–M7 历史基线 | `code_complete` | 现有产物已落盘但审计后仅部分覆盖；未满足项由 M8–M14 接管，旧链暂不标记 `superseded` |
| C0 连续性基线 | `verified` | 计划基线 `6f8490a`；验证见 `V-20260716-001`、`V-20260716-002` |
| M8 真实模型与运行时 | `code_complete` | M8-T1、M8-T2、M8-T3、M8-T5、M8-T7 verified；M8-T4、M8-T6 code_complete；全量离线门通过，真实在线 E4 未授权，不能 accepted |
| M9 MCP Client 与 Skill | `planned` | 当前任务 M9-T1；依赖的 M8 Runtime 契约已具备 E3 离线证据 |
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

- M8-T7 课程验收见 `V-20260717-003`：Provider 故障命令 1 项、框架对照 12 项和全量后端 252 项通过，1 项既有 Windows symlink 跳过；Vue、MCP 与 Compose 配置门通过。
- M8-T6 工作区验证见 `V-20260717-001`，实现提交 `bd6c09a` 的恢复锚点见 `V-20260717-002`：12 项新增关键测试与 102 项定向回归通过，Fake Runtime 经实际 Store/Coordinator 纵切；这只是 E3，不是在线 Provider 证据。
- 没有用户新的单次授权，因此没有读取真实 Key、运行带 `-Authorized` 的脚本、访问模型服务或产生费用；Provider strict schema、真实 streaming、工具调用、usage、模型质量、费用和资源清理仍无 E4 证据。
- M8-T6 没有修改依赖、锁文件、HTTP API、前端、跨前后端公共契约或发布配置，因此没有运行 `scripts/verify.ps1` 全量门。
- `KI-018` 的逐调用硬成本门、版本化定价源与持久 usage/cost 账本仍未实现；本次 operator-supplied 费用估算不得描述成账单事实。
- M8 课程和离线工程已 `code_complete`，但没有真实在线 E4，不能标记 `accepted`；学习者个人自测与费曼勾选仍只写 `docs/progress.md`。
- `KI-001` 保持 mitigated；`KI-016`、`KI-017`、`KI-018` 的生产缺口不变，后续分别由 M11-M13 承接。

## 恢复入口

若本轮中断，先阅读 `docs/continuity/course-delivery-playbook.md` 与 `docs/continuity/handoffs/2026-07-17-m8-t7-course-acceptance.md`，再核对 `V-20260717-003`、实施计划 M9-T1 和 `docs/stages/09-mcp-client-skills.md`。若全量离线门、52 个稳定任务/53 个 Markdown 文件的连续性检查和 M8 文档内容仍一致，不要重做 M8；下一步只设计 M9-T1 的 MCP Client 配置与生命周期，不提前实现工具发现、Skill 或 M10。没有用户新的单次授权，不得读取 Key 或执行真实模型。
