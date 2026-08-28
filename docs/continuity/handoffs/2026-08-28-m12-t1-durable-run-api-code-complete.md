# M12-T1 交接：持久 Run HTTP 状态事务（code_complete）

- 日期：2026-08-28，Asia/Shanghai
- 当前任务：`M12-T1 / code_complete`
- 验证基线：`e8f4f3b`
- 验证记录：`V-20260828-007`
- 关联决策：`ADR-0029`
- 任务等级：A 类持久 Run、身份、匿名 capability、幂等和公开 API；时间盒 2–4 小时
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本次完成

1. 新增隔离的 `/api/durable` Run API：创建、查询、会话列表、取消和审批；旧 `/api/sessions/.../runs`、`/api/runs/{id}` 与 SSE 未修改，且无 dual write。
2. 创建先通过 RunStore 原子 create，只有创建赢家才在后台调用 application-owned `RunCommands.execute()`；同 owner/key/请求返回同一 Run，变更请求返回内容无关 `409`。
3. 认证 owner 只来自 Principal。匿名初次创建用 32-byte-minimum 客户端随机 `Idempotency-Key` 作为 capability bootstrap，Store 仅保存 SHA-256 派生 owner；首次响应返回 capability，之后通过 `X-Session-Token` 访问或创建同一 session。
4. `session_id` 只有在同 owner 的既有 durable Run 存在时才可复用；首个 Run 本身是最小 session 所有权锚点，避免把任意客户端 session ID 交给 Context/Memory。
5. 审批 endpoint 只接收 approval ID 和 decision；tool call/name/arguments digest 由 owned `run.waiting_approval` 事件恢复，Coordinator 与 ApprovalStore 继续执行完整精确绑定。
6. snapshot response 固定返回 `run_id`、状态、answer、citations、usage 和安全 error 形状。M12-T1 未统一 RAG/usage，故 citations 为空、usage 为 null；该填充工作属于 M12-T3。

## 修改文件

- `backend/app/api/schemas.py`
- `backend/app/main.py`
- `backend/tests/test_persistent_run_api.py`
- `backend/tests/postgres_store_integration.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/continuity/decisions/ADR-0029-durable-run-http-ownership.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- 本 handoff

## 实际验证

| 命令 | 退出码 | 结果 |
| --- | ---: | --- |
| `./.venv/Scripts/python.exe -B -m unittest backend.tests.test_persistent_run_api backend.tests.test_api backend.tests.test_run_store_contract backend.tests.test_langgraph_approval_resume -q` | 0 | 76 项通过 |
| `./.venv/Scripts/python.exe -B -c "import backend.tests.postgres_store_integration"` | 0 | PostgreSQL 用例可导入；没有连接数据库 |
| `git diff --check` | 0 | 无 whitespace 错误；只有 LF/CRLF 工作树提示 |

## 未验证范围

- `docker exec ai-agent-demo-m11-postgres-1 pg_isready -U ai_agent -d ai_agent_test` 经沙箱外最小重试确认容器存在但未运行。因此 `PostgresFastApiApplicationTest.test_durable_run_api_replays_and_reads_after_application_restart` 未执行，M12-T1 保持 `code_complete`，不能宣称 PostgreSQL durable HTTP 或跨 lifespan 已验证。
- 没有实现 M12-T2 事件 SSE/after/heartbeat、M12-T3 RAG/Memory/usage 聚合、M12-T4 Vue、M12-T5 浏览器 E2E 或 M12-T6 兼容层替代。
- capability 没有过期、撤销、速率限制或生产 OIDC；这些不属于本任务。

## 下一条原子动作

在用户允许且本机 Docker integration 容器已启动后，只执行：

```powershell
$env:AI_AGENT_TEST_POSTGRES_DSN = "postgresql://ai_agent@127.0.0.1:55433/ai_agent_test?sslmode=disable"
./.venv/Scripts/python.exe -B -m unittest backend.tests.postgres_store_integration.PostgresFastApiApplicationTest.test_durable_run_api_replays_and_reads_after_application_restart -v
$testExit = $LASTEXITCODE
Remove-Item Env:\AI_AGENT_TEST_POSTGRES_DSN -ErrorAction SilentlyContinue
if ($testExit -ne 0) { exit $testExit }
```

若通过，先追加 verification、更新 `KI-004` 和 status 为 `verified`，再做最小恢复检查和本地提交；仍不得进入 M12-T2。
