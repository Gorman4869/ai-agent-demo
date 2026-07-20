# 当前实施状态

- 更新时间：2026-07-20，Asia/Shanghai
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
- M9-T1 验证基线提交：`ba7adf9`；实现提交：`f8b59d2`
- M9-T2 验证基线提交：`f8b59d2`；实现提交：`40b1257`
- 远程仓库：未配置
- 在线付费调用：未授权执行

## 当前任务

| 字段 | 内容 |
| --- | --- |
| 任务 ID | `M9-T3` |
| 状态 | `planned` |
| 目标 | 构建现有 TypeScript Knowledge Server，并通过真实 STDIO 完成 initialize、list_tools、call_tool、非法参数与关闭 E2E |
| 设计依据 | `docs/stages/09-mcp-client-skills.md`、实施计划 M9-T3、`ADR-0009`、M9-T2 共同 `ToolDefinition` 适配边界 |
| 执行协议 | 课程优先、里程碑验收；见 `docs/continuity/course-delivery-playbook.md` |
| 当前修改 | M9-T2 已完成策略 allowlist、Schema 规范化、分页发现、名称冲突、角色过滤、调用超时和安全结果适配；7 项新增关键测试与 126 项定向回归通过，状态为 `verified` |
| 前置证据 | `V-20260720-001`、`V-20260720-002`、`V-20260717-004`、`ADR-0009` |
| 下一动作 | 按 B 类协议只读审阅 M9-T3、现有 TypeScript Knowledge Server 与构建脚本；重跑 Server 构建后新增 Python Client 对该 Server 的真实 STDIO E2E，不提前实现 Skill 或 M10 |

## 里程碑状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| M0–M7 历史基线 | `code_complete` | 现有产物已落盘但审计后仅部分覆盖；未满足项由 M8–M14 接管，旧链暂不标记 `superseded` |
| C0 连续性基线 | `verified` | 计划基线 `6f8490a`；验证见 `V-20260716-001`、`V-20260716-002` |
| M8 真实模型与运行时 | `code_complete` | M8-T1、M8-T2、M8-T3、M8-T5、M8-T7 verified；M8-T4、M8-T6 code_complete；全量离线门通过，真实在线 E4 未授权，不能 accepted |
| M9 MCP Client 与 Skill | `in_progress` | M9-T1、M9-T2 verified；当前任务 M9-T3，TypeScript Server E2E 与 Skill 尚未完成 |
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

- M9-T2 见 `V-20260720-001`：7 项新增关键测试和 126 项定向回归通过；真实本地 Python MCP Server 完成 `list_tools -> ToolDefinition -> Manual/SDK/LangGraph -> call_tool`，证据为本地协议 E3。
- M9-T2 没有执行 TypeScript Knowledge Server E2E、远程 transport、断线重连、调用幂等或副作用恢复；`KI-002` 保持 open，由 M9-T3 接管。
- M9-T2 没有修改依赖/锁文件、共享 `ToolDefinition` 公共契约、HTTP Schema、前端或跨前后端接口，因此按 B 类协议只运行定向回归，没有重复执行 `scripts/verify.ps1` 全量门。
- M8-T7 课程验收见 `V-20260717-003`：Provider 故障命令 1 项、框架对照 12 项和全量后端 252 项通过，1 项既有 Windows symlink 跳过；Vue、MCP 与 Compose 配置门通过。
- M8-T6 工作区验证见 `V-20260717-001`，实现提交 `bd6c09a` 的恢复锚点见 `V-20260717-002`：12 项新增关键测试与 102 项定向回归通过，Fake Runtime 经实际 Store/Coordinator 纵切；这只是 E3，不是在线 Provider 证据。
- 没有用户新的单次授权，因此没有读取真实 Key、运行带 `-Authorized` 的脚本、访问模型服务或产生费用；Provider strict schema、真实 streaming、工具调用、usage、模型质量、费用和资源清理仍无 E4 证据。
- `KI-018` 的逐调用硬成本门、版本化定价源与持久 usage/cost 账本仍未实现；本次 operator-supplied 费用估算不得描述成账单事实。
- M8 课程和离线工程已 `code_complete`，但没有真实在线 E4，不能标记 `accepted`；学习者个人自测与费曼勾选仍只写 `docs/progress.md`。
- `KI-001` 保持 mitigated；`KI-016`、`KI-017`、`KI-018` 的生产缺口不变，后续分别由 M11-M13 承接。

## 恢复入口

若本轮中断，先阅读 `docs/continuity/course-delivery-playbook.md` 与 `docs/continuity/handoffs/2026-07-20-m9-t2-mcp-tool-adapter.md`，再核对 `V-20260720-001`、`V-20260720-002`、`ADR-0009`、实施计划 M9-T3 和 `docs/stages/09-mcp-client-skills.md`。若 7 项 MCP 工具适配测试、126 项定向回归和连续性检查仍一致，不要重做 M9-T1/M9-T2；下一步只实现 TypeScript Knowledge Server 的真实 STDIO E2E，不提前执行 Skill 或 M10。没有用户新的单次授权，不得读取 Key 或执行真实模型。
