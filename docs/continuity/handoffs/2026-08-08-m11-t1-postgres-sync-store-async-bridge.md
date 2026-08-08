# M11-T1 交接：PostgreSQL 同步 Store async bridge

- 日期：2026-08-08，Asia/Shanghai
- 当前任务：`M11-T1 / in_progress`
- 任务等级：A 类同步数据库 I/O、线程取消、结果未知和资源关闭；时间盒 2–4 小时
- 第九纵切实现提交：`bffeab7`（`feat: isolate postgres sync stores`）
- 工作区验证：`V-20260808-011`
- 连续性闭环：`V-20260808-012`
- 关联决策：`ADR-0021`、`ADR-0020`、`ADR-0019`、`ADR-0014`
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- 新增共享有界 `PostgresSyncStoreBridge`，worker 数对齐同步 pool 容量；Approval/Memory async façade 通过专用线程真实调用现有同步 PostgreSQL adapters，不阻塞事件循环。
- queued timeout/cancel 会尝试取消尚未开始的 submission；running timeout 返回 `store_operation_timeout` 与 `result_unknown=true`，底层线程继续受 owner 追踪，不自动重试、不复用晚到结果。
- 审批参数在提交前复制。bridge close 停止 admission、等待 in-flight worker 后关闭 executor；persistence 再关闭 sync pool 与 async pool，sync close 失败也不跳过 async close。
- 同步 pool open 也改为 owned worker：调用方取消先等待 open 完成，再清理两类 pool。现有 composition 已通过 persistence close 自动继承该 drain 顺序。
- 真实 PostgreSQL async 纵切执行审批 resolve/consume、消息与事实写读、共享 pool exhaustion 和 composition shutdown 等待。

## 验证摘要

- 修改前恢复：PostgreSQL 86 项、quiesce+composition 18 项、M1 10 项和连续性 52 个稳定任务/88 个 Markdown 通过。
- 最终 async bridge 单元 9 项、真实 PostgreSQL 完整集 89 项、受影响 Approval/Memory/quiesce/composition/Runtime 56 项和 M1 隔离 10 项通过。
- 实现提交后，9 个单元与 3 个真实 PostgreSQL 专项共 12 项再次通过。
- 首轮 async bridge 7 项中 6 项通过；共享短 timeout 也让占位读按设计超时，但夹具清理错误期待成功。修正清理断言后通过，生产代码未因此放宽。
- 不落盘语法检查与 `git diff --check` 通过，仅有既有 LF/CRLF 提示。本切片没有触发全仓门，第五纵切完整门继续引用 `V-20260808-002`/`003`。

## 修改文件

- 实现提交：`backend/app/stores/postgres_async.py`、`backend/app/stores/postgres.py`、`backend/tests/test_postgres_async_stores.py`、`backend/tests/postgres_store_integration.py`
- 决策/规约：`docs/continuity/decisions/ADR-0021-postgres-sync-store-async-bridge.md`、`BACKEND_CODING_STANDARDS.md`
- 连续性：`docs/implementation-plan.md`、`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff

## 未验证范围

- 默认 `ApplicationContainer`、`create_app()`、FastAPI lifespan 和 HTTP 没有迁移到 PostgreSQL composition 或 async façade；`KI-023` 只更新为 mitigated。
- 只有 async façade 调用受 bridge admission/in-flight 追踪。为兼容旧合同保留的直接同步 adapters 不受追踪，其调用方必须先停止再关闭 persistence。
- Python worker 不能硬取消 PostgreSQL statement。running timeout/cancel 后结果可能未知；没有 statement timeout、线程强杀、进程级硬终止或有副作用写操作安全重试证据。
- Approval/Memory 的同步 pool 与 Run/Event/checkpoint 的 async pool 仍是分离事务，不是跨 pool 或外部副作用 exactly-once。
- 本地 trust/tmpfs 容器不是生产鉴权、TLS、持久卷、备份、高可用、跨主机或容量证据。

## 下一条原子动作

继续 `M11-T1`，只设计并实现显式 opt-in PostgreSQL application composition 接入 `ApplicationContainer` 和 FastAPI lifespan：

- 默认仍为离线内存配置；缺失或无效 PostgreSQL 配置 fail closed，不静默回退。
- startup 固定 composition open/setup/supervisor 与 MCP lifecycle 的全有或全无顺序；shutdown 先停止 HTTP/命令 admission，再关闭 composition。
- async 主链只使用 `async_approval_store`/`async_memory_store`，不得在 event loop 直接调用同步 PostgreSQL adapters。
- 该步骤涉及默认 composition、Settings 与 HTTP/lifespan 共享边界，应执行相应完整回归门；仍不新增部署配置，不进入 M11-T2 pgvector。

不得把本轮显式 composition 证据描述成默认应用已经使用 PostgreSQL，也不得在没有持久幂等语义时自动重试结果未知写操作。

## 恢复命令

```powershell
git status --short
git log -6 --oneline
docker exec ai-agent-demo-m11-postgres-1 pg_isready -U ai_agent -d ai_agent_test
$env:AI_AGENT_TEST_POSTGRES_DSN = "postgresql://ai_agent@127.0.0.1:55432/ai_agent_test?sslmode=disable"
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.postgres_store_integration -q
$testExit = $LASTEXITCODE
Remove-Item Env:\AI_AGENT_TEST_POSTGRES_DSN -ErrorAction SilentlyContinue
if ($testExit -ne 0) { exit $testExit }
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_postgres_async_stores -q
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_run_coordinator_quiesce backend.tests.test_postgres_execution -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 PostgreSQL 89 项、async bridge 9 项、quiesce+composition 18 项、M1 10 项以及连续性 52 个稳定任务/90 个 Markdown 通过。若一致，不要重做前九个纵切；下一步只进入显式 opt-in PostgreSQL application composition 与 FastAPI lifespan 接线。
