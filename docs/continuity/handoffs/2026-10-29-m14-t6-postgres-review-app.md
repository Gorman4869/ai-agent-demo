# M14-T6 PostgreSQL review application 交接

- M14-T6 / in_progress，A 类 composition/审批 + C 类本机 PostgreSQL；base HEAD `10a7c70`。
- 验证 V-20261029-004；ADR-0044/0045；开始工作树干净。
- 新增 advanced/postgres_review_application.py；改 review_runtime.py、review_tools.py、Container/main、
  postgres_execution.py、Coordinator、Postgres 集成和 test_postgres_execution 夹具；规约/合同/连续性同步。
- factory 经原有 lifespan/setup 建 registry 和 PostgresReviewRuns；后者每次 await 私有 Store.resolve
  后构造 immutable catalog。Container.open 可接受既有 PostgresRuntimeFactory，不与显式 runtimes 混用。
- Runtime 审批 request/读取走 async façade，registry 同步 policy gate 在 composition owned bounded
  bridge 内，Coordinator.resolve 也 await 同一 async façade；内存路径保留 AsyncLocal 包装。
- 初次 82 项回归有 10 个夹具缺 async_approval_store 属性 error；补齐后 82/82。最终相关离线157/157，
  PostgreSQL 专项3/3、完整132/132。既有 TestClient deprecation、lease/notifier 注入日志、数据库负向
  timeout 保留。没有隐藏失败事实。
- 三次 TestClient app lifespan 验证：create/pause→close/reopen approve/reject/unknown→close/reopen
  replay/read/SSE；publisher 调用 approve=1、reject=0、unknown=1 且不重放；owner 越权404，变化请求409。
  同步审批五类方法均断言不在应用 event loop 线程执行。
- 本次 app 重开仍在同一测试 PID，不能声称 full-stack OS hard-kill/HA；Store 的独立PID验证见前序。
  Vision offline、Browser fixture driver；没有真实 Chromium/Provider/公网/前端/部署验证。
- 未安装依赖、未改 docs/progress.md、未用 Key、未 push；所有未提交文件属于本任务。

## 恢复

`python -B -m unittest backend.tests.test_review_application backend.tests.test_review_runtime backend.tests.test_review_tools backend.tests.test_postgres_execution backend.tests.test_container -q`

配置仓库 localhost integration test DSN 后跑
`python -X utf8 -B -m unittest backend.tests.postgres_store_integration.PostgresReviewApplicationTest -v`。

## 下一条原子动作

接 Vue 审查界面与可运行离线演示入口：

1. 阅读前端规约、package.json、现有 durable types/API/SSE 状态机、路由/页面和测试；按现有 Vue3/TS
   Composition API 风格接六字段 create，不加状态/UI库。
2. 增加 review projection 类型和页面证据/审批/结果展示，普通聊天仍走原入口。审批只提交 decision，
   其余完整绑定从同 Run 的 waiting 事件恢复；刷新由既有 snapshot+SSE 恢复。
3. 后端需要 server-owned PNG/page/policy/review 初始revision 演示目录和明确启动入口；继续使用
   独立 factory，固定离线视觉与受控 Browser，不把测试文件导入运行代码。
4. 用定向前端验证与真实应用 HTTP 证明 create/approve/refresh；再进入实际 deployment 复验。
   KI-034保持open，KI-035独立处理；没有新的在线授权。

业务映射：等待人工审批的后台工作流应在重开后从数据库恢复请求，而不是要求前端重发业务参数。
排错入口：spec request digest、stored approval、bridge worker、同 Run events 和 snapshot。
