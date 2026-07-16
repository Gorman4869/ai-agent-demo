# 当前实施状态

- 更新时间：2026-07-16，Asia/Shanghai
- 计划版本：2.0
- 当前分支：`main`
- 最近已确认实现提交：`b171ad0`
- 最近文档闭环提交：`5086ddc`
- 远程仓库：未配置
- 在线付费调用：未授权执行

## 当前任务

| 字段 | 内容 |
| --- | --- |
| 任务 ID | `M8-T4` |
| 状态 | `in_progress` |
| 目标 | 先建立 OpenAI Agents Runtime 的 fake runner/event fixture 与离线适配契约，不执行在线模型调用 |
| 设计依据 | `docs/superpowers/specs/2026-07-16-ai-agent-transition-completion-design.md`、`ADR-0007`、`ADR-0008` |
| 当前修改 | 已核对本地 `openai-agents==0.18.2` 和官方 Runner/stream/usage 文档；正在固定可注入 Runner、显式 client/model、Trace 关闭、事件白名单、每 Run 工具隔离和 aggregate usage 边界 |
| 前置证据 | `V-20260716-005` |
| 下一动作 | 提交 M8-T4 设计基线后，先写 `test_openai_agents_runtime.py` 的 fake runner/event 失败契约，再实现适配器；没有新的单次授权不得在线调用 |

## 里程碑状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| M0–M7 历史基线 | `code_complete` | 现有产物已落盘但审计后仅部分覆盖；未满足项由 M8–M14 接管，旧链暂不标记 `superseded` |
| C0 连续性基线 | `verified` | 计划基线 `6f8490a`；验证见 `V-20260716-001`、`V-20260716-002` |
| M8 真实模型与运行时 | `in_progress` | M8-T1、M8-T2、M8-T3 verified；M8-T4 planned；M8-T6 在线门仍未授权 |
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

- 当前没有 M8-T4 未验证业务代码；实施前设计基线由实施计划、ADR-0008 与本状态固定。
- 实现提交 `b171ad0` 已通过 60 项提交后核心回归和统一验证：197 项后端测试通过、1 项既有环境跳过，前端、MCP、pip 与 Compose 配置均通过。
- `KI-015` 已 mitigated：内存 start/terminal 一次提交已实现；PostgreSQL 同事务与多进程证据仍缺。`KI-016`、`KI-017` 分别跟踪 running 恢复与同步兼容 Runtime 限制。

## 恢复入口

若本轮中断，保留 M8-T3 实现 `b171ad0`，先阅读 `docs/continuity/decisions/ADR-0008-openai-agents-runtime-adapter.md` 与实施计划 M8-T4。若设计基线已提交但 `test_openai_agents_runtime.py` 不存在，就从 fake fixture 开始；不要迁移旧 HTTP/SSE，也不要执行在线 Runner。
