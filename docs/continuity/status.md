# 当前实施状态

- 更新时间：2026-07-16，Asia/Shanghai
- 计划版本：2.0
- 当前分支：`main`
- 最近已确认实现提交：`ac24dda`
- 最近 M8-T4 文档闭环提交：`176d182`
- 本轮协议修改基线提交：`ed5ad9c`
- 远程仓库：未配置
- 在线付费调用：未授权执行

## 当前任务

| 字段 | 内容 |
| --- | --- |
| 任务 ID | `M8-T5` |
| 状态 | `planned` |
| 目标 | 用同一输入、工具、事件、结果和错误 fixture 对比 Manual、Agents SDK、LangGraph，并建立最小 LangChain 实际调用链 |
| 设计依据 | `docs/superpowers/specs/2026-07-16-ai-agent-transition-completion-design.md`、`ADR-0007`、`ADR-0008`、实施计划 M8-T5 |
| 执行协议 | 课程优先、里程碑验收；见 `docs/continuity/course-delivery-playbook.md` |
| 当前修改 | M8-T4 实现 `ac24dda`、文档闭环 `176d182` 与状态收尾 `ed5ad9c` 已固定；本轮只建立模型切换协议，M8-T5 尚未开始业务代码 |
| 前置证据 | `V-20260716-006` |
| 下一动作 | 先建立三 Runtime 共用 contract fixture，再完成 `labs/langchain-agent/` 最小对照；继续 offline，没有新的单次授权不得运行 M8-T6 |

## 里程碑状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| M0–M7 历史基线 | `code_complete` | 现有产物已落盘但审计后仅部分覆盖；未满足项由 M8–M14 接管，旧链暂不标记 `superseded` |
| C0 连续性基线 | `verified` | 计划基线 `6f8490a`；验证见 `V-20260716-001`、`V-20260716-002` |
| M8 真实模型与运行时 | `in_progress` | M8-T1、M8-T2、M8-T3 verified；M8-T4 code_complete；M8-T5 planned；M8-T6 在线门仍未授权 |
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

- M8-T4 业务代码已提交为 `ac24dda`，最终离线证据见 `V-20260716-006`：SDK 专项 33 项通过；统一验证 231 项后端测试通过、1 项既有 Windows 环境能力跳过，前端、MCP、pip 与 Compose 配置通过。
- M8-T4 仍缺真实 Provider strict schema、streaming、工具调用、usage 和费用证据，所以状态只能是 `code_complete`；M8-T6 没有新的单次授权，不得执行。
- 当前没有未提交的 M8-T4 业务或教程修改；本轮基于 `ed5ad9c` 只增加课程交付协议和模型切换记录，不改动或提升 M8-T5 业务状态。
- 本轮交付协议的文档、链接、连续性和 diff 证据见 `V-20260716-007`；没有以文档验证替代业务代码测试。
- `KI-015` 已 mitigated；`KI-016` 跟踪 running 恢复，`KI-017` 跟踪同步 worker/工具线程，`KI-018` 跟踪请求、Token、费用和全程 timeout 的真实预算缺口。

## 恢复入口

若本轮中断，先阅读 `docs/continuity/course-delivery-playbook.md` 与 `docs/continuity/handoffs/2026-07-16-model-switch-course-delivery.md`。保留 M8-T4 实现 `ac24dda`，再核对 `docs/continuity/handoffs/2026-07-16-m8-t4-openai-agents-runtime.md`、`V-20260716-006`、ADR-0008 与实施计划 M8-T5。若专项 33 项仍通过，不要重做 SDK Runtime；从三 Runtime 共用 fixture 开始。不要迁移旧 HTTP/SSE，也不要执行 M8-T6 在线 Runner。
