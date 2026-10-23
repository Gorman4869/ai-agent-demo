# M14-T6 PostgreSQL publication 与重启对账交接

## 当前状态

- 当前任务：`M14-T6 / in_progress`。
- 合同：accepted `ADR-0044`；本轮验证：`V-20261023-001`；验证基线：`aa334e8`。
- 已实现 migration 7、显式 PostgreSQL publication adapter、遗留 RUNNING 权威对账，以及真实本地
  PostgreSQL 双进程 commit-crash/recover。
- 未接默认 Container/API/UI 或部署；没有读取模型 Key、调用 Provider/公网、运行真实 Chromium、
  安装依赖、修改学习者进度或 push。

## 实现要点

1. `review_publication_heads` 用 owner scope digest + review ID 保存当前 revision；
   `review_publications` 保存 publication ID、review/decision/revision 和四类 digest，不保存原始 owner、
   幂等键、审批参数、证据内容或异常。
2. `PostgresReviewPublicationStore` 使用既有 async pool。publish 事务先创建可信初始 head（只来自构造时
   的 server-owned revision map），再锁行、检查同键 replay、校验 expected revision，并原子更新 head。
3. Runtime 遇到 `ToolExecution.RUNNING` 时不会进入 registry：相同业务键已有 publication 则补齐
   COMPLETED；不存在/查询失败则 UNKNOWN。正常、UNKNOWN、取消路径仍不自动重放副作用。
4. 双进程 probe 同时覆盖已提交和未提交两条结果未知窗口；恢复进程复用了 PostgreSQL
   Run/Event/Approval/ToolExecution Store，publisher replay 计数为零，并写入安全结果/终态事件。
5. adapter 保持显式注入，未添加到默认 `ApplicationContainer` 或 `PostgresPersistence` 属性，避免在
   API/UI 合同冻结前扩大 M1–M13 默认导入和运行路径。

## 修改文件

- `backend/migrations/0007_review_publication_store.sql`
- `backend/app/advanced/postgres_review_publication.py`
- `backend/app/advanced/postgres_review_publication_probe.py`
- `backend/app/advanced/review_runtime.py`
- `backend/tests/test_review_publication.py`
- `backend/tests/test_review_runtime.py`
- `backend/tests/postgres_store_integration.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- 本 handoff

## 验证

- 恢复基线 23/23；新增专项 26/26；真实 PostgreSQL 聚焦 12/12、完整 121/121；相关离线回归
  173/173；加强 UNKNOWN 断言后的双进程 probe 1/1。
- compileall、continuity 和 `git diff --check` 结果见 `V-20261023-001`。
- 首轮相关回归写错测试模块名而退出 1，修正为实际 `test_multimodal_agent` 后全绿；失败事实已保留。
- integration PostgreSQL 仍在本机 healthy 状态，localhost-only、tmpfs、未 pull 新镜像；不代表部署库。

## 未验证范围

- 适配器未接默认 Container/FastAPI/Vue；公开请求、approval resume API、SSE 与 snapshot 还看不到
  `review.result`，不能声称作品集 UI 或默认应用主链完成。
- PostgreSQL publication 与 ToolExecution、Approval、Run/Event 是可对账的独立事务，不是分布式
  exactly-once；外部发布系统、HA、备份、跨主机多实例和生产容量均未验证。
- 没有新的 Provider 授权；在线视觉、Token/usage、费用与公网 Browser 仍不能从历史 E4 推断。
- 旧 capstone 架构、演示、成本、威胁、故障和迁移材料尚未重写，`KI-034` 保持 open。

## 下一条原子动作

冻结并实现显式作品集 API/UI 纵切：

- 先定义 owner-scoped create/read/approval resume 请求与 snapshot `review` 投影，只复用 M12 durable
  Run、SSE 和 approval 端点语义，不修改 legacy `/api/sessions/...` 链或产生双写；
- 将 portfolio registry/runtime/catalog/publication 通过显式 factory 接入 opt-in composition，memory 与
  PostgreSQL 两档保持默认离线；
- 后端先覆盖创建、等待审批、批准发布、拒绝/过期、结果未知投影和重启读取，再做最小 Vue 展示；
- 仍不运行在线模型。若视觉质量确需真实 Provider，必须另行说明模型、调用次数、计费口径和停止条件，
  并取得新的单次授权。
