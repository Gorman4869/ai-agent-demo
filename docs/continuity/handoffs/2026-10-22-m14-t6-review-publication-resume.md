# M14-T6 审批恢复与 publication CAS 交接

## 当前状态

- 当前任务：`M14-T6 / in_progress`。
- 合同：accepted `ADR-0044`；本轮验证：`V-20261022-001`；验证基线：`3b68851`。
- 已实现审批 resume、持久 `ToolExecutionStore` 协议接线、owner-scoped 内存 publication CAS/对账和
  安全 `review.result`。
- 未实现 PostgreSQL publication、跨进程/重启、默认 Container/API/UI 或部署；没有读取 Key、调用
  Provider/公网、运行真实 Chromium/PostgreSQL/Docker、安装依赖或 push。

## 实现要点

1. 初始 Run 在审批暂停前创建 side-effecting `ToolExecution(PENDING -> WAITING_APPROVAL)`；审批请求
   异常时不遗留活跃 PENDING。
2. resume 只接受 ApprovalStore 中与 principal/Run/call/tool/arguments 完全一致的 resolution，并再次
   对可信 Run spec 与 server-derived publication command/idempotency digest 做校验。
3. ToolExecution 以 version CAS 从 WAITING 进入 RUNNING；Coordinator singleflight + Store CAS 让并发
   resume 只有一个 publisher 调用，其余读取同一 durable winner。
4. `InMemoryReviewPublicationStore` 使用 expected revision CAS 和业务键幂等 replay；只保存 owner/key/
   binding digest 与安全 result，不保存原始 evidence、owner 或幂等键。
5. result unknown 仅做一次权威 reconcile：已存在记录可在 ToolExecution 仍 RUNNING 时确认 completed；
   不存在/不可确认则落 terminal UNKNOWN，不自动重放。副作用边界内取消同样落 UNKNOWN。

## 修改文件

- `backend/app/advanced/review_publication.py`
- `backend/app/advanced/review_runtime.py`
- `backend/app/advanced/review_tools.py`
- `backend/app/advanced/__init__.py`
- `backend/tests/test_review_publication.py`
- `backend/tests/test_review_runtime.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- 本 handoff

## 验证

- 恢复基线 10/10；最终专项 23/23；副作用/Coordinator 聚焦回归 109/109；最终相关回归 170/170。
- compileall、continuity 和 `git diff --check` 结果见 `V-20261022-001`。
- 既有 observer、lease/notifier 故障注入与 asyncio slow-task 信息不是断言失败。

## 未验证范围

- publication Store 只有内存 adapter；不能声称进程重启、PostgreSQL 事务、多实例或可复现部署。
- result unknown 只在同一进程立即对账；ToolExecution 一旦确认 UNKNOWN 保持终态，不伪装成可重试。
- 未接默认 `ApplicationContainer`、HTTP 或 Vue；`review.result` 尚未进入公开 snapshot/UI 投影。
- 旧 capstone 架构/演示、成本、威胁、故障和迁移材料尚未重写，`KI-034` 保持 open。

## 下一条原子动作

实现 PostgreSQL publication 持久纵切：

- 新增 versioned migration 与 owner-scoped publication adapter，保持与内存 Store 相同 CAS/幂等合同；
- 与现有 PostgreSQL Run/Event/Approval/ToolExecution Store 组合，不创建第二套审批或执行状态机；
- 用两个独立 composition/PID 验证批准后发布、重启 replay、并发同键唯一写入和 revision conflict；
- 注入 result unknown，分别验证权威记录已存在时确认完成、记录不存在时 UNKNOWN 且不重放；
- 继续不接默认 API/UI，不运行在线模型；真实 PostgreSQL/Docker 执行前按项目外部门禁取得授权。

没有新的在线模型授权。若后续在线视觉能显著提升作品集证据，仍需先说明用途、模型、调用次数、
计费口径和停止条件并重新取得单次授权；环境变量中存在 Key 不构成授权。
