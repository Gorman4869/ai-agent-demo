# 多源证据审查作品集报告

本文把业务、成本、安全、故障和迁移放在同一证据口径下。运行说明见[本机PG部署](m14-review-deployment.md)，
架构见[capstone architecture](capstone-architecture.md)，录制与答辩流程见[20分钟演示](capstone-demo-script.md)。
工程状态只写[status](continuity/status.md)，个人训练仍由学习者填写 `progress.md`。

## 业务问题与可展示结果

目标用户是运营或内容审核人员：发布审查结论前，需要核对截图、内部规则和页面事实，并保留谁批准了
哪一组证据的记录。作品集使用合成商品资料，不接真实客户、个人账号或外部内容发布系统。

请求为 `multisource-review-v1` 六个业务字段，详见[HTTP合同](m14-review-api-contract.md)。拟定结论由请求
明确给出；Runtime固定执行图片→规则→网页，检查证据完整性与绑定，随后等待精确人工审批。它没有让
离线视觉模型自动决定业务结论，也不声称能解决开放域事实冲突。

| 工具 | 实际调用 | 展示什么 | 实现位置 |
| --- | --- | --- | --- |
| inspect_image | MultimodalVisionAgent + OfflineVisionModel | PNG检查、不可信结构化观察、安全摘要 | [review_tools](../backend/app/advanced/review_tools.py) |
| search_review_policy | InMemoryKnowledgeBase.search | 本地合成规则的真实检索，最多3条引用 | [demo corpus装配](../backend/app/review_demo.py) |
| read_fixture_page | BrowserAgent + PlaywrightBrowserDriver | 真实Chromium读取server-owned网页，全部route fixture | [browser driver](../backend/app/advanced/browser_driver.py) |
| publish_review | PostgresReviewPublicationStore | 精确审批后真实写PG审查记录与revision；业务幂等/CAS | [publication adapter](../backend/app/advanced/postgres_review_publication.py) |

四个工具属于同一durable Run。前三个证据形成有序bundle digest，发布绑定该digest。
数据库发布记录是真实副作用；PNG/规则/网页为合成资料，Vision为离线模型，两者不能混写成真实产品质量证明。

## 交付物与证据索引

所有V编号均可在[verification log](continuity/verification-log.md)检索；表内是各次已记录的历史证据，
不是每次阅读本文都会重新运行的结果。测试或执行档位不同的行不合并计算通过率。

| 交付项 | 产物/实现 | 对应证据与边界 |
| --- | --- | --- |
| 场景与四工具 | 本报告、[ADR-0044](continuity/decisions/ADR-0044-multisource-review-portfolio-contract.md) | V-20261021-005/006、V-20261022-001：同Run证据、精确审批与发布仲裁 |
| 架构与所有权 | [架构图](capstone-architecture.md)、[私有request ADR](continuity/decisions/ADR-0045-private-review-request-storage.md) | V-20261029-003/004：Run/spec原子创建与PG应用重开恢复 |
| 可复现部署 | [部署命令](m14-review-deployment.md)、[ADR-0047](continuity/decisions/ADR-0047-loopback-postgres-review-deployment.md) | V-20261029-006/008：Vue dist+本机后端/Chromium+PG容器；两次后端进程重启 |
| 演示视频脚本 | [20分钟流程](capstone-demo-script.md) | 提供录制步骤和预期，不冒充已有视频、真人答辩或本轮重新执行的录屏 |
| 固定评测 | [M14-T5报告](m14-advanced-agent-evaluation.md) | V-20261021-001/002：同dataset的offline/Playwright fixture对照 |
| 成本 | 下节的范围/公式/已知覆盖率 | V-20261020-005：独立单次M Plan usage；当前review usage仍unknown |
| 威胁模型 | 下节的输入、控制面和副作用表 | test_review_tools/runtime/projection与ADR-0040–0047；不扩大为公网审计 |
| 故障复盘 | 下节的Windows启动与重启恢复 | V-20261029-006：失败尝试、根因、最小修正和复验均保留 |
| 迁移说明 | 下节的研究助手→审查助手清单 | [M12迁移合同](m12-api-migration.md)、六字段create与可空review投影 |

工程演练记录为V-20261029-008：重新执行了审查合同、Vue单元/浏览器、PG组合与两档固定评测，
对应同Run发布、重复审批拒绝、人工拒绝及UNKNOWN合同。具体命令、通过数、Run归属、清理与未运行
范围只记录在verification log，不把本报告或脚本当成真人演讲、已有视频或个人通关证据。

关键可复现门如下，均从仓库根目录运行；只需现有依赖：

```powershell
# 工具/Runtime安全与恢复合同（默认离线）
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_review_tools backend.tests.test_review_runtime backend.tests.test_review_projection -q
# 固定评测；不启动真实Browser、不调用Provider
./.venv/Scripts/python.exe -B -m backend.app.evals.advanced_agent
# 本机PG/真实Chromium全链，命令会创建并清理自己的隔离项目
./scripts/verify-review-deployment.ps1
```

精确单项入口可选择
`backend.tests.test_review_runtime.MultisourceReviewRuntimeTest.test_result_unknown_without_record_is_terminal_and_not_replayed`
验证结果未知不重放，或
`backend.tests.test_review_tools.ReviewToolContractTest.test_changed_evidence_digest_cannot_reuse_publish_approval`
验证换证据不能复用审批。它们是离线合同测试，不是新Provider或完整OS崩溃实证。

## 评测与成本

| 范围 | 可引用数据 | 不能推导什么 |
| --- | --- | --- |
| M14-T5 fixed dataset | 7/7匹配预期、3/7 completed、4/4安全命中、1/7需审批fixture、9个计划步骤 | 7/7不是任务成功率；1/7不是真人介入率；时延不是生产SLA |
| M14-T6 PG组合案例 | 一个批准Run、一个拒绝Run；两个后端重启点；最终只有1条publication、6条evidence | 不是大样本评测、HA、多用户并发容量或PG重启 |
| M14-T4单次MiniMax | 历史input479/output43/total522，M Plan；独立授权已用完 | 不能累加到review Run，不能换算PAYG现金账单或推导套餐剩余 |
| 本机review Run | provider/total_tokens/estimated_cost/currency为null，cost_source=unknown | 无在线调用不等于整套系统运行成本为0；离线元数据不是模型质量分数 |

容量和成本先写变量，再代入业务测量，不填未经验证的现价：

```text
每日审查量 N = 平均每秒审查量 × 86400（仅适用于全天稳定流量）
服务并发预算 ≈ 峰值到达率 × 实测p95服务秒数 × 余量系数
每日事件字节 ≈ N × 每Run事件数 × 平均事件字节
PAYG模型成本 = N × (平均输入Token × 输入单价 + 平均输出Token × 输出单价)
人工成本 = N × 实测需人工介入比例 × 平均操作工时 × 单位工时成本
```

单价必须统一为“每Token”，并附Provider、模型、计费方式、币种和价格版本/日期。M Plan不能直接套用
PAYG公式。当前缺生产Token分布、可信费率、真人工时和硬件费用，故不填写现金总额。
部分Run费用已知时，只报告已知子集之和与覆盖率 `费用已知Run数 / 总Run数`；未知项不按0补齐。
逐调用硬成本门、版本化定价和完整账本仍按 `KI-018` 跟踪，不能拿预算配置存在代替执行证据。

## 威胁模型与残余风险

| 边界/资产 | 威胁 | 已有控制与定位 | 残余边界 |
| --- | --- | --- | --- |
| HTTP请求→身份/spec | body伪造owner、role、URL或工具 | Principal来自服务端；严格六字段、owner目录、canonical request digest；test_review_application | 本机固定reviewer无生产登录/撤销能力；同机身份隔离不是本例目标 |
| 图片→视觉观察 | 图片文字冒充审批；畸形图片 | PNG guard与untrusted_visual_data/can_authorize_actions=false；test_multimodal_agent、test_review_tools | guard不等于完整decoder、重编码、metadata剥离或扫描器 |
| policy检索→证据 | 恶意规则指令、无证据仍发布 | server-owned合成corpus；有界citation；无证据停止；test_review_tools/runtime | 不是生产文档ACL或向量检索质量证明 |
| 网页计划→Browser进程 | SSRF、重定向、页面漂移、任意脚本 | exact origin、完整计划绑定、地址分类、route fixture、页面digest；test_browser_network/driver | 未开放任意公网、个人profile或真实DNS/TLS；应用策略不等于OS沙箱 |
| 证据→审批 | 换decision/revision/digest后复用grant | principal/run/call/tool/arguments完整绑定、单次消费、执行时复核；test_review_tools/runtime | 人工可误判业务事实，审批不能保证证据内容真实 |
| 发布→数据库 | 重复写入、版本竞争、连接断开后误重试 | ToolExecution CAS、业务幂等、revision锁与事务；UNKNOWN只查权威publication | 无跨系统分布式事务或任意外部发布目标的exactly-once承诺 |
| EventStore→SSE/UI | 乱序、重连重复、把answer冒充发布事实 | 严格sequence、持久snapshot、有序bundle验证；test_review_projection、前端unit/E2E | SSE只是观察；snapshot失败不能编造成功或创建替代Run |
| DSN/部署资源 | 凭据进前端/日志；清理到旧项目 | 文件secret、白名单输出、唯一project、既有资源拒绝、环境恢复；V-20261029-006 | 未提供生产Secret Manager、备份加密、保留期与租户审计方案 |

公开事件/snapshot只含受审查的摘要、引用ID和发布元数据；私有 `review_run_requests.policy_topic` 是数据库内
明文业务字段，不能把“日志不记录”说成“系统完全不存内容”。数据库权限、备份与保留期仍需另行设计。

## 实际故障复盘

主要事件为本机PG应用首次启动失败，发生于组合验证环境，没有真实业务用户影响。

| 阶段 | 可观察事实 | 处理与复验 |
| --- | --- | --- |
| 发现 | 前两次组合脚本退出1，后端health未就绪；安全诊断StoreUnavailableError | 保留失败，不把构建成功当部署成功；不输出DSN/原始异常 |
| 定位 | 本地Uvicorn在Windows默认Proactor；Psycopg异步连接明确不支持该循环 | 对照安装源码与既有PG probe的Selector用法；未改全局策略或装库 |
| 修正 | 启动命令显式 `--loop asyncio:SelectorEventLoop` | 第三次已进入审查/重开/恢复审批；随后测试暴露UI缩写ID断言错误 |
| 测试修正 | 页面RUN只显示前8字符，测试错误要求完整UUID | UI保持现有显示；完整ID由HTTP snapshot比对，修正测试后全链通过 |
| 收尾 | 两个稳定点重开、SSE恢复、publication=1；guard保留旧资源 | guard另发现缺失变量被恢复为空；改为移除Env项后复验通过，自建资源全部清理 |

此复盘的步骤顺序来自V-20261029-006，没有可用的生产MTTR/停机时长或事故工单，不补造分钟数。
等待审批/发布终态重开后端，与“工具执行中强杀后自动恢复”不同；后者仍看 `KI-016`。

结果未知的排查顺序：停止自动发布→确认同Run与ToolExecution→按相同业务key查权威publication→有一致记录
则对账，无记录/不可用则保留UNKNOWN与人工处理。不要换新key再次发布，也不要改事件把它补成成功。
PG双进程对账引用V-20261023-001；本机UI重启演示引用V-20261029-006，两类实证分开使用。

## 从研究助手迁移到审查助手

| 层 | 保留 | 替换/增加 | 验收与撤回方式 |
| --- | --- | --- | --- |
| 前端 | Fetch封装、useAgentDesk、SSE/recovery与审批卡 | 六字段审查表单、三源卡片、review投影；保留研究模式 | 普通Run的review=null；关闭新入口可继续研究，不删除原主链 |
| API | durable owner/idempotency/cancel/approval合同 | 显式POST /api/durable/reviews，不从message或模型输出猜spec | 同owner/key同请求重放，字段变更409；默认app不注册创建路由 |
| 数据 | Run/Event/Approval/ToolExecution | migration7的publication/head；migration8私有request，创建同事务 | 保留审计数据；撤回入口不drop表、不重编号迁移、不改写历史事件 |
| 工具/资源 | ToolRegistry最终授权与工具预算 | 注入真实截图/规则/受控页面目录和Publisher | 先替换只读目录与测试；外部发布先验证幂等/查询/unknown语义再接入 |
| 身份 | server-owned Principal/owner绑定 | 公司验证过的登录/session或身份adapter | 禁止复用本机固定reviewer作为生产身份；不把静态Token打包进Vue |
| 部署 | 原M13服务与既有secret模式 | 本例单独loopback组合入口 | 普通应用不自动启用；Linux浏览器镜像/公网服务需独立方案与验证 |

迁移顺序：先保留兼容入口→验证只读证据→验证精确批准/拒绝→验证revision冲突/unknown→验证同Run刷新与
后端重开→最后才考虑真实身份、资源与发布目标。不要用新的Research请求覆盖旧Run结果。
业务已发布后撤回页面功能，不会撤销数据库发布事实；需要业务撤销时应另设计新的受审批动作。

## 答辩自检

用5分钟解释：为什么恢复需要私有spec和事件两个事实源；为什么拟定结论reject与人工拒绝审批不同；
为什么UNKNOWN不能自动重试；为什么历史522 Token不属于本Run；为什么本机PG组合部署仍不是生产登录。
再按[20分钟脚本](capstone-demo-script.md)脱离本文完成演示。个人完成情况只写 `progress.md`，本报告不代填。
