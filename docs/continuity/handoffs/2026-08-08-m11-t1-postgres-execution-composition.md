# M11-T1 交接：显式 PostgreSQL execution composition

- 日期：2026-08-08，Asia/Shanghai
- 当前任务：`M11-T1 / in_progress`
- 任务等级：A 类资源所有权、取消、持久恢复和跨进程生命周期；时间盒 2–4 小时
- 第七纵切实现提交：`1d4386c`（`feat: compose postgres execution lifecycle`）
- 工作区验证：`V-20260808-007`
- 关联决策：`ADR-0019`、`ADR-0018`、`ADR-0017`、`ADR-0016`
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本轮结果

- 新增显式 `PostgresExecutionComposition`，按 persistence open/setup、lease-aware Coordinator、恢复服务/supervisor、supervisor start 的顺序构造完整执行链。
- setup、配置或 supervisor start 失败会逆序回收已取得资源；close 固定 supervisor 先于 persistence，重复调用幂等，关闭失败和调用方取消保持可见。
- 新增不同 PID 的真实 PostgreSQL probe：旧 holder 由 composition Coordinator 进入 running 后退出 17，新 composition 只靠自动 supervisor 提交 `run_orphaned`、唯一 `run.failed` 并释放 lease。
- 聚焦复审明确了 active Run 边界：本 composition 尚不拥有 admission stop/drain；调用方必须先停止 execute/resume 并等待 active Coordinator 操作结束，再 close pool。

## 验证摘要

- 修改前恢复：PostgreSQL 83 项、recovery/supervisor 14 项、M1 10 项和连续性 52 个稳定任务/84 个 Markdown 通过。
- 最终 composition 生命周期 9 项、真实 PostgreSQL 完整集 84 项、核心 composition/Run/Store/Coordinator/recovery/LangGraph 155 项、M1 隔离 10 项通过。
- 跨 PID composition 单例在实现提交前后均通过；不可达数据库 pool timeout、lease release/notifier 行均为既有负向用例的预期安全输出。
- 一次系统 Python 因 Windows 登录会话不可用而未启动；一次 `py_compile` 因现有 `__pycache__` 临时 pyc 写权限被拒绝。仓库 `.venv` 测试与不落盘 `compile()` 随后通过，失败事实保留在 `V-20260808-007`。
- 本切片没有触发全量门；第五纵切的完整门继续引用 `V-20260808-002`/`003`。

## 修改文件

- 实现提交：`backend/app/postgres_execution.py`、`backend/app/postgres_execution_probe.py`、`backend/tests/test_postgres_execution.py`、`backend/tests/postgres_store_integration.py`
- 决策/规约：`docs/continuity/decisions/ADR-0019-explicit-postgres-execution-composition.md`、`BACKEND_CODING_STANDARDS.md`
- 连续性：`docs/implementation-plan.md`、`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff

## 未验证范围

- composition close 不会主动禁止新的 execute/resume，也不会等待或终止 active Coordinator task；违反 close 前置条件时，Runtime/heartbeat 可能访问正在关闭的 pool。不能把当前 close 描述成安全应用 shutdown。
- 默认 `ApplicationContainer`、`create_app()`、FastAPI lifespan 和 HTTP 仍使用原有显式边界，没有统一 PostgreSQL 默认主链重启证据。
- PostgreSQL Approval/Memory 仍是同步 pool，async 线程隔离、取消、超时与耗尽未验证，`KI-023` 保持 open。
- lease、ToolExecution、Run/Event 与外部副作用仍是可收敛的分离边界，不是 exactly-once。localhost trust/tmpfs 容器不是生产部署、跨主机、高可用或容量证据。

## 下一条原子动作

继续 `M11-T1`，只设计并实现显式 Coordinator admission stop 与 active execution quiesce/drain 合同：composition 开始关闭后拒绝新 execute/resume，等待现有 Runtime/heartbeat 停止后才关闭 persistence，并用执行中关闭、等待超时、调用方取消和 lease 结果未知用例固定 fail-closed 语义。

本步骤仍不迁移默认 Container/HTTP/FastAPI lifespan，不调用同步 PostgreSQL Approval/Memory，不新增部署配置，不进入 M11-T2 pgvector。不得把 application shutdown 伪装成用户取消，也不得直接依赖 Coordinator 私有 task。

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
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_postgres_execution -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 PostgreSQL 84 项、composition 9 项、M1 10 项以及连续性 52 个稳定任务/86 个 Markdown 通过。若一致，不要重做前七个纵切；下一步只进入显式 Coordinator quiesce/drain。
