# M14-T6 作品集材料交接

- M14-T6 / in_progress，B类纯材料整合（30–90分钟）；base HEAD `d847c77`；V-20261029-007。
  初始Git干净，所有未提交变更均属本轮文档；没有改运行代码、依赖、部署脚本或学习者progress。
- 先恢复25项，再按实际review_demo、Runtime、工具、snapshot与历史V证据改写材料，不因历史摘要重造实现。
- 重写 `docs/capstone-architecture.md` 与 `docs/capstone-demo-script.md`，新增
  `docs/m14-portfolio-report.md`；更新M7/M14阶段页、gap audit历史定位、implementation plan与连续性文件。
  无新ADR，延续0044–0047。KI-034材料漂移修正，工程演练/交付核对仍open；其它既有问题未改。

## 验证

root运行（用本地.venv）：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_review_demo backend.tests.test_review_application backend.tests.test_review_projection backend.tests.test_deployment_contract -q
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_review_runtime.MultisourceReviewRuntimeTest.test_result_unknown_without_record_is_terminal_and_not_replayed backend.tests.test_review_tools.ReviewToolContractTest.test_changed_evidence_digest_cannot_reuse_publish_approval -v
./.venv/Scripts/python.exe -B -m backend.app.evals.advanced_agent
```

分别25/25（0.763s）、2/2（0.141s）、默认offline 7/7预期匹配；task success3/7、安全4/4、审批fixture1/7、
9步，usage/cost为空。没有新业务失败；既有Starlette/httpx弃用提示仍保留，未安装建议的替代库。
标准库一次性引用检查对6份材料的11个V编号与11个Python模块/类/方法做存在性核对，代码围栏成对；
continuity与diff通过。Mermaid图作源码/边界复核，没有安装渲染器或声称图形渲染已测试。
收尾52个稳定任务/204个Markdown，所有本轮链接有效；已检查目标材料中过期持久化/上传/重编码陈述无残留。

本轮没有PG/Browser/全仓门、模型请求、Key使用、价格查询、镜像下载或视频录制。相关PG/Chromium链
引用V-20261029-006，并非本轮再次执行；当前报告明确把M Plan历史522 Token和review unknown分开。
没有push、修改个人progress或代替真人答辩。材料写全不等于T6工程演练已经执行。

## 下一条原子动作

按20分钟脚本做T6工程演练与最终交付核对，使用现有依赖和本机隔离PG/Chromium链：

1. 先核对演示请求/证据/审批/发布归属；内存交互和独立PG场景分别登记Run，不拼接证据。
2. 执行 `./scripts/verify-review-deployment.ps1` 与脚本中的精确故障命令，记录新V编号及实际SQL、
   重启与清理结果；PG脚本仅操作自建唯一project，缺缓存/环境时如实停在未验证范围，不安装。
3. 核对九类产物、部署、成功/拒绝/unknown和残余风险，决定T6工程状态；不要提前做T7的30项终审。
4. 录像、真人答辩与个人学习勾选是单独事实，不从自动化通过推断，也不替用户填写progress。

纯材料修订只需文档检查；若进入本次下一步的正式工程演练，按其风险运行实际命令，不能引用旧结果
伪装成当轮实证。默认无Key/离线，无新的Provider、Linux依赖或公网部署授权。
