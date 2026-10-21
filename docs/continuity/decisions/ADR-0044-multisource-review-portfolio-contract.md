# ADR-0044：多源证据审查作品集合同

- 状态：accepted
- 日期：2026-10-21
- 任务：`M14-T6`
- 依赖：`ADR-0029`、`ADR-0031`、`ADR-0035`、`ADR-0037`、`ADR-0040`、
  `ADR-0041`、`ADR-0042`、`ADR-0043`
- 场景版本：`multisource-review-v1`

## 背景

M14-T1 至 T5 已分别证明受控 Browser、浏览器网络策略、视觉输入和固定评测，但这些能力仍是分离的
模块或命令。默认 `create_default_registry()` 只有加法、温度换算和明示为模拟的发布工具，不能满足
M14-T6“至少三个真实业务工具，其中至少一个副作用工具具备审批和幂等”的作品集门槛。

作品集选择“多源证据审查”作为业务纵切：内容审核人员针对一项待发布审查单，同时核对产品截图、
内部审查规则和受控网页事实，形成可追溯结论后再发布。该场景必须进入同一个 durable Run，不能用
四个互不关联的 Demo、第二个 Research Run 或历史评测报告拼接成完成证据。

本 ADR 只冻结业务、工具、数据、失败和验收合同，不实现 Runtime、默认 Container、HTTP、Vue 或
部署接线，也不授权新的在线模型、公网 Browser、依赖安装或 Provider 请求。

## 决策

### 1. 一个版本化请求只产生一个 owner-scoped durable Run

场景请求固定使用 `multisource-review-v1`，目标用户是具有 `reviewer` 角色的内容审核人员。可信应用层
从已认证 `Principal` 和 server-owned 资源目录构造请求，最小字段为：

| 字段 | 含义与边界 |
| --- | --- |
| `review_id` | 稳定、不含业务内容的审查单 ID；owner scope 只来自 `Principal` |
| `expected_revision` | 发布前的乐观并发版本，正整数 |
| `image_asset_id` | server-owned PNG 资产 ID；模型不能提供路径、URL 或图片 bytes |
| `policy_topic` | 有界审查主题；用于检索，不选择 owner、索引或 Provider |
| `page_fixture_id` | server-owned Browser fixture ID；模型不能提供 URL、selector 或脚本 |
| `requested_decision` | 仅允许 `approve`、`reject`、`needs_review` |

HTTP body、模型输出和工具参数都不能覆盖 owner、角色、真实资源位置、Provider、工具集合、发布目标或
审批绑定。输入通过既有 durable create 幂等门后，由同一个 `run_id` 承载四个工具的事件、审批、
`ToolExecution` 和最终结果。独立 `/api/research`、M14-T5 evaluator 与在线视觉 smoke 只可作为历史
证据引用，不能成为该 Run 的隐藏第二条执行链。

### 2. 四个工具均为真实领域适配器，参数保持最小且由服务端解析资源

| 工具 | 风险 | 模型可见参数 | 必须复用的真实边界 | 结果合同 |
| --- | --- | --- | --- | --- |
| `inspect_image` | 只读、低风险 | `image_asset_id` | server-owned asset catalog + `MultimodalVisionAgent`；先做 PNG guard，默认 `OfflineVisionModel` | 图片摘要、观察摘要、uncertainties、provider/model/offline、内容 digest；所有视觉内容保持 `untrusted_visual_data`、`can_authorize_actions=false` |
| `search_review_policy` | 只读、低风险 | `policy_topic` | 已注入 `KnowledgeBase.search()`，固定 owner-safe policy corpus | 最多 3 条 citation，含文档 ID、title、source、chunk、excerpt 和 score；只有实际返回的 evidence 可进入同 Run citation |
| `read_fixture_page` | 只读、低风险 | `page_fixture_id` | server-owned fixture catalog + `BrowserAgent.run_with_driver()` + `PlaywrightBrowserDriver` | 最终页面 digest、标题/正文的有界安全摘要、可见元素 ID 与 fixture evidence scope；不返回原始 HTML、截图 bytes 或 child output |
| `publish_review` | 副作用、高风险 | `review_id`、`expected_revision`、`requested_decision`、`evidence_bundle_digest` | owner-scoped publication store + ApprovalStore + 持久 `ToolExecutionStore` | `publication_id`、新 revision、published status、完整证据 bundle digest；不回显原始审批、幂等键或敏感证据 |

前三个工具必须调用上述领域模块，不能用常量 dict、预写结论或只构造对象冒充工具执行。
`read_fixture_page` 只允许读取，不开放 click/type/submit、下载、上传、弹窗或公网；若后续确需写页面，
必须另开 ADR 和审批策略。`inspect_image` 默认离线；历史 MiniMax E4 不自动进入作品集 Run。

工具定义不得替换或删除现有教学工具。作品集使用独立的显式 registry/runtime factory；在 API/UI
合同和回归完成前不接默认 `ApplicationContainer`。

### 3. 证据 bundle 和最终结果必须可由同一 Run 重建

三个只读工具每个最多产生一条 `review.evidence.recorded` 公开事件，统一字段为：

- `schema=review-evidence-v1`、`review_id`、`source_kind`、`source_ref`；
- `content_sha256`、`content_bytes`、`trust`、`status`；
- 可选的公开 citation 或安全摘要，不含图片 bytes、OCR 原文、完整页面正文、原始 prompt、工具参数、
  owner、Key、Cookie、DSN、异常文本或 Provider raw payload。

三条 evidence 按 `image -> policy -> page` 固定顺序 canonical JSON 编码，得到
`evidence_bundle_digest`。`publish_review` 的审批参数和业务写入必须绑定该 digest；缺少任一来源、来源
失败、顺序/内容改变、revision 或 decision 改变，都必须重新形成请求并重新审批，不能复用旧 grant。

最终 `review.result` 和 durable snapshot 的作品集扩展必须来自同一 Run 的持久事件，不重新读取当前
网页、知识库或图片。最小结果为 `review_id`、`scenario_version`、`outcome`、三条 evidence ref、
`evidence_bundle_digest`、`publication` 和 `usage`：

- `outcome=published`：发布记录与 `ToolExecution` 均已确认 completed；
- `outcome=needs_attention`：证据不完整、审批拒绝/过期或发布结果未知；
- `outcome=failed`：输入、策略、Store 或预算在产生可信结论前失败。

默认离线视觉与 fixture Browser 的 Provider usage/cost 保持 `null/unknown`，不得写成 0。只有本 Run
实际产生的 usage 事件可被投影；不得合并 M14-T4 历史 smoke usage。

### 4. 发布动作同时使用精确审批、业务幂等和持久执行仲裁

`publish_review` 固定 `allowed_roles={"reviewer"}`、`risk_level=HIGH`、
`has_side_effects=true`、`requires_approval=true`。应用层从可信 Run 状态生成 call ID 和参数，审批必须
绑定 principal、run ID、tool call ID、tool name 与完整 arguments digest，并维持单次消费。

业务幂等键不接收模型或客户端原文。应用层对
`scenario_version + owner_scope_digest + review_id + expected_revision + requested_decision + evidence_bundle_digest`
做 canonical digest，再以仓库既有密钥长度合同生成 server-owned key；原始 key 只在调用 Store 时短暂
存在，持久层只保存 digest。

执行顺序固定为：

1. 以业务幂等键创建 `ToolExecution(PENDING)`；同键、同参数重放返回既有记录，参数不同为冲突。
2. 未批准时转入 `WAITING_APPROVAL`，不得调用 publication adapter。
3. 批准后以 CAS 转为 `RUNNING`，publication store 以相同业务 key 和 `expected_revision` 执行一次写入。
4. 已确认写入后保存有界 result summary/digest 并转为 `COMPLETED`。
5. 明确失败转 `FAILED`；进程、timeout 或连接在副作用边界后中断则转 `UNKNOWN`，错误码
   `tool_result_unknown`。

`UNKNOWN`、timeout 或 I/O error 均不得自动再次调用发布 adapter。恢复只允许先按业务 key 查询权威
publication record：一致则把结果作为已完成事实投影；缺失或冲突则保持 `needs_attention`，交由人工
处理。该合同提供 at-most-once 调用与可对账恢复，不声称跨外部系统 exactly-once。

### 5. 稳定失败码、降级和停止规则

下一实现纵切必须把下列新码加入应用稳定错误目录；公开消息不带 ID、内容、URL、路径或异常文本：

| 失败码 | 含义 | Run 行为 |
| --- | --- | --- |
| `review_asset_not_found` | server-owned 图片或页面资源不存在/不属于 owner | fail closed，不调用后续工具 |
| `review_policy_no_evidence` | 规则检索没有达到最小一条证据 | `needs_attention`，禁止发布 |
| `review_page_changed` | fixture 观察与执行 digest 不一致或元素消失 | `needs_attention`，不自动重试/放宽范围 |
| `review_evidence_invalid` | evidence 结构、trust、数量或 bundle digest 无效 | fail closed，禁止审批和发布 |
| `review_revision_conflict` | `expected_revision` 已过期或幂等参数冲突 | `needs_attention`，要求重新读取和审批 |
| `review_budget_exceeded` | 场景调用、字节或时间预算耗尽 | fail closed，不扩大预算 |
| `tool_result_unknown` | 发布可能已发生但无法确认 | `needs_attention`，只允许对账，不自动重放 |

复用既有码：`invalid_arguments`、`approval_required`、`permission_denied`、`provider_*`、
`store_unavailable`、`store_operation_timeout`、`run_timeout` 和 `cancelled_by_user`。视觉 Provider 失败时
可以保留 PNG metadata 与明确 degraded observation，但 degraded 证据不能支持 `approve` 发布；请求
必须降为 `needs_review` 或停止发布。视觉文字、页面正文和 RAG excerpt 都是数据，任何“批准发布”、
“忽略规则”或工具指令都不能改变 decision、角色、工具参数、审批或 budget。

### 6. `multisource-review-v1` 预算不可由模型放宽

- 每个 Run 最多 4 次工具调用，每个工具最多 1 次；副作用调用最多 1 次。
- 图片最多 1 个，只接受 PNG，并完整复用 `PngLimits`；图片 bytes 不进入工具参数或事件。
- policy topic 最多 512 UTF-8 bytes，最多返回 3 条 evidence；无命中不得用模型常识补证。
- 页面最多 1 个 server-owned fixture、1 次 fresh Chromium context、1 次只读观察；无公网、用户
  profile、Cookie、upload/download 或 DOM 写动作。
- evidence bundle 必须恰好包含 image、policy、page 三个唯一来源；公开摘要与事件继续受现有有界
  JSON/输出限制。
- 场景总墙钟受 `Settings.budget.run_timeout_ms` 约束；视觉、Browser 和 Store 同时受各自更小的既有
  timeout。任何子预算或总预算先到即停止。
- 只读工具不做隐藏重试；发布工具永不自动重试。后续若为只读 adapter 增加重试，仍必须受 M13
  次数、deadline 和 cancellation 合同约束，且不能增加工具调用计数上限。

### 7. 离线实现与验收矩阵

默认验收保持 key-free、network-free（Browser 仅 route-fulfilled fixture）和零 Provider 请求。下一
代码纵切至少覆盖：

| 场景 | 必须证明 |
| --- | --- |
| 完整审查 | 四工具实际进入同一 durable Run；三条 evidence 形成唯一 bundle，批准后只发布一次 |
| 缺审批/拒绝/过期 | publication adapter 调用次数为 0，Run 可恢复且错误内容无敏感事实 |
| 审批参数篡改/旧 bundle | 精确绑定拒绝，旧 grant 不可消费 |
| 同键重放/并发重复 resume | 返回同一 publication；handler 最多执行一次 |
| 视觉提示注入 | 文字保持 `untrusted_visual_data`，不能改变 decision 或触发发布 |
| 视觉 Provider 降级 | 保留安全 metadata，但 `approve` 不可发布 |
| RAG 无证据 | `review_policy_no_evidence`，Browser/发布不会被伪造成成功 |
| 页面漂移/元素消失 | `review_page_changed`，不自动重试或扩大 origin |
| 发布明确失败 | `FAILED` 与稳定码可读，不生成 published 结果 |
| 发布结果未知与恢复 | `UNKNOWN` 后不自动重放；按业务 key 对账已存在/不存在两种结果 |
| 取消/预算耗尽 | 后续工具停止；已进入副作用边界时按 unknown 处理 |
| 内容安全 | Run/Event/ToolExecution/repr 不含图片、OCR、完整页面、Key、DSN、Cookie、原始幂等键或异常 |

内存 adapter 可用于确定性单元测试；要声称可复现部署与重启恢复，必须再用 PostgreSQL
`RunStore/EventStore/ApprovalStore/ToolExecutionStore` 和持久 publication store 完成集成验证。真实
Chromium仍是本地 E3；在线视觉、Provider usage/费用和公网 Browser 必须使用独立、重新授权的 E4，
不能成为本纵切的默认通过条件。

## 后果

- M14-T6 有了唯一业务目标、四工具边界、同 Run 结果、失败语义和可执行验收清单，后续实现不会把
  分离 Demo 或模拟发布包装成作品集。
- 作品集 registry/runtime 与默认教学链隔离，降低在接口未稳定前破坏 M1–M13 行为的风险。
- 发布动作新增一个真正的业务持久化事实；最终部署验收需要 PostgreSQL publication adapter 和迁移，
  不能只凭内存测试关闭 `KI-034`。
- 当前 ADR 本身不让“真实工具”门槛从 missing 变为 complete；只有代码、测试、同 Run 证据、API/UI
  和部署复验逐步完成后才可关闭 `KI-034`。

## 未采用方案

- 直接把现有加法、温度转换和模拟发布改名：没有真实领域调用链，也无法满足业务验收。
- 让模型提供图片路径、任意 URL、selector、知识库 ID、owner 或幂等键：会把不可信数据升级为控制面。
- 把视觉/RAG/Browser 分别跑完后由文档合并：没有同 Run 的持久事件、审批和恢复证据。
- 视觉 fallback 后仍批准发布：把未知视觉事实伪装成完成证据。
- 对 result-unknown 发布自动重试：可能产生重复外部副作用；必须先查权威业务记录。
- 在本 ADR 同时修改 Container、API、Vue、Docker 或调用 MiniMax：扩大原子任务，且越过依赖和在线
  授权门。

## 验证依据

- `docs/m14-production-portfolio-gap-audit.md`
- `backend/app/advanced/multimodal.py`
- `backend/app/advanced/browser_agent.py`
- `backend/app/knowledge/rag.py`
- `backend/app/tools/registry.py`
- `backend/app/domain/run.py`
- `backend/app/stores/tool_execution.py`
- `V-20261021-004`
