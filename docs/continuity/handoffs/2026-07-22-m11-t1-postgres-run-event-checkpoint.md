# M11-T1 交接：PostgreSQL Run/Event/checkpoint 首个纵切

- 日期：2026-07-22，Asia/Shanghai
- 当前任务：`M11-T1`
- 当前状态：`in_progress`
- 里程碑状态：`M11 / in_progress`
- 验证基线 HEAD：`8af705b`
- 首个纵切实现提交：待本轮本地 commit 固定
- 验证记录：`V-20260722-009`
- 分支：`main`
- 任务等级：A 类关键持久化、事务和恢复边界，时间盒 2–4 小时
- 新增依赖：`langgraph-checkpoint-postgres==3.1.0`、`psycopg[binary,pool]==3.3.4`
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 新增 `0001_durable_run_event_store.sql` 与版本化 migration runner：SHA-256 校验和、advisory transaction lock、首次/重复执行、历史缺口、漂移拒绝和失败回滚均有真实 PostgreSQL 证据。
2. 新增共享异步连接池的 `PostgresPersistence`，提供继承现有合同的 RunStore、EventStore 与官方 `AsyncPostgresSaver`；数据库不可用稳定 fail closed，不回退内存。
3. Run/Event start、pause、resume、terminal 在持有 Run row lock 后同事务提交；事件使用每 Run 计数器。幂等创建、所有权、并发序号、并发终态和 event INSERT 触发器故障回滚均通过。
4. 新增公开离线 checkpoint probe 与显式 PostgreSQL 集成模块；两个 PID 不同的 Python 进程对同一可信 thread 依次观察 invocation count 0→1、1→2。
5. 新增 localhost-only、trust、tmpfs 的 PostgreSQL 17 测试 Compose；本轮用户已授权安装依赖、拉取镜像并启动容器。它不是生产部署配置。

## 本次修改文件

- `backend/requirements-m2.txt`
- `backend/migrations/0001_durable_run_event_store.sql`
- `backend/app/stores/postgres_migrations.py`
- `backend/app/stores/postgres.py`
- `backend/app/stores/postgres_checkpoint_probe.py`
- `backend/tests/postgres_store_integration.py`
- `deploy/compose.postgres.yaml`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-07-22-m11-t1-postgres-run-event-checkpoint.md`

没有修改默认 Container、公共 Store Protocol、HTTP/SSE、前端、pgvector 或在线 Provider 配置。

## 实际验证

- 启动恢复：M10 聚焦 58 项、M1 7 项、连续性 52/72 通过；代码与 M10 交接一致，无漂移。
- 环境：Docker Client/Server 29.3.1；`postgres:17-alpine` 测试容器健康，实际 server version 17.10；端口只绑定 `127.0.0.1:55432`。
- PostgreSQL 集成：最终 35 项通过，包括共同 RunStore 合同、migration、事务回滚、数据库不可用和两个 Python 进程 checkpoint 恢复。
- 受影响回归：RunStore、Coordinator、checkpoint 与 approval 共 71 项通过；M1 在禁用 `site-packages` 后 7 项通过。
- 完整发布门：沙箱首轮因 Vue `tsconfig.app.tsbuildinfo` 写入 `EPERM` 退出 1；相同脚本经批准后退出 0，后端 354 项通过、1 项既有 Windows symlink 跳过，Code Agent、依赖、Vue、MCP TypeScript 和 Compose 配置均通过。
- 连续性和 diff：52 个稳定任务、73 个 Markdown 通过；`git diff --check` 无 whitespace 错误。

## 失败、警告与边界

- 默认 Windows Proactor loop 被 psycopg 明确拒绝；适配器正确返回 `store_unavailable`。probe 与显式集成测试在自己的边界使用 Selector loop，生产模块不在 import 时修改全局 policy。
- 集成首轮 33 项中 32 项通过，Selector loop 下 asyncio subprocess 报 `NotImplementedError`；测试改为在线程中调用标准库 `subprocess.run` 后，真实两个 PID 恢复通过。
- 数据库不可达负向测试有一条预期的 pool timeout 诊断；全量后端有一条既有 `StarletteDeprecationWarning`，并跳过 1 项 Windows symlink 能力用例。
- 两进程恢复不是数据库容器重启、跨主机、并发同 thread、持久卷、备份、TLS、高可用或容量证据。
- Approval/Memory、私有审批参数、ToolExecution、连接结果未知仲裁、lease/recovery scanning、默认 Container 与 pgvector 尚未实现；不得将 M11-T1 标为 verified。

## 未提交改动

上述代码、依赖、测试 Compose、规约和连续性记录均在工作区，尚待首个纵切本地提交固定。没有任务外改动，没有读取密钥，没有在线模型或付费调用，没有远程 Git 操作。本地 PostgreSQL 测试容器在交接时保持健康运行。

## 下一条原子动作

继续 `M11-T1`，只新增 PostgreSQL ApprovalStore/MemoryStore 所需 migration、适配器和内存/PostgreSQL 共同合同，并持久化审批恢复需要的私有参数。先复用现有共享 pool、migration 和稳定错误边界；暂不实现 ToolExecution、lease、默认 Container，也不进入 M11-T2 pgvector。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
docker version
docker compose -f deploy/compose.postgres.yaml up -d --wait
$env:AI_AGENT_TEST_POSTGRES_DSN = "postgresql://ai_agent@127.0.0.1:55432/ai_agent_test?sslmode=disable"
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.postgres_store_integration -q
Remove-Item Env:\AI_AGENT_TEST_POSTGRES_DSN
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 PostgreSQL 集成 35 项、M1 7 项通过且无 ResourceWarning，连续性保持 52 个稳定任务、73 个 Markdown。若一致，不要重做 Run/Event/checkpoint 首个纵切；下一步只进入 PostgreSQL Approval/Memory。未经用户新的明确授权，不读取 Key、不执行在线/付费调用、不配置或推送远程 Git、不扩大到 M11-T2。
