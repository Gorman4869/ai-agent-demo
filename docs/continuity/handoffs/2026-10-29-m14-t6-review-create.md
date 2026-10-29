# M14-T6 显式内存 review create 交接

- 任务 M14-T6 / in_progress；A 类身份/创建幂等，2–4 小时时间盒内的内存创建原子步骤。
- base HEAD `34a5823`；验证 `V-20261029-002`；开始工作树干净。
- 文件：advanced/review_application.py、api/schemas.py、main.py、test_review_application.py，后端规约、
  m14-review-api-contract、implementation-plan、known-issues、status、verification 和本 handoff。
- `create_review_app` 接受服务端 registry/authenticator，装配内存 Run/Event/ToolExecution；仅显式
  factory 注册 `/api/durable/reviews`。请求六字段经入口构造一次 ReviewRunSpec，拒绝额外控制字段。
- owner/role 来自 Principal，spec 包含于既有 request digest。相同 key 返回相同 Run，不重复启动；
  任一字段变化 409。绑定仅存在 server-owned per-Run map，Runtime 不解析 input_text 控制业务。
- 真实领域调用：OfflineVisionModel、KnowledgeBase、BrowserAgent + fixture driver、内存 publication CAS。
  测试没有真实 Chromium/Provider/公网。已有 durable 审批、snapshot 和 SSE 读取同一 Run。
- 恢复 47/47，相关回归 92/92，最后类型标注/测试环境调整后创建专项 6/6。无失败命令。
  Starlette TestClient deprecation 与 asyncio slow-task 信息保留。KI-035 未改动/未重跑。
- 全部未提交修改属于本次原子步骤，仅本地提交，不 push。未使用 Key，未新增依赖或修改学习者进度。

## 恢复命令

`python -B -m unittest backend.tests.test_review_application backend.tests.test_review_projection backend.tests.test_review_runtime backend.tests.test_persistent_run_api -q`

## 下一条原子动作

补齐 PostgreSQL composition，而后接 Vue：

1. 先审阅 RunRecord request_options（当前只影响 digest、不持久化）、RunStore create 事务、迁移和
   ReviewRunCatalog。选择私有 spec 存储及其原子绑定方式；不得借用 input_text、公开事件、Memory fact
   或假审批来保存控制面。跨模块长期存储决策应新增 ADR。
2. Review Runtime/registry 当前直接调用同步 ApprovalStore。PostgreSQL async 路径必须接已有有界
   async approval façade，不能把同步 pool 方法直接放到 event loop；同时检查 Coordinator 的 resume 边界。
3. 用同一 Postgres Run/Event/Approval/ToolExecution/publication 验证创建、重启暂停、批准后发布、
   幂等重放和 snapshot。内存 factory 的证据不代表这些能力。
4. 再接 Vue；本任务不需要在线模型 Key。KI-034 保持 open。
