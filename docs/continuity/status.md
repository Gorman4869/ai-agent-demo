# 当前实施状态

- 更新时间：2026-07-16，Asia/Shanghai
- 计划版本：2.0
- 当前分支：`main`
- 最近已确认实现提交：`ac24dda`
- 最近文档闭环提交：`38a39d4`（本次 M8-T4 handoff 与验证记录尚在工作区）
- 远程仓库：未配置
- 在线付费调用：未授权执行

## 当前任务

| 字段 | 内容 |
| --- | --- |
| 任务 ID | `M8-T5` |
| 状态 | `planned` |
| 目标 | 用同一输入、工具、事件、结果和错误 fixture 对比 Manual、Agents SDK、LangGraph，并建立最小 LangChain 实际调用链 |
| 设计依据 | `docs/superpowers/specs/2026-07-16-ai-agent-transition-completion-design.md`、`ADR-0007`、`ADR-0008`、实施计划 M8-T5 |
| 当前修改 | M8-T4 实现 `ac24dda` 已达到离线 `code_complete`；正在提交验证日志、跟练教程、风险台账和恢复 handoff，尚未开始 M8-T5 业务代码 |
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
- 本次未验证修改仅为当前工作区中的 handoff、教程、ADR 校准、编码规范、风险和状态文档；提交后运行 continuity 并回填文档提交哈希。
- `KI-015` 已 mitigated；`KI-016` 跟踪 running 恢复，`KI-017` 跟踪同步 worker/工具线程，`KI-018` 跟踪请求、Token、费用和全程 timeout 的真实预算缺口。

## 恢复入口

若本轮中断，保留 M8-T4 实现 `ac24dda`，先阅读 `docs/continuity/handoffs/2026-07-16-m8-t4-openai-agents-runtime.md`、`V-20260716-006`、ADR-0008 与实施计划 M8-T5。若专项 33 项仍通过，不要重做 SDK Runtime；从三 Runtime 共用 fixture 开始。不要迁移旧 HTTP/SSE，也不要执行 M8-T6 在线 Runner。
