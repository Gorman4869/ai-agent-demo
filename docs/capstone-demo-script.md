# 多源证据审查演示脚本（20分钟）

脚本面向录制与答辩，时间为讲解预算，不是实测时延或SLA。当前提供脚本与可复现命令，
不表示已经产出视频、完成真人演练或替学习者通过考核。
架构见[架构图](capstone-architecture.md)，论据见[作品集报告](m14-portfolio-report.md)。

## 演示前准备

1. 读取[状态](continuity/status.md)和最新verification，核对当前代码与命令档位。
2. 确认既有.venv、Node、frontend依赖、Playwright Chromium与缓存PG镜像存在；不现场自动安装。
3. 只使用合成资料。录制应用窗口与安全汇总，关闭密钥、DSN文件、环境变量、raw异常和个人资料页面。
4. 先预测正常与拒绝/unknown的结果，再执行。准备一张空白记录表：本段Run ID、来源数、审批结果、
   publication ID/revision、对应V编号；不记录原始capability、幂等键或私有topic。
5. 恢复最小门可运行25项审查/投影/部署合同测试，命令见[最近交接](continuity/handoffs/2026-10-29-m14-t6-postgres-review-deployment.md)。
   不把本轮纯文档检查说成新一轮PG/Browser实证，也不为录制重复运行全仓。

交互段使用内存入口，在仓库根目录的两个PowerShell终端运行：

```powershell
# 终端1
./.venv/Scripts/python.exe -B -m backend.app.review_demo
```

```powershell
# 终端2
npm.cmd --prefix frontend run dev -- --host 127.0.0.1
```

打开http://127.0.0.1:5173，切“审查”。默认六字段与预期见[本地跟练](m14-review-demo.md)。
此段固定reviewer无登录，后端停止会丢失内存记录；不要在此段用重开内存后端演示PG持久恢复。
组合PG段用不同端口与独立Run，讲解时重新登记该段证据，不能拼接成同一次运行。

## 时间安排与讲解提示

| 时间 | 执行/展示 | 必须讲清的结论 |
| --- | --- | --- |
| 0:00–2:00 | 说明运营审核业务、六字段请求和四工具 | 目标是有证据且经过批准的审查记录；离线视觉不判定真实产品质量 |
| 2:00–4:00 | 展示架构和执行档位 | 本例PG在容器，后端/Chromium/preview在本机；不是原M13全容器链 |
| 4:00–8:00 | 交互页启动→三源→等待→刷新→批准→published | 同一Run ID、来源数3、精确人工审批、publication与revision2；拟定结论不代替审批 |
| 8:00–11:00 | 运行下方PG组合脚本，查看安全汇总与生成截图 | 自动化用另一个独立Run完成两次后端进程重启；PG持久化而不是页面内存制造恢复 |
| 11:00–13:00 | 定位组合测试的重复审批409、第二Run人工拒绝 | 一次publication；拒绝不发布；第二Run只验证失败分支，不凑同Run来源 |
| 13:00–15:00 | 运行结果未知/换证据审批两项故障合同 | UNKNOWN不能重放，换digest不能复用审批；这是离线注入合同，不是工具执行中OS强杀 |
| 15:00–17:00 | 运行固定评测、展示成本表 | 7/7预期匹配不等于成功率7/7；当前Run usage未知，历史522 Token单独归属 |
| 17:00–19:00 | 展示威胁表与迁移清单 | 图片/网页/RAG是数据，Principal/审批是控制面；公司业务先替换身份和目录 |
| 19:00–20:00 | 回答追问并列出残余边界 | 生产登录、完整Linux镜像、进行中工具hard-kill、价格/容量都不能从本例推定 |

PG组合段从仓库根目录运行：

```powershell
./scripts/verify-review-deployment.ps1
```

按[部署说明](m14-review-deployment.md)选择不同空闲端口。脚本只启动自己的隔离项目，最终删除自己的
数据库卷和临时连接文件；原项目不会被复用。不要为了展示打开DSN。其自动化场景见
[review-postgres.spec.ts](../frontend/tests/e2e/review-postgres.spec.ts)。
截图路径为 `frontend/test-results/review-postgres/published-after-restart.png`，需先执行命令生成，
不是Git中预录成功的替代品。

## 两项精确故障合同

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_review_runtime.MultisourceReviewRuntimeTest.test_result_unknown_without_record_is_terminal_and_not_replayed backend.tests.test_review_tools.ReviewToolContractTest.test_changed_evidence_digest_cannot_reuse_publish_approval -v
```

预期两项通过：缺失权威publication时保持UNKNOWN且不再调用publisher；修改evidence digest时原审批
不能使用。进一步的PG双进程对账看V-20261023-001，页面真实进程重开看V-20261029-006。
不能把上述离线测试描述成这两种外部环境实证。

固定评测命令：

```powershell
./.venv/Scripts/python.exe -B -m backend.app.evals.advanced_agent
```

默认Browser不启动进程；如果另行展示真实fixture Chromium档位，按[评测文档](m14-advanced-agent-evaluation.md)
显式传 `--browser-driver playwright-fixture`。保持同dataset/digest；任何在线视觉仍需新的单次授权，
演示脚本不会调用带Authorized的在线命令。

## 遇到异常时怎么讲与怎么查

先记录用户现象和本段Run ID，再检查snapshot终态/sequence、审批与ToolExecution、权威publication，
最后判断是创建、工具、Store还是SSE层。诊断使用稳定错误码，不打印连接串或raw异常。

- Windows PG后端health不就绪：确认连接文件/PG健康，再核对Selector循环；见[实际复盘](m14-portfolio-report.md)。
- SSE因计划重开后端出现ECONNRESET：恢复后读原Run，不重新发布，不隐瞒故障注入。
- 没有规则/资产或bundle不一致：停止形成发布结论；回到服务端目录/原证据排查，不放宽校验。
- 无publication且结果未知：保留人工处理，不能现场换key重跑来制造成功。
- 镜像/Chromium不存在：报告缺失环境，保留可检查的脚本；不临时下载或用离线Fake冒充浏览器实证。

## 答辩追问与结束条件

1. 页面保存了Run ID，为什么还需要数据库私有spec？——ID只是坐标，resume需要可信的六字段绑定，
   不能从模型输出或新表单重建。
2. 三源证据都存在为什么仍不能显示已发布？——还需要精确审批、ToolExecution和匹配bundle的权威publication/终态投影。
3. 拟定结论reject与拒绝审批有什么区别？——前者可被批准发布为拒绝结论，后者不允许发布动作执行。
4. 为什么只需一次业务写入却还要处理UNKNOWN？——写入提交与收到响应不是同一件事，重复执行可能扩大副作用。
5. 为什么不再申请一个Key把本例变成在线？——在线质量是另一个需授权的实验；本轮要证明审批/恢复合同，不借用历史调用。
6. 怎样迁移到公司CMS？——先验证真实身份、server-owned资料ACL、Publisher幂等/查询和结果未知语义，再做发布目标适配。

结束时检查：每段Run归属明确；成功/拒绝/unknown均有对应证据；未知费用没有补0；
生成物和连接文件没有进Git；对未运行的完整容器链或真人演练明确保留范围。
学习者应脱离脚本复述后再自行记录 `docs/progress.md`，工程提交不替代个人训练。
