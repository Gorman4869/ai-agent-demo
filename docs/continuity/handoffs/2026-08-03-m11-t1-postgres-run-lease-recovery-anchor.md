# M11-T1 交接锚点：PostgreSQL Run lease 与 orphan recovery

- 日期：2026-08-03，Asia/Shanghai
- 当前任务：`M11-T1 / in_progress`
- 第四纵切实现提交：`1fc55fb`（`feat: recover orphaned runs with postgres leases`）
- 工作区验证：`V-20260803-005`
- 提交后恢复：`V-20260803-006`
- 关联决策：`ADR-0016`
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 提交后恢复结论

- 实现提交 `1fc55fb` 上真实 PostgreSQL 76 项通过；不可达数据库负向用例保留预期 pool timeout，无 ResourceWarning。
- 禁用 `site-packages` 后 M1 手写 Loop 7 项通过；提交后连续性检查在新增本锚点前为 52 个稳定任务/79 个 Markdown，新增后再次检查应为 52/80。
- `V-20260803-005` 的内存 13 项、受影响 131 项、完整门后端 394 项、四进程竞争、触发器故障、失败尝试和未验证范围不变。
- 本地 PostgreSQL 测试容器保持运行；没有任务外改动、密钥读取、在线调用、付费调用或远程 Git 操作。

## 下一条原子动作

继续 `M11-T1`，只设计并实现显式注入的 `RunCoordinator` lease 生命周期：固定 acquire 与 `run.started` 的顺序、heartbeat 所有权、pause/terminal/cancel release、lease-lost fail-closed 和进程内 heartbeat 清理。不要同时迁移默认 Container/HTTP，不解决同步 Approval/Memory 的 async 线程边界，也不进入 M11-T2。

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
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 PostgreSQL 76 项、M1 7 项、连续性 52 个稳定任务/80 个 Markdown 通过。若一致，不要重做前四个纵切；下一步只进入显式 Coordinator lease 生命周期。
