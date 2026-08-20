# M11-T5 主 Run 消息发布第四纵切交接

- 时间：2026-08-20 09:33，Asia/Shanghai
- 当前任务：`M11-T5 / in_progress`
- 验证基线：`b87b6c8`
- 第三纵切实现提交：`b87b6c8`
- 第四纵切实现提交：待本轮 Git 固定
- 证据：`V-20260820-001/002`
- 任务等级：A 类 persistence/side-effect/concurrency 边界；2–4 小时时间盒

## 已完成

- `RunCoordinator` 是主 Run conversation message 的唯一发布者。只有 completed terminal commit 的 `created=true` 赢家按 user→assistant 写入；failed/cancelled、approval pause 和 replay 不写。
- 发布顺序固定为 durable terminal→user→assistant→live notify→lease release。approval resume 写原始输入与最终回答一次；消息不自动提升为长期 fact。
- 默认内存 Container 共享同一 AsyncLocal Memory façade 给 Context collector 和 Coordinator；默认 PostgreSQL composition 把 owned async façade 注入 Coordinator，显式 caller Runtime mapping 保持不变。
- Run 1 completed turn 已被 Run 2 作为 recent context 读取；Store/terminal failure、并发 replay、quiesce 与安全日志均有风险测试。
- terminal 后 Memory 失败不回滚已完成 Run、不自动重试；owned publication 在 quiesce 关闭 persistence 前完成或以安全失败收敛。

## 修改文件

- `backend/app/services/run_coordinator.py`
- `backend/app/container.py`
- `backend/app/postgres_execution.py`
- `backend/tests/test_run_coordinator.py`
- `backend/tests/test_container.py`
- `backend/tests/test_postgres_execution.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/continuity/status.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-08-20-m11-t5-run-message-publication.md`

## 验证快照

- 恢复基线：PostgreSQL composition/Container 39 项、连续性 52/108 通过；Node 22.16.0。
- 最终关键修改面：RunCoordinator/Container/PostgreSQL composition 76 项通过。
- 共享相关回归：245 项通过；M1 `python -S` 隔离 10 项通过。
- 完整离线门：后端 586 项通过、1 项既有 Windows symlink 能力跳过；Code Agent、依赖、Vue、MCP TypeScript 与 Compose 配置全部通过。
- 第一份完整门结果句柄在会话压缩后失效，未作为证据；相同脚本重新完整执行并以退出码 0 固定结果。
- 连续性：52 个稳定任务、109 个 Markdown 通过；`git diff --check` 通过。

## 未验证与边界

- durable Run terminal 与 Memory message 不共享事务；当前两次 append 不是 atomic/idempotent turn。崩溃可导致消息缺失，第二次失败可留下 user-only，replay 不补写；不能宣称 exactly-once。
- 未运行真实 PostgreSQL、进程/数据库重启、连接结果未知、跨进程发布竞争或 pgvector Context。
- 未实现错误记忆纠正/删除、版本冲突、审计、在线摘要、Provider 或固定 RAG 评测。
- 未读取 Key、调用在线服务、产生费用、安装依赖、配置 remote 或执行 push。
- M11-T5 不得提升为 `verified`，KI-005/KI-014 只保持 mitigated。

## 失败尝试

- 第一次完整门已启动，但会话压缩后执行句柄不可读取，最终状态未知；没有将其伪报为通过，随后重跑同一完整门并取得退出码 0。
- 沙箱外完整门仍使用前一纵切已批准的构建权限，因为 Vue `tsbuildinfo` 在沙箱内曾稳定出现 EPERM；没有修改源码绕过权限。

## 下一条原子动作

只开始 M11-T5 第五纵切：为 completed turn 增加 Run-bound atomic/idempotent Store command，先定义内存/PostgreSQL 共同合同与冲突语义，再增加版本化 migration 和真实 PostgreSQL restart/replay/partial-failure 证据。保持现有 terminal-first、可信 session、Context 读取、默认 Container 与外部 API 不变；不提前实现纠正/删除、版本审计、M11-T6 或 M12。

## 恢复命令

```powershell
git status --short
git log -5 --oneline
node --version
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_run_coordinator backend.tests.test_container backend.tests.test_postgres_execution -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 Node 至少为 18；当前验证版本为 22.16.0。若上述 76 项和连续性与 `V-20260820-001/002` 一致，不要重做 M11-T1–T4 或 M11-T5 前四纵切。
