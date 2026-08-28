# M12-T3 交接：同 Run RAG 引用与 usage 投影

- 日期：2026-08-28，Asia/Shanghai
- 已验收任务：`M12-T3 / verified`
- 下一任务：`M12-T4 / planned`
- 验证基线：`f8770a1`
- 验证记录：`V-20260828-010`
- 关联决策：`ADR-0025`、`ADR-0026`、`ADR-0029`、`ADR-0030`、`ADR-0031`
- 任务等级：A 类（持久化、公开 API 和数据边界）
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本次结果

同步与异步 Context Runtime 在 Assembly 完成后，只将**实际入选**的 RAG
fragments 转换为 `rag.citations` 事件。每项仅含 title、source、excerpt 与有限
score；无 document ID、query、prompt、Memory、最近消息、系统策略、Skill 内容或
owner/session。RAG source 准备异常会先写入内容无关的 `context.failed`，随后由
Coordinator 正常提交同 Run 的安全失败终态。

`/api/durable` 的 create、get、list、cancel 和 approval snapshot 都从同 owner 的
EventStore sequence 分页读取事件。citation 和 usage 分别使用最近一条有效
`rag.citations`、`scope=run` 的 `model.usage`；不会重检索、重跑 Runtime 或从其它
Run 聚合。畸形 event 只被忽略，不能令 HTTP 失败或猜测 usage/cost。

本机 PostgreSQL 的 FastAPI lifespan 测试已覆盖：创建命中知识库的 durable Run、
收到 `rag.citations`、关闭应用、重新创建应用后按 owner 读取 snapshot，仍得到同一
citation。默认 ManualRuntime 没有模型 usage，因此 null 保持“未知”而非零。

## 修改文件

- `backend/app/context/runtime.py`
- `backend/app/context/async_runtime.py`
- `backend/app/main.py`
- `backend/tests/test_durable_run_projection.py`
- `backend/tests/postgres_store_integration.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/continuity/decisions/ADR-0031-durable-run-evidence-usage-projection.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- 本 handoff

## 验证

- 离线 Context/Run/API/SSE/Coordinator 回归 79 项通过。
- 真实本地 PostgreSQL FastAPI restart 的 citation snapshot 与相邻 durable Run/SSE
  重启回归 3 项通过。
- 没有执行在线模型、前端、浏览器、Nginx 或远程 Git。

## 下一条原子动作

开始 M12-T4 前，先只读阅读实施计划 M12-T4、当前 Vue 结构、现有 Research API
调用与 durable snapshot/SSE 的 response/event contract。只实现 Vue 侧“创建/恢复
同一 Run、消费 snapshot 与 SSE、处理终态/审批/错误”的最小状态机；不要在页面再以
Research API 覆盖答案，不要提前进入浏览器 E2E、Nginx、成本账本或新在线调用。
