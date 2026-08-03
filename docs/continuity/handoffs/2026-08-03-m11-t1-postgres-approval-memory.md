# M11-T1 交接：PostgreSQL Approval/Memory 第二纵切

- 日期：2026-08-03，Asia/Shanghai
- 当前任务：`M11-T1`
- 当前状态：`in_progress`
- 里程碑状态：`M11 / in_progress`
- 验证基线 HEAD：`bf875be`
- 第二纵切实现提交：`cb4fd52`
- 验证记录：`V-20260803-001`、`V-20260803-002`
- 关联决策：`ADR-0014`
- 分支：`main`
- 任务等级：A 类身份授权、私有数据、迁移、事务和跨进程恢复边界，时间盒 2–4 小时
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 新增同步 `ApprovalStore`/`MemoryStore` Protocol；现有内存实现、ToolExecutionContext、审批 Runtime、Container 与 `create_app()` 改为依赖抽象，默认实例和调用方式不变。
2. 新增 `0002_approval_memory_store.sql`、`PostgresApprovalStore` 与 `PostgresMemoryStore`。私有审批参数与公开 grant 分表；resolve/grant 同事务，consume row lock 单次结算；消息 per-session 排序并事务内裁剪，事实显式批准且 owner 隔离。
3. `PostgresPersistence` 使用同一 DSN 和生命周期管理原异步 pool 与 Approval/Memory 共享同步 pool；`ADR-0014` 明确两类 pool 没有跨 pool 事务，默认 async 主链暂不注入同步数据库适配器。
4. 新增内存/PostgreSQL 共同合同及安全进程 probe；两个 PID 不同的进程恢复私有参数、完成决议/单次消费，并恢复完整消息与长期事实。stdout 不包含这些私有内容。
5. ApprovalStore 故障在审批 Runtime 中原样传播；真实 grant 触发器失败证明 resolution 与 grant 一起回滚，不产生可消费授权。
6. 恢复审计先登记并关闭 `KI-022`，`KI-014` 进入 mitigated；新增 `KI-023` 跟踪同步数据库适配器接入 async 主链前的线程隔离、取消和超时缺口。

## 本次修改文件

- `backend/migrations/0002_approval_memory_store.sql`
- `backend/app/stores/postgres.py`
- `backend/app/stores/postgres_approval.py`
- `backend/app/stores/postgres_state_probe.py`
- `backend/app/memory/store.py`
- `backend/app/memory/postgres.py`
- `backend/app/memory/__init__.py`
- `backend/app/tools/registry.py`
- `backend/app/tools/__init__.py`
- `backend/app/agent/approval_runtime.py`
- `backend/app/security/identity.py`
- `backend/app/container.py`
- `backend/app/main.py`
- `backend/tests/test_approval_store_contract.py`
- `backend/tests/test_memory_store_contract.py`
- `backend/tests/test_langgraph_approval_resume.py`
- `backend/tests/postgres_store_integration.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/continuity/decisions/ADR-0014-postgres-approval-memory-pools.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-08-03-m11-t1-postgres-approval-memory.md`

没有修改依赖、默认 Container 实例、HTTP 行为、前端、ToolExecution、lease、pgvector 或在线 Provider 配置。

## 实际验证

- 启动恢复：真实 PostgreSQL 35 项、M1 7 项、连续性 52/73 通过；首个纵切代码与提交一致。
- 新共同合同：内存与 PostgreSQL 各运行 11 项 Approval、5 项 Memory 行为；参数脱离、64 KB 上限、owner/binding、伪造 resolution、拒绝/过期、并发单次消费、消息窗口与事实删除均覆盖。
- PostgreSQL 最终集成：53 项通过，包括两个进程 Approval/Memory 恢复、grant 故障事务回滚及既有 Run/Event/checkpoint/migration 合同；无 ResourceWarning。
- 受影响回归：Approval/Memory/Runtime/API/Container 等 80 项通过；M1 在禁用 `site-packages` 后 7 项通过。
- 完整发布门：沙箱首轮在当时后端 370 项通过、1 项跳过，Code Agent 与依赖通过后因 Vue `tsbuildinfo` 写入 EPERM 退出 1；相同脚本获批后退出 0。聚焦复审补 forged resolution 合同后，最终后端 371 项、Vue、MCP TypeScript 和 Compose 配置再次全部通过。
- 连续性与 diff：52 个稳定任务、75 个 Markdown 通过；`git diff --check` 无 whitespace 错误。
- 提交后恢复：实现提交 `cb4fd52` 上真实 PostgreSQL 53 项、M1 7 项和连续性 52/75 再次通过；容器保持 healthy，不可达数据库负向用例保留预期 pool timeout，仍无 ResourceWarning。

## 失败、警告与边界

- 首次猜错 ADR 文件名后按稳定编号纠正；Docker 沙箱只读检查被拒后获批成功；原容器不存在，经批准启动健康。一次窄 apply_patch 权限审查超时，原 patch 重试成功。
- 恢复和首轮聚焦测试各出现一条非持续 Windows asyncio 慢任务诊断；数据库不可达用例有一条预期 pool timeout；后端有既有 `StarletteDeprecationWarning` 和 1 项 Windows symlink 跳过。
- 同步 PostgreSQL Approval/Memory 不能直接当作 async 主链生产接线；尚无线程隔离、取消、超时、pool 耗尽或关闭竞争证据，见 `KI-023`。
- 两类 pool 不共享事务；未实现 ToolExecution 结果仲裁、lease/recovery scanning、默认 Container、ContextAssembler、pgvector、Embedding 或 RAG。
- 私有参数和记忆为本地测试数据库明文；没有加密、TLS、持久卷、备份、高可用、生产容量或在线 Provider 证据。

## 未提交改动

上述代码、migration、测试、ADR、规约和 `V-20260803-001` 已由实现提交 `cb4fd52` 固定；当前仅 `V-20260803-002`、status 和 handoff 的提交后锚点待本地文档提交。没有任务外改动，没有读取密钥，没有在线模型或付费调用，没有远程 Git 操作。本地 PostgreSQL 测试容器在交接时保持健康运行。

## 下一条原子动作

继续 `M11-T1`，只为领域 `ToolExecution` 增加 PostgreSQL migration、适配器和共同合同：先固定副作用幂等键、CAS、pending/running/terminal/unknown 状态与单次结果结算，再用真实数据库注入结算结果未知故障。不要同时实现 lease/recovery scanning、默认 Container，也不进入 M11-T2 pgvector。

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

预期 PostgreSQL 集成 53 项、M1 7 项通过且无 ResourceWarning，连续性保持 52 个稳定任务、75 个 Markdown。若一致，不要重做 Run/Event/checkpoint 或 Approval/Memory；下一步只进入 PostgreSQL ToolExecution 结果仲裁。未经用户新的明确授权，不安装依赖、不读取 Key、不执行在线/付费调用、不配置或推送远程 Git、不扩大到 M11-T2。
