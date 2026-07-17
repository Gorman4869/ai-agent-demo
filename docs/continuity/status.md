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
- M8-T7 验证基线提交：`6e86e1e`
- M8-T7 课程文档提交：`ba7adf9`
- M9-T1 验证基线提交：`ba7adf9`；实现提交待本轮本地 commit 固定
- 远程仓库：未配置
- 在线付费调用：未授权执行

## 当前任务

| 字段 | 内容 |
| --- | --- |
| 任务 ID | `M9-T2` |
| 状态 | `planned` |
| 目标 | 使用 M9-T1 的已连接 Session 完成 `list_tools`、Schema 规范化、权限过滤、名称冲突策略与远程调用适配器 |
| 设计依据 | `docs/stages/09-mcp-client-skills.md`、实施计划 M9-T2、`ADR-0009`、现有共同 `ToolDefinition`/Registry 契约 |
| 执行协议 | 课程优先、里程碑验收；见 `docs/continuity/course-delivery-playbook.md` |
| 当前修改 | M9-T1 已建立服务端允许的 MCP Server 配置、真实 SDK STDIO initialize、每连接同任务清理和 FastAPI lifespan；9 项新增测试与 68 项定向回归通过，状态为 `verified` |
| 前置证据 | `V-20260717-004`、`ADR-0009` |
| 下一动作 | 按 B 类普通框架任务只读审阅 M9-T2、`backend/app/tools`、SDK tool adapter 与 M9-T1 私有 Session 边界；先定义发现快照、Schema/权限/命名冲突和调用超时，不提前执行 M9-T3 TypeScript E2E 或 Skill |

## 里程碑状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| M0–M7 历史基线 | `code_complete` | 现有产物已落盘但审计后仅部分覆盖；未满足项由 M8–M14 接管，旧链暂不标记 `superseded` |
| C0 连续性基线 | `verified` | 计划基线 `6f8490a`；验证见 `V-20260716-001`、`V-20260716-002` |
| M8 真实模型与运行时 | `code_complete` | M8-T1、M8-T2、M8-T3、M8-T5、M8-T7 verified；M8-T4、M8-T6 code_complete；全量离线门通过，真实在线 E4 未授权，不能 accepted |
| M9 MCP Client 与 Skill | `in_progress` | M9-T1 verified；当前任务 M9-T2，MCP 工具发现/映射与 TypeScript E2E 尚未完成 |
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

- M9-T1 见 `V-20260717-004`：9 项新增生命周期测试和 68 项 Settings/Container/FastAPI/API/online-smoke 定向回归通过；真实本地 Python MCP Server 完成 `stdio_client -> ClientSession.initialize()` 和关闭，证据为本地协议 E3。
- M9-T1 没有实现 `list_tools`、Schema/RBAC/名称冲突、`call_tool`、断线重连、调用幂等或 TypeScript Server E2E；`KI-002` 保持 open，由 M9-T2/M9-T3 接管。
- M9-T1 没有修改依赖/锁文件、HTTP Schema、前端或跨前后端接口，因此按 B 类协议只运行定向回归，没有重复执行 `scripts/verify.ps1` 全量门。
- M8-T7 课程验收见 `V-20260717-003`：Provider 故障命令 1 项、框架对照 12 项和全量后端 252 项通过，1 项既有 Windows symlink 跳过；Vue、MCP 与 Compose 配置门通过。
- M8-T6 工作区验证见 `V-20260717-001`，实现提交 `bd6c09a` 的恢复锚点见 `V-20260717-002`：12 项新增关键测试与 102 项定向回归通过，Fake Runtime 经实际 Store/Coordinator 纵切；这只是 E3，不是在线 Provider 证据。
- 没有用户新的单次授权，因此没有读取真实 Key、运行带 `-Authorized` 的脚本、访问模型服务或产生费用；Provider strict schema、真实 streaming、工具调用、usage、模型质量、费用和资源清理仍无 E4 证据。
- `KI-018` 的逐调用硬成本门、版本化定价源与持久 usage/cost 账本仍未实现；本次 operator-supplied 费用估算不得描述成账单事实。
- M8 课程和离线工程已 `code_complete`，但没有真实在线 E4，不能标记 `accepted`；学习者个人自测与费曼勾选仍只写 `docs/progress.md`。
- `KI-001` 保持 mitigated；`KI-016`、`KI-017`、`KI-018` 的生产缺口不变，后续分别由 M11-M13 承接。

## 恢复入口

若本轮中断，先阅读 `docs/continuity/course-delivery-playbook.md` 与 `docs/continuity/handoffs/2026-07-17-m9-t1-mcp-client-lifecycle.md`，再核对 `V-20260717-004`、`ADR-0009`、实施计划 M9-T2 和 `docs/stages/09-mcp-client-skills.md`。若 9 项 MCP 生命周期测试、68 项定向回归和连续性检查仍一致，不要重做 M9-T1；下一步只设计 M9-T2 的工具发现与共同 ToolDefinition 映射，不提前执行 M9-T3 TypeScript E2E、Skill 或 M10。没有用户新的单次授权，不得读取 Key 或执行真实模型。
