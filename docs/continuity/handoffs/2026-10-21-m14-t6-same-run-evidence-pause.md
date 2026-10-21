# M14-T6 同 Run evidence 与发布审批暂停交接

## 当前状态

- 当前任务：`M14-T6 / in_progress`。
- 合同：accepted `ADR-0044`；场景版本：`multisource-review-v1`。
- 本轮验证：`V-20261021-006`；验证基线：`86609d5`。
- 已实现可信 Run binding、三源 canonical evidence、每次调用预算和 `publish_review` 精确审批暂停。
- 未实现 approval resume、持久 `ToolExecution`、publication store、API/UI 或部署；没有读取 Key、
  调用 Provider/公网、运行真实 Chromium/Docker、安装依赖或 push。

## 实现要点

1. `ReviewRunCatalog` 是 immutable、owner-scoped 的可信请求目录；Runtime 忽略 `input_text` 中的
   resource/decision/role/budget/publish 指令，只使用目录内 server-owned 值。
2. `MultisourceReviewRuntime` 固定按 `inspect_image`、`search_review_policy`、
   `read_fixture_page` 顺序执行；每个成功结果投影为一条版本化且内容安全的 evidence event。
3. bundle 必须恰好是 image/policy/page；digest 由安全 event 字段 canonical JSON 派生。视觉文字、
   页面正文、RAG excerpt、owner 和原始工具参数不进入事件或普通 repr。
4. `ReviewToolCallBudget` 在 Runtime 层限制最多四调用、每工具一次、单副作用一次；缺审批 Store 在
   任何工具前 fail closed，取消和上游失败不执行后续工具。
5. 完整证据后只创建与 review/revision/decision/bundle 精确绑定的 approval 并暂停。当前类没有
   `resume()`，所以 `RunCoordinator` 只验证同 Run started/evidence/waiting-approval 持久序列。

## 修改文件

- `backend/app/advanced/review_runtime.py`
- `backend/app/advanced/review_tools.py`
- `backend/app/advanced/__init__.py`
- `backend/tests/test_review_runtime.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- 本 handoff

## 验证与失败尝试

- compileall：通过。
- 专项最终 10/10；Runtime/Tool/Security/Reliability/Vision/Browser/RAG 相关回归 147/147 通过。
- 首次专项因测试 fixture 使用同步 event sink 出现 5 个 error；改成 async sink 后通过，失败已记录在
  `V-20261021-006`。
- 沙箱内同步用例通过，但现有和新增 `IsolatedAsyncioTestCase` 都因 Windows sandbox socketpair 限制
  挂起；手动中断，相同异步测试在沙箱外通过。
- continuity 与 `git diff --check` 的最终结果记录在 `V-20261021-006`。

## 未验证范围

- 当前 Runtime 不实现 approval resume；拒绝、过期、grant 篡改和并发 resume 留给下一纵切。
- 尚未接持久 `ToolExecutionStore`、owner-scoped publication store CAS、result-unknown 权威对账和
  最终 `review.result`，不能声称副作用已执行或可跨重启恢复。
- 仍未定义 HTTP/Vue 形状或改变默认 Container/部署镜像；`KI-034` 保持 open，旧 capstone 文档未重写。
- 本轮无真实 Chromium 或在线 Provider 证据；既有 registry 与历史 M14 E3/E4 保持独立证据。

## 下一条原子动作

实现批准后的持久发布恢复链：

- 为 Runtime 增加受精确 approval 约束的 `resume()`，只执行当前审批绑定的 `publish_review`；
- 用持久 `ToolExecutionStore` 仲裁同键重放与并发 resume，publisher 最多进入一次；
- 实现 owner-scoped publication store 的 expected-revision CAS 和业务幂等查询；
- 对明确失败与 result-unknown 分流，unknown 只查权威记录、不自动重放；
- 覆盖缺失/拒绝/过期/篡改审批、重放、并发、取消和内容安全；仍不接默认 Container/API/UI。

没有新的在线授权。后续若在线模型能显著提升课程证据，必须先说明用途、模型、调用次数、计费口径
和停止条件，并重新取得单次授权；不能因为环境变量已有 Key 就直接调用。
