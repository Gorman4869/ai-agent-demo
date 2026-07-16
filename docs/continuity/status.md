# 当前实施状态

- 更新时间：2026-07-16，Asia/Shanghai
- 计划版本：2.0
- 当前分支：`main`
- 最近已确认提交：`4ac81b4`
- 远程仓库：未配置
- 在线付费调用：未授权执行

## 当前任务

| 字段 | 内容 |
| --- | --- |
| 任务 ID | `M8-T3` |
| 状态 | `planned` |
| 目标 | 建立异步 AgentRuntime、ManualRuntime、RunCoordinator、持久 emitter 与终态一次提交用例边界 |
| 设计依据 | `docs/superpowers/specs/2026-07-16-ai-agent-transition-completion-design.md` |
| 当前修改 | M8-T2 已提交并验证；新 Store 尚未接入 Runtime 或旧 API，`KI-015` 终态事务边界保持 open |
| 前置证据 | `V-20260716-004` |
| 下一动作 | 审计现有 ManualAgentLoop/事件/取消/观测边界，先写 Runtime 与 Coordinator 失败契约测试；未经许可不安装依赖 |

## 里程碑状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| M0–M7 历史基线 | `code_complete` | 现有产物已落盘但审计后仅部分覆盖；未满足项由 M8–M14 接管，旧链暂不标记 `superseded` |
| C0 连续性基线 | `verified` | 计划基线 `6f8490a`；验证见 `V-20260716-001`、`V-20260716-002` |
| M8 真实模型与运行时 | `in_progress` | M8-T1、M8-T2 verified；M8-T3 planned；M8-T6 在线门仍未授权 |
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

- 当前没有未验证的业务代码。M8-T3 及后续规划不得被误读为实现证据。
- `KI-015` 仍 open：当前 Store 阻止终态后的晚到事件，但 Run 终态与终态事件的通用原子 Unit of Work 尚未实现。

## 恢复入口

最新执行者应先阅读本文件，再阅读 `docs/continuity/handoffs/2026-07-16-m8-t2-run-store-contract.md` 和 `docs/continuity/decisions/ADR-0006-durable-run-store-contract.md`。M8-T3 从失败契约测试开始，不要重写 M8-T1/T2 或双写旧 API。
