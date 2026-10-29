# 多源审查 HTTP 读取合同

依据：ADR-0044。应用显式注入 Review Runtime 后，继续复用 durable Run 的 owner scope 与持久事件。

## 已实现接口

| 接口 | 合同 |
| --- | --- |
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

## 后续创建与页面接线

review create 和 opt-in composition 尚未实现。下一步从已认证 reviewer 与 server-owned 目录构造
ADR-0044 的六个业务字段，绑定到同一 durable Run 的 request digest 和持久配置；不能由通用 message
解析控制字段。须先解决跨进程可信 Run spec 恢复和 async approval 接线，再接 Vue 创建/证据/审批视图。

真实业务映射：审核页面刷新后通过 snapshot 恢复证据和结论，SSE 负责增量展示。常见错误是把 completed
等同 published，或用当前网页重新拼历史 evidence。排查时核对同 Run 事件、bundle digest 与既有错误码。

验证入口：`python -B -m unittest backend.tests.test_review_projection -v`；fixture HTTP 证据见
`V-20261029-001`。本材料不声称创建接口、Vue 页面或部署验收已完成。
