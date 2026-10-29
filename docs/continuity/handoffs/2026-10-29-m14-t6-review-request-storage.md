# M14-T6 私有 review request Store 交接

- M14-T6 / in_progress，A 类事务/私有控制面 + C 类本机 PostgreSQL，2–4 小时时间盒内的 Store 原子步骤。
- base HEAD `aed032f`；验证 V-20261029-003；ADR-0044/0045；开始工作树干净。
- 新增 migration 8、ReviewRequestStore 协议/record factory、PostgresReviewRequestStore、双进程 probe
  和共享合同。内存 application 复用 record factory、增加 resolve。PostgresRunStore 只将原 create SQL
  抽到同 connection 内部方法，不改变普通 create 的公开语义。
- spec INSERT、Run 和 event counter 同事务；失败回滚不留 Run。resolve owner-scoped，并校验按原
  session/六字段重建的 request digest；错误映射稳定 StoreUnavailableError，无原文异常。
- spec 的 policy_topic 是私有业务字段，publication 表仍不存原文；没有将 spec 写进 input_text、
  公共事件、Memory fact 或假审批。删除 Run 时 FK cascade 删除 spec。
- 验证：恢复 43/43；共享合同+内存 HTTP 10/10；数据库初次 40/40，最终 request 专项 8/8；完整
  PostgreSQL 129/129，44.670s；相关离线 128/128；compileall/diff 通过。
- 无业务测试失败；既有 TestClient deprecation、slow-task 和不可达数据库负向 timeout 保留。
- integration 容器原已 healthy，本轮只读检查与测试，无 pull/新基础设施。未运行 Provider/Chromium/
  前端/部署，未改 KI-035、依赖、学习者进度或 push。
- 改动文件：advanced/review_requests.py、postgres_review_requests.py、postgres_review_request_probe.py、
  review_application.py；stores/postgres.py；migration 8；test_review_request_store.py、postgres_store_integration.py；
  后端规约、plan、API 合同、ADR-0045 和 continuity 文档。未提交修改均属于本次任务。

## 下一条原子动作

将已完成 Store 接入真正 PostgreSQL 应用运行链，而后接 Vue：

1. 给 portfolio Runtime wrapper 注入 async ReviewRequestStore.resolve，从 owned Run 恢复 spec 后创建
   immutable ReviewRunCatalog。保留内存 factory，避免影响默认 M1–M13 Runtime。
2. Review Runtime request/get_resolution/approved_arguments 与 registry policy gate 当前仍同步。
   用已有 bounded async approval façade 接线，检查 Coordinator.resume_approval 里的同步 resolve。
   不要用无限制 to_thread 绕开 owned bridge，也不要改变精确单次 grant 语义。
3. 在 PostgresExecutionComposition runtime_factory 中共享 persistence 的 Run/Event/ToolExecution、
   async approval 和 Postgres publication；创建 API 使用本 Store，composition lifecycle 保持既有顺序。
4. 真实 PostgreSQL 验证 create→pause→close/reopen→approve→published/SSE/snapshot 与同键 replay，
   再进入 Vue；当前两个 PID 只证明 Store 恢复，不证明该应用链。

恢复：`python -B -m unittest backend.tests.test_review_request_store backend.tests.test_review_application -q`。
数据库：设置仓库本机 integration test DSN 后运行 `backend.tests.postgres_store_integration.PostgresReviewRequestStoreTest`。
业务迁移：审核请求必须与 Run 原子存储；常见错误是单独写 spec 形成半成品。排查从 request digest、
owned Run 和私有表开始，不从用户输入或当前资源反推历史请求。
