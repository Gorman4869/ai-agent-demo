# M14-T6 多源证据审查四工具注册表交接

## 当前状态

- 当前任务：`M14-T6 / in_progress`。
- 合同：accepted `ADR-0044`；场景版本：`multisource-review-v1`。
- 本轮验证：`V-20261021-005`；验证基线：`9e34565`。
- 已实现独立四工具 registry、owner-scoped server-owned 资源目录、领域 evidence/result 类型和稳定失败码。
- 未接默认 `ApplicationContainer`、HTTP、Vue 或部署；没有读取 Key、调用 Provider/公网、运行真实
  Chromium/Docker、安装依赖或 push。

## 实现要点

1. `AsyncReviewToolRegistry` 用现有同步 `ToolRegistry` 做 schema、RBAC、工具可见性和精确审批 gate，
   再异步执行 Vision/Browser 等 handler；默认 registry 和旧 Runtime 行为不变。
2. `ReviewResourceCatalog` 是 immutable 且按 principal owner 隔离；工具参数只接受资源 ID，不能传
   图片路径/bytes、页面 URL/selector、owner、角色、Provider 或幂等键。
3. 三个只读工具分别真实调用 `MultimodalVisionAgent.inspect()`、`KnowledgeBase.search()` 和
   `BrowserAgent.run_with_driver()`；Vision/Page 原始内容与 RAG excerpt 不进入普通 repr。
4. `publish_review` 是 reviewer-only 高风险副作用，要求 Run identity 和一次性精确审批；命令绑定
   review/revision/decision/evidence digest，并由服务端派生隐藏业务幂等键。
5. 发布 timeout、I/O 和 `tool_result_unknown` 都标记结果未知；不得据此自动重放。当前 publisher 仅是
   注入协议与测试 fake，尚未实现持久 publication store 或权威对账。

## 修改文件

- `backend/app/advanced/review_tools.py`
- `backend/app/advanced/multimodal.py`
- `backend/app/advanced/__init__.py`
- `backend/app/reliability.py`
- `backend/tests/test_review_tools.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- 本 handoff

## 验证与失败尝试

- compileall：通过。
- 专项最终 15/15 通过；Tool/Security/Reliability/Vision/Browser/RAG 直接依赖回归最终 85/85 通过。
- 沙箱内专项在首个 async 用例前因 Windows socketpair 限制卡住，已中断；相同命令在沙箱外通过。
- 首次假定 `backend/pyproject.toml` 和 `requirements*.txt` 路径失败；仓库实际依赖文件为
  `backend/requirements-m2.txt`，未安装或修改依赖。
- continuity 与 `git diff --check` 的最终结果记录在 `V-20261021-005`。

## 未验证范围

- registry 尚不负责 same-Run provenance，也不执行 `max_tool_calls=4`、每工具一次、单副作用一次计数。
- 尚未生成 canonical evidence bundle，无法证明发布参数中的 digest 源自当前 Run 的三条实际 evidence。
- 尚未接 durable `ToolExecution`、publication store CAS、result-unknown 权威对账或重启恢复。
- 未定义最终 HTTP/Vue 形状，未改变部署镜像；`KI-034` 保持 open，旧 capstone 文档仍未重写。

## 下一条原子动作

实现显式注入的同 Run 离线 Runtime：

- 固定执行三个只读工具各一次，产出 image/policy/page canonical evidence bundle 和稳定 digest；
- 证明所有 evidence 绑定同一 principal/Run，且不可信视觉/网页/RAG 内容不能改写 decision、角色、预算、
  工具参数或审批；
- 强制四调用、每工具一次、单副作用一次预算；
- 第四步只形成 `publish_review` 的精确 approval request 并暂停，不在无审批时调用 publisher；
- 暂不接默认 Container/API/UI，不实现 PostgreSQL publication adapter，不运行 Provider。

没有新的在线授权。若后续真实在线视觉或公网演示能显著提升课程证据，必须先向用户说明目的、模型、
调用次数、计费口径和停止条件，并重新取得单次授权；不能因为环境中已有 Key 就直接调用。
