# M11-T5 第七纵切交接：versioned memory HTTP 与跨 lifespan 主 Run

- 日期：2026-08-20
- 任务：`M11-T5 / verified`
- 验证基线：`f066a90`
- 实现提交：在结束时固定
- 主要证据：`V-20260820-008/009`、`ADR-0028`

## 已完成

- 保留既有 `POST /api/memories` 响应和无 version DELETE 兼容行为；新增 active fact list/detail、approved version CAS PATCH、audit 和 DELETE 的可选 `expected_version`。
- 所有 versioned 路径的 owner 只来自认证 Principal。未认证、未批准、不存在/删除/跨 owner、陈旧版本和非法输入分别固定为 401/403/404/409/422，错误不输出 owner、key、value 或 current version。
- audit 只返回 fact ID、version、created/corrected/deleted 和 SHA-256 digest；owner 删除 tombstone 后仍可审计，其他 owner 不能探测。
- 三个真实 PostgreSQL application lifespan 证明 legacy create、version correction、durable main Run Context、version delete、下一 Run 不再注入、重启后空 active list 与完整 audit。默认 Container、Coordinator、Run Store、AsyncContextAwareRuntime 和 async Memory façade均进入实际链路。
- M11-T5 产物与测试条件已全部覆盖，状态提升为 `verified`；`KI-014` closed，`KI-005` 保持 mitigated 等待 M12 统一 Run。

## 修改文件

- `backend/app/api/schemas.py`
- `backend/app/main.py`
- `backend/tests/test_api.py`
- `backend/tests/postgres_store_integration.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/continuity/status.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-08-20-m11-t5-versioned-memory-http.md`

## 验证快照

- API 27 项、相关离线回归 115 项通过。
- 真实 PostgreSQL `PostgresFastApiApplicationTest` 2 项、完整 integration 110 项通过；预期不可达数据库负向日志不计失败。
- 完整门后端 599 项通过、1 项既有 Windows symlink 能力跳过；受控 Code Agent、Python 依赖、Vue、MCP TypeScript 与 Compose 配置全部通过。
- M1 `python -S` 隔离 10 项、连续性 52/114 和 `git diff --check` 通过。

## 未验证与边界

- 兼容无 version DELETE 按设计继续存在，旧客户端可以不做客户端 CAS；version-aware 客户端应提交 `expected_version`。
- async bridge timeout/取消/连接断开可能 result-unknown。可用 active version/audit 仲裁，但 correction/delete 没有持久 mutation idempotency key，不得自动重试。
- audit digest 不是加密，低熵 value 可能被猜测；数据库 trigger 不是外部不可篡改账本。
- active detail 当前复用 owner `facts()` 后线性过滤，不是大数据量分页或性能验收。
- Run/Event 与 Memory 不是共同事务，也没有后台扫描。本地 trust/tmpfs PostgreSQL 不代表生产鉴权、加密、备份、WAL、高可用或灾备；没有在线模型、Token/usage、费用或前端证据。

## 失败与警告

- 全量门首次输出被界面截断且结果句柄关闭，退出状态无法恢复，因此未计入证据；同一脚本重新完整执行后明确退出 0。
- 只有既有 Starlette/httpx deprecation warning、Windows symlink 条件跳过和 Git LF→CRLF 提示；没有新增失败。
- 恢复时发现 `status.md` 底部入口落后一个纵切，已先登记 `KI-026` 再修正并由连续性闭环关闭。

## 下一条原子动作

按实施计划开始 M11-T6：建立不少于 50 条查询的版本化 RAG 固定评测集，比较离线稀疏检索、pgvector 和可选重排的 Recall@K、MRR、回答依据正确率、延迟与成本边界。开始前重新读取 M11-T6 依赖、关联 ADR、最新验证和本交接；本轮没有实现 M11-T6。

## 恢复命令

```powershell
git status --short
git log -5 --oneline
node --version
docker compose -f deploy/compose.integration.yaml ps
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_api -q
$env:AI_AGENT_TEST_POSTGRES_DSN='postgresql://ai_agent@127.0.0.1:55433/ai_agent_integration'
.\.venv\Scripts\python.exe -B -m unittest backend.tests.postgres_store_integration.PostgresFastApiApplicationTest -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 Node 至少为 18；当前验证版本为 22.16.0。若 API 27 项、真实 PostgreSQL application lifespan 2 项和连续性一致，不要重做 M11-T1–T5，按 M11-T6 独立恢复。
