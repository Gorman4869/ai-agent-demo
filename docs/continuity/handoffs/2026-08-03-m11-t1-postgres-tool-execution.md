# M11-T1 交接：PostgreSQL ToolExecution 第三纵切

- 日期：2026-08-03，Asia/Shanghai
- 当前任务：`M11-T1`
- 当前状态：`in_progress`
- 里程碑状态：`M11 / in_progress`
- 验证基线 HEAD：`bb36875`
- 第三纵切实现提交：`0de735d`
- 验证记录：`V-20260803-003`、`V-20260803-004`
- 关联决策：`ADR-0015`
- 分支：`main`
- 任务等级：A 类副作用、持久化、幂等、事务和跨进程恢复边界，时间盒 2–4 小时
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 新增 async `ToolExecutionStore` 与内存参考实现；owner 通过父 Run 绑定，只有 running Run 能创建 pending/version 0 执行。
2. 固定每 Run/call 唯一和 `(run_id, tool_name, idempotency digest)` 幂等作用域。副作用必须有 key，同键同参数返回既有状态，同键改参数冲突；原始 key、参数和结果不保存。
3. 新增 `0003_tool_execution_store.sql` 与 `PostgresToolExecutionStore`，使用现有 async pool；创建锁 Run 行，claim/settle 锁 ToolExecution 行并做 version CAS，并发只有一个赢家。
4. 三进程 probe 证明 terminal commit 后进程异常退出时新进程读取 completed 并幂等 replay；遗留 running 只能显式转 terminal unknown，不能重放。
5. settlement trigger 故障证明结果更新整事务回滚，记录保持 running 且没有结果摘要；数据库错误稳定映射、不回退内存。
6. 新增 `ADR-0015`，更新后端规约、实施计划、known issue、status 和验证证据；默认 Container、lease/recovery scanning 与 M11-T2 保持未实现。

## 本次修改文件

- `backend/app/stores/tool_execution.py`
- `backend/app/stores/memory.py`
- `backend/app/stores/postgres_tool_execution.py`
- `backend/app/stores/postgres_tool_execution_probe.py`
- `backend/app/stores/postgres.py`
- `backend/app/stores/__init__.py`
- `backend/migrations/0003_tool_execution_store.sql`
- `backend/tests/test_tool_execution_store_contract.py`
- `backend/tests/postgres_store_integration.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/continuity/decisions/ADR-0015-postgres-tool-execution-arbitration.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-08-03-m11-t1-postgres-tool-execution.md`

没有修改依赖、领域 ToolExecution 形状、默认 Container、ToolRegistry/Runtime/HTTP、前端、lease、pgvector 或在线 Provider 配置。

## 实际验证

- 启动恢复：真实 PostgreSQL 53 项、M1 7 项、连续性 52/75 通过；前两个纵切代码与记录一致。
- 共同合同：内存与 PostgreSQL 各 10 项通过，覆盖 owner、running 创建门、幂等 replay/conflict、call 冲突、并发 claim/settle、unknown 和终态 Run replay。
- PostgreSQL 最终集成：65 项通过，包括 migration 1/2/3、前三个纵切、三进程结果未知恢复和 settlement trigger 回滚；预期不可达 pool timeout，无 ResourceWarning。
- 受影响回归：Run/Store/Coordinator/LangGraph 108 项通过；M1 禁用 `site-packages` 后 7 项通过。
- 完整门：沙箱首轮后端 381 项通过、1 项跳过，Code Agent 与依赖通过后因 Vue `tsbuildinfo` EPERM 退出 1；相同脚本获批后后端、Vue、MCP TypeScript 和 Compose 配置全部通过。
- 连续性与 diff：52 个稳定任务、77 个 Markdown 通过；`git diff --check` 无 whitespace 错误。
- 提交后恢复：实现提交 `0de735d` 上真实 PostgreSQL 65 项、M1 7 项和连续性 52/77 再次通过；工作区干净，预期 pool timeout 仍无 ResourceWarning。

## 失败、警告与边界

- Compose 状态查询权限审查 stream 断开后，使用已批准的只读 `docker exec ... pg_isready` 确认健康；没有重建或清理容器。
- 内存合同首轮因测试取消 Run 漏传 `error_code` 失败 1 项，修正测试输入后通过；状态机未放宽。
- `0003` 首轮显式 CHECK 名与列级自动名冲突，migration 回滚；其后 fixture setup 连锁 63 errors 并耗尽该测试进程连接。回滚诊断确认 PostgreSQL `42710`，重命名后 4 项 migration 与完整 65 项均通过。
- 首轮 ad-hoc PowerShell `finally Remove-Item` 遮蔽了 unittest 退出码；后续命令显式保存并恢复 `$LASTEXITCODE`。该失败已按测试输出记录，未改写为成功。
- 后端仍有既有 `StarletteDeprecationWarning`、三条 notifier 负向日志和 1 项 Windows symlink 跳过；不可达数据库用例仍有预期 pool timeout。
- 本纵切不证明外部副作用与数据库 exactly-once，也未实现 lease/heartbeat、自动恢复扫描、跨 pool/Run/Event/checkpoint 事务、默认主链、生产数据库能力或在线 Provider。

## 未提交改动

上述代码、migration、测试、ADR、规约和 `V-20260803-003` 已由实现提交 `0de735d` 固定；当前仅 `V-20260803-004`、status 和 handoff 的提交后锚点待本地文档提交。没有任务外改动，没有读取密钥，没有在线模型或付费调用，没有远程 Git 操作。本地 PostgreSQL 测试容器保持运行。

## 下一条原子动作

继续 `M11-T1`，只设计并实现 PostgreSQL lease/heartbeat 与 orphan recovery scanning：先固定 server-owned lease token、过期时间、heartbeat CAS、scanner 领用规则和 running Run/ToolExecution 的 fail-closed 结论，再做真实多进程租约竞争与过期恢复。不要同时迁移默认 Container、解决同步 Approval/Memory 的 async 线程边界，也不进入 M11-T2 pgvector。

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

预期 PostgreSQL 集成 65 项、M1 7 项通过且无 ResourceWarning，连续性保持 52 个稳定任务、77 个 Markdown。若一致，不要重做前三个纵切；下一步只进入 lease/heartbeat 与 orphan recovery scanning。未经用户新的明确授权，不安装依赖、不读取 Key、不执行在线/付费调用、不配置或推送远程 Git、不迁移默认 Container、不扩大到 M11-T2。
