# 当前实施状态

- 更新时间：2026-07-16，Asia/Shanghai
- 计划版本：2.0
- 当前分支：`main`
- 最近已确认实现提交：`ac24dda`
- 最近 M8-T4 文档闭环提交：`176d182`
- 本轮协议修改基线提交：`ed5ad9c`
- M8-T5 验证基线提交：`f83cbbc`
- 远程仓库：未配置
- 在线付费调用：未授权执行

## 当前任务

| 字段 | 内容 |
| --- | --- |
| 任务 ID | `M8-T6` |
| 状态 | `planned` |
| 目标 | 在完整显式门禁和用户新的单次授权下执行一次低预算真实流式 Run、工具调用与 usage/费用记录 |
| 设计依据 | `docs/superpowers/specs/2026-07-16-ai-agent-transition-completion-design.md`、`ADR-0002`、`ADR-0005`、`ADR-0008`、实施计划 M8-T6 |
| 执行协议 | 课程优先、里程碑验收；见 `docs/continuity/course-delivery-playbook.md` |
| 当前修改 | M8-T5 已在基线 `f83cbbc` 的工作区完成三 Runtime E3 共享契约、LangChain E2 调用链、取舍报告和定向验证；提交由本轮后续本地 commit 固定 |
| 前置证据 | `V-20260716-008` |
| 下一动作 | 按 C 类任务先只读核对并设计 `scripts/verify-online.ps1` 的 fail-closed 门；没有用户新的单次授权不得读取 Key、运行真实模型或产生费用 |

## 里程碑状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| M0–M7 历史基线 | `code_complete` | 现有产物已落盘但审计后仅部分覆盖；未满足项由 M8–M14 接管，旧链暂不标记 `superseded` |
| C0 连续性基线 | `verified` | 计划基线 `6f8490a`；验证见 `V-20260716-001`、`V-20260716-002` |
| M8 真实模型与运行时 | `in_progress` | M8-T1、M8-T2、M8-T3、M8-T5 verified；M8-T4 code_complete；M8-T6 planned，在线执行仍未授权 |
| M9 MCP Client 与 Skill | `planned` | 依赖 M8 Runtime 契约 |
| M10 LangGraph 持久工作流 | `planned` | 依赖 M8、M9 |
| M11 上下文、记忆与真实 RAG | `planned` | 依赖 M10 状态和 Store 协议 |
| M12 统一 Run 与实时 UI | `planned` | 依赖 M10、M11 |
| M13 生产工程闭环 | `planned` | 依赖 M12 主链路 |
| M14 高级 Agent 作品集 | `planned` | 依赖 M13 安全、观测和部署门禁 |

## 当前阻塞

- Docker Engine 未运行；不阻塞文档和离线测试，但阻塞容器、PostgreSQL/pgvector 和 Nginx 实际验收。
- 真实模型在线冒烟测试尚未获得单次执行授权；不阻塞离线实现与测试。
- 远程 Git 地址尚未提供；不阻塞本地提交。

## 未验证修改

- M8-T5 工作区验证见 `V-20260716-008`：LangChain Demo 实际进入 `create_agent().invoke()`；三 Runtime/SDK/Coordinator/Container 定向回归 89 项通过，新增 9 个高价值测试方法或等价参数化覆盖。
- M8-T5 没有修改依赖、锁文件、HTTP API、前端或跨前后端契约，因此没有重复运行 `scripts/verify.ps1` 全量门；本轮结束前只运行连续性和 diff 检查。
- M8-T4 真实 Provider strict schema、streaming、工具调用、usage、费用和资源清理仍无证据，状态继续是 `code_complete`；M8-T6 没有新的单次授权，不得执行在线部分。
- LangGraph checkpoint、interrupt、resume 与重启恢复仍由 `KI-004` / M10 跟踪；本任务的 LangGraph Runtime 只是无持久化的 M8 对照纵切。
- `KI-003` 已由 `V-20260716-008` 关闭；`KI-001` 保持 mitigated，`KI-016`、`KI-017`、`KI-018` 的生产缺口不变。

## 恢复入口

若本轮中断，先阅读 `docs/continuity/course-delivery-playbook.md` 与 `docs/continuity/handoffs/2026-07-16-m8-t5-runtime-framework-comparison.md`，再核对 `V-20260716-008`、ADR-0008 与实施计划 M8-T6。若 89 项定向回归和 LangChain Demo 仍通过，不要重做 M8-T5；下一步只设计 M8-T6 fail-closed 在线脚本。没有用户新的单次授权，不得读取 Key、执行真实模型、迁移旧 HTTP/SSE 或提前进入 M10。
