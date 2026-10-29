# 多源审查 HTTP 读取合同

依据：ADR-0044。应用显式注入 Review Runtime 后，继续复用 durable Run 的 owner scope 与持久事件。

## 已实现接口

| 接口 | 合同 |
| --- | --- |
| `POST /api/durable/reviews` | 仅 create_review_app 显式注册；已认证 reviewer + Idempotency-Key，六字段请求，202 返回同一 durable Run |
| `GET /api/durable/runs/{run_id}` | 既有 snapshot 新增可空 `review`，身份和 owner 校验沿用现有实现 |
| `POST /api/durable/runs/{run_id}/approvals/{approval_id}` | body 仍仅为 `decision: approve/reject`；服务端从既有等待事件恢复完整绑定；响应包含同一 review 投影 |
| `GET /api/durable/runs/{run_id}/events` | 仍为同一 Run 的 SSE history；review.evidence.recorded 与 review.result 沿用 ADR-0044 事件 |

没有有效 review evidence 的普通 Run 返回 `review=null`。review 包含 scenario_version、review_id、outcome、
evidence、evidence_bundle_digest、publication 和 usage。evidence 仅公开 source_kind/ref、digest、bytes、
trust/status 与有界 citation_refs。投影不回显图片/OCR、网页、RAG 原文、审批参数或幂等键。

| outcome | 条件 |
| --- | --- |
| in_progress | 已有证据，Run 尚在执行 |
| waiting_approval | Run 正在等待既有精确审批 |
| published | 三条有序同 review evidence 形成完整 bundle；review.result 的 digest/ref 匹配，publication 合法且 Run completed |
| needs_attention | 拒绝、过期、结果未知、revision conflict、缺规则、页面变化、取消，或 completed Run 没有可信 published 结果 |
| failed | 其他终态失败，如预算或证据错误 |

不完整 evidence 的 bundle digest 为 null。无匹配发布事实时 publication 为 null；不得通过 answer 文本
或当前资源重建发布结果。无效事件不覆盖此前合法投影；不同 Run 的事件不参与投影。
当前场景仅支持离线 unknown usage：provider/total_tokens/estimated_cost/currency 为 null，cost_source
为 unknown。后续在线 usage 必须另有本 Run 的已验证合同，不能混入历史 smoke。

## 显式内存创建

`backend.app.advanced.review_application.create_review_app(registry=..., authenticator=...)` 接受服务端已装配
的四工具 registry，创建独立内存 composition。默认 create_app 不开启该入口。

请求示例：

```json
{
  "review_id": "review-1",
  "expected_revision": 3,
  "image_asset_id": "hero-image",
  "policy_topic": "review disclosure",
  "page_fixture_id": "policy-page",
  "requested_decision": "approve"
}
```

缺认证 401，缺 reviewer 403，缺/非法 Idempotency-Key 400；额外控制字段或非法业务字段 422。
同一 owner/key/六字段重放返回原 Run，任一业务字段变化 409。资源存在性由 owner-scoped 工具目录
检查，缺资产 Run 安全失败。创建后使用返回的 id 查询、订阅 SSE、提交审批；无需另建第二条执行链。

当前 HTTP factory 的 spec 仍在进程内。ADR-0045 和 migration 8 已另行提供私有 PostgreSQL request
Store，将 Run、counter、六字段 spec 原子创建，并通过两个独立 PID 验证 resolve/replay。原始 spec
不进入事件或 answer。该 Store 尚未接 HTTP factory；async approval、完整 PostgreSQL composition 和
Vue 仍待实现。下一步先完成后端接线，再接 Vue 创建/证据/审批视图。

真实业务映射：审核页面刷新后通过 snapshot 恢复证据和结论，SSE 负责增量展示。常见错误是把 completed
等同 published，或用当前网页重新拼历史 evidence。排查时核对同 Run 事件、bundle digest 与既有错误码。

验证入口：`python -B -m unittest backend.tests.test_review_application backend.tests.test_review_projection -v`；
fixture HTTP 证据见 `V-20261029-001/002`。本材料不声称 PostgreSQL 创建、Vue 页面或部署验收已完成。
