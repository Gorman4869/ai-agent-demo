# M14-T6 review snapshot 交接

- 任务 M14-T6 / in_progress；A 类公共 HTTP 合同，2–4 小时时间盒内 snapshot 原子步骤。
- base HEAD `10bec14`；验证 `V-20261029-001`，ADR-0044；开始工作区干净。
- 修改：api/schemas.py、api/review_projection.py、main.py、test_review_projection.py；后端规约、
  implementation-plan、known-issues、status、verification、新增 docs/m14-review-api-contract.md 和本文件。
- snapshot 从持久事件还原 review。完整 bundle/digest/ref、合法 publication 和 completed Run 才显示
  published；等待、拒绝、unknown 等通过 outcome 显示；普通 Run 为 null。不从 answer 或当前资源推断。
- 同步 HTTP approval fixture 实际经过 Coordinator/Review Runtime/ToolExecution；新 app 读取共享
  内存 Store 证明重复投影，不是 OS 重启。Provider、PostgreSQL、浏览器、Vue、部署未运行。
- 验证：恢复 26/26，最终 47/47。首轮夹具 policy 摘要不一致造成 1 项失败，修正本次夹具后通过。
  扩大 74 项有 1 项 legacy RAG approved 失败；在进程内加载旧 HEAD schemas/main 重跑仍失败，KI-035
  跟踪，不修改 learner RAG。已有 Starlette TestClient deprecation warning 保留。
- 未提交修改均为本次任务；提交只包含上述文件，不 push。

## 恢复命令

`python -B -m unittest backend.tests.test_review_projection backend.tests.test_durable_run_projection backend.tests.test_review_runtime backend.tests.test_review_publication backend.tests.test_persistent_run_api -q`

Windows 沙箱 async socketpair 限制按既有流程申请沙箱外执行。

## 下一条原子动作

实现显式 review create 与 opt-in composition。先读 durable create、Settings、Container、async approval
和 review Runtime，选择持久 Run spec 绑定方式，避免进程内可变 catalog 无法跨进程恢复。六个业务字段
参与 create request digest，owner/role 来自 Principal，图片/page 仍只用 server-owned ID。先用既有
四工具链验证创建→证据→审批→发布与 snapshot，再接 Vue。无需在线 Key。

业务映射和常见错误见 docs/m14-review-api-contract.md；KI-034 保持 open，KI-035 独立处理。
