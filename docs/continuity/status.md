# 当前实施状态

- 更新时间：2026-07-17，Asia/Shanghai
- 计划版本：2.0
- 当前分支：`main`
- 最近已确认实现提交：`e03f8d6`
- 最近 M8-T4 文档闭环提交：`176d182`
- 本轮协议修改基线提交：`ed5ad9c`
- M8-T5 验证基线提交：`f83cbbc`
- M8-T5 实现提交：`e03f8d6`
- M8-T6 验证基线提交：`e03f8d6`；实现提交待本轮本地 commit 固定
- 远程仓库：未配置
- 在线付费调用：未授权执行

## 当前任务

| 字段 | 内容 |
| --- | --- |
| 任务 ID | `M8-T7` |
| 状态 | `planned` |
| 目标 | 汇总 M8 跟练、自测、速查表、费曼复述与 30 项大纲映射，并以可复现证据验收里程碑边界 |
| 设计依据 | `docs/stages/08-real-model-runtimes.md`、实施计划 M8-T7、`ADR-0002`、`ADR-0005`、`ADR-0008` |
| 执行协议 | 课程优先、里程碑验收；见 `docs/continuity/course-delivery-playbook.md` |
| 当前修改 | M8-T6 已在基线 `e03f8d6` 上完成独立在线脚本、双重授权门、低预算策略、安全摘要和 12 项离线关键测试；真实在线 E4 未授权且未执行，状态为 `code_complete` |
| 前置证据 | `V-20260716-008`、`V-20260717-001` |
| 下一动作 | 按 B 类里程碑验收任务审阅 `docs/stages/08-real-model-runtimes.md`，先列出 M8-T7 教程与验收缺口；引用 M8-T6 online not authorized 状态，不运行带 `-Authorized` 的脚本 |

## 里程碑状态

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| M0–M7 历史基线 | `code_complete` | 现有产物已落盘但审计后仅部分覆盖；未满足项由 M8–M14 接管，旧链暂不标记 `superseded` |
| C0 连续性基线 | `verified` | 计划基线 `6f8490a`；验证见 `V-20260716-001`、`V-20260716-002` |
| M8 真实模型与运行时 | `in_progress` | M8-T1、M8-T2、M8-T3、M8-T5 verified；M8-T4、M8-T6 code_complete；M8-T7 planned，在线执行仍未授权 |
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

## 未验证范围

- M8-T6 工作区验证见 `V-20260717-001`：12 项新增关键测试与 102 项定向回归通过，Fake Runtime 经实际 Store/Coordinator 纵切；这只是 E3，不是在线 Provider 证据。
- 没有用户新的单次授权，因此没有读取真实 Key、运行带 `-Authorized` 的脚本、访问模型服务或产生费用；Provider strict schema、真实 streaming、工具调用、usage、模型质量、费用和资源清理仍无 E4 证据。
- M8-T6 没有修改依赖、锁文件、HTTP API、前端、跨前后端公共契约或发布配置，因此没有运行 `scripts/verify.ps1` 全量门。
- `KI-018` 的逐调用硬成本门、版本化定价源与持久 usage/cost 账本仍未实现；本次 operator-supplied 费用估算不得描述成账单事实。
- `KI-019` 已由 `V-20260717-001` 关闭；`KI-001` 保持 mitigated，`KI-016`、`KI-017`、`KI-018` 的生产缺口不变。

## 恢复入口

若本轮中断，先阅读 `docs/continuity/course-delivery-playbook.md` 与 `docs/continuity/handoffs/2026-07-17-m8-t6-online-smoke-gate.md`，再核对 `V-20260717-001`、ADR-0008 与实施计划 M8-T7。若 12 项 M8-T6 新增测试和 102 项定向回归仍通过，不要重做 M8-T5/M8-T6；下一步只审阅并补齐 M8-T7 里程碑跟练与验收。没有用户新的单次授权，不得读取 Key、执行真实模型、迁移旧 HTTP/SSE 或提前进入 M9/M10。
