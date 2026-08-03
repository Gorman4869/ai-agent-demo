# M11-T1 交接：PostgreSQL Run lease 与 orphan recovery 第四纵切

- 日期：2026-08-03，Asia/Shanghai
- 当前任务：`M11-T1`
- 当前状态：`in_progress`
- 里程碑状态：`M11 / in_progress`
- 验证基线 HEAD：`1219737`
- 第四纵切实现提交：由后续本地 commit 固定
- 验证记录：`V-20260803-005`
- 关联决策：`ADR-0016`
- 分支：`main`
- 任务等级：A 类持久化凭证、并发租约、故障恢复、migration 与跨进程仲裁，时间盒 2–4 小时
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 新增 async `RunLeaseStore`、repr-safe server token handle 与内存参考实现；只有 running owned Run 能 acquire，每 Run 一条租约，旧 token/version 不能 heartbeat 或 release。
2. 新增 `0004_run_leases.sql` 与 `PostgresRunLeaseStore`。数据库只保存 token SHA-256，以 `clock_timestamp()` 判断过期；heartbeat 固定 Run row→lease row 锁序，scanner 用 `FOR UPDATE SKIP LOCKED` 轮换 recovery token。
3. 新增显式 `RunRecoveryService.scan_once()`：running ToolExecution→unknown，pending/waiting→cancelled，既有终态不变；随后以 `TerminalCommit` 写入非重试 `run_orphaned`，最后释放租约。
4. 真实 PostgreSQL 触发器故障证明工具已安全终结而 Run/Event 回滚时，recovery lease 再过期后下一轮扫描可以收敛；不把分离事务称为原子或 exactly-once。
5. 四个 PID 不同的 probe 进程证明 execution holder 以 17 退出后，两个 scanner 竞争同一过期租约只有一个恢复者；审计进程确认 Run/tool/event/lease 结果，stdout 不输出 token、参数、key 或结果。
6. 新增 `ADR-0016`，更新后端规约、实施计划、known issue、status 和验证证据；默认 Container/Coordinator、后台 scanner、同步 Approval/Memory async 边界与 M11-T2 保持未实现。

## 本次修改文件

- `backend/app/stores/run_lease.py`
- `backend/app/stores/memory.py`
- `backend/app/stores/postgres_run_lease.py`
- `backend/app/stores/postgres_recovery_probe.py`
- `backend/app/stores/postgres.py`
- `backend/app/stores/__init__.py`
- `backend/app/services/run_recovery.py`
- `backend/migrations/0004_run_leases.sql`
- `backend/tests/test_run_lease_store_contract.py`
- `backend/tests/test_run_recovery.py`
- `backend/tests/postgres_store_integration.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/continuity/decisions/ADR-0016-postgres-run-lease-recovery.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-08-03-m11-t1-postgres-run-lease-recovery.md`

没有修改依赖、默认 Container、RunCoordinator、ToolRegistry/Runtime/HTTP、前端、pgvector 或在线 Provider 配置。

## 实际验证

- 启动恢复：真实 PostgreSQL 65 项、M1 7 项、连续性 52/77 通过；前三个纵切代码与记录一致。
- 内存最终专项：lease/recovery 13 项通过，覆盖 owner/running 门、token 隐藏、heartbeat/release CAS、时钟失败不变异、过期领用、scanner 竞争、Run 状态绑定、工具/Run fail-closed 和部分故障收敛。
- PostgreSQL 最终集成：76 项通过，包括 migration 1–4、前四个纵切、token 摘要、数据库时钟、并发 scanner、四进程恢复和 recovery trigger 回滚；预期不可达 pool timeout，无 ResourceWarning。
- 受影响回归：Run/Store/Coordinator/LangGraph 131 项通过；M1 禁用 `site-packages` 后 7 项通过。
- 完整门：沙箱首轮后端 393 项通过、1 项跳过，Code Agent 与依赖通过后因 Vue `tsbuildinfo` EPERM 退出 1；相同脚本获批后通过。锁序复审补两项合同后，最终后端 394 项、Vue、MCP TypeScript 和 Compose 配置再次全部通过。
- 连续性与 diff：新增 ADR/handoff 后 52 个稳定任务、79 个 Markdown 通过，`git diff --check` 无 whitespace 错误，仅有 Git 的 LF/CRLF 转换提示。

## 失败、警告与边界

- 首轮 PostgreSQL lease 合同因 fixture 固定 Run 时间晚于未注入的 RunStore 时钟，7 项在准备阶段报“时间倒退”；按既有合同模式注入固定时钟后通过，没有放宽领域校验。
- 首次 ADR 路径推测、两次窄 patch 上下文和一次 Windows 路径正则不匹配均未修改文件；按实际路径/上下文重试成功。
- 完整门沙箱首轮仍受 Vue `tsbuildinfo` EPERM 影响，批准后最终通过；后端保留一条既有 `StarletteDeprecationWarning`、三条 notifier 负向日志和 1 项 Windows symlink 跳过；不可达数据库用例仍有预期 pool timeout。
- ToolExecution、Run/Event 和 lease release 不共享事务，外部副作用也不在数据库事务中。scanner 证明 fail-closed 与最终收敛，不证明 exactly-once、自动业务补偿、生产调度或原子快照。
- 默认 Coordinator 尚未 acquire/heartbeat/release，应用 lifespan 没有 scanner；同步 Approval/Memory 直接接 async 主链仍会阻塞。统一应用重启、容器重启、跨主机、生产鉴权/TLS/持久卷/备份/高可用/容量均未验证。

## 未提交改动

第四纵切代码、migration、测试、ADR、规约和 `V-20260803-005` 当前均为本任务工作区改动，实现提交由后续本地 commit 固定。没有任务外改动，没有读取密钥，没有在线模型或付费调用，没有远程 Git 操作。本地 PostgreSQL 测试容器保持运行。

## 下一条原子动作

继续 `M11-T1`，只设计并实现显式注入的 `RunCoordinator` lease 生命周期：先固定 acquire 与 `run.started` 的顺序、heartbeat 所有权、pause/terminal/cancel 的 release、lease-lost fail-closed 和进程内 heartbeat 清理，再跑内存与真实 PostgreSQL 协调器竞争/故障测试。不要同时迁移默认 Container/HTTP，不解决同步 Approval/Memory 的 async 线程边界，也不进入 M11-T2 pgvector。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
docker exec ai-agent-demo-m11-postgres-1 pg_isready -U ai_agent -d ai_agent_test
$env:AI_AGENT_TEST_POSTGRES_DSN = "postgresql://ai_agent@127.0.0.1:55432/ai_agent_test?sslmode=disable"
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.postgres_store_integration -q
$testExit = $LASTEXITCODE
Remove-Item Env:\AI_AGENT_TEST_POSTGRES_DSN -ErrorAction SilentlyContinue
if ($testExit -ne 0) { exit $testExit }
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 PostgreSQL 集成 76 项、M1 7 项通过且无 ResourceWarning，连续性保持 52 个稳定任务、79 个 Markdown。若一致，不要重做前四个纵切；下一步只进入显式 Coordinator lease 生命周期。未经用户新的明确授权，不安装依赖、不读取 Key、不执行在线/付费调用、不配置或推送远程 Git、不迁移默认 Container/HTTP、不扩大到同步 Approval/Memory async 边界或 M11-T2。
