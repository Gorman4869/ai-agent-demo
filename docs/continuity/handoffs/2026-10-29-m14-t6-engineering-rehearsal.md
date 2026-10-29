# M14-T6 工程演练与交付收尾

- 当前M14-T6 / verified（工程范围），非accepted/个人通关；base HEAD `9469c11`；V-20261029-008。
- A类工程验收+C类本机PG/Chromium；依照ADR-0044–0047和20分钟脚本执行自动工程步骤。工作开始Git
  干净；不改运行代码、依赖、架构决定或个人progress。本轮变更仅连续性、报告索引与脚本一句档位说明。
- 九类作品集交付物和同Run真实四工具/审批幂等均核对；KI-034关闭。工程通过不代替真人部署/答辩，
  无新视频或个人考核记录。T7/T8尚未执行；KI-035等既有缺口未改。

## 实际命令

root，用已有.venv：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_review_demo backend.tests.test_review_application backend.tests.test_review_projection backend.tests.test_deployment_contract -q
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_review_tools backend.tests.test_review_runtime backend.tests.test_review_publication backend.tests.test_review_request_store backend.tests.test_advanced_agent_eval -q
./.venv/Scripts/python.exe -B -m backend.app.evals.advanced_agent
./.venv/Scripts/python.exe -B -m backend.app.evals.advanced_agent --browser-driver playwright-fixture
./scripts/verify-review-deployment.ps1
```

frontend下：`npm.cmd run test:unit`，以及
`.\node_modules\.bin\playwright.cmd test --config playwright.review.config.ts`、
`.\node_modules\.bin\playwright.cmd test --config playwright.config.ts`。

结果：25/25 + 56/56后端；15/15前端；内存审查1/1（12.2s）、研究2/2（8.6s）、PG组合1/1（32.3s）。
组合脚本内Vue类型/构建通过；两档固定评测同7案例/digest，预期7/7、completed3/7、安全4/4、审批fixture1/7，
usage/费用null。没有新业务失败，只有既有弃用/颜色提示与主动停止后端时的SSE ECONNRESET。

收尾continuity为52个稳定任务/205个Markdown，链接/diff通过。外层首次用 `$LASTEXITCODE` 判断没有
native退出码的PowerShell检查脚本，误抛异常；改用即时 `$?` 后整条检查退出0，未改脚本或重跑业务测试。

PG project为 `ai-agent-demo-m14-29400-e695ffc4`，已自动清理。两次重开后端恢复同Run和publication；
重复审批409，第二Run拒绝不发布；SQL迁移8/spec2/publication1/revision2/completed publish1/evidence6。
桌面PG与390px内存PNG已view_image检查，均三源、版本2、无明显显示问题；生成物保持忽略。
清理后无M14容器/卷/网络，7个测试端口无监听，原integration/M11两个PG容器healthy。

没有全仓/完整PG套件或完整M13容器门的新结果，没有新Provider/Key使用、安装/拉取、配额/价格查询、
PG重启、进行中工具hard-kill、HA、生产身份、视频录制或push。各档位实证不混用。

## 下一条原子动作

只读做终审前依赖核对，不直接启动T7/T8：

1. KI-037：T7写“M8–M14所有任务达到门槛”，T8又依赖T7，存在字面循环。先对照已接受设计与计划，
   明确应检查哪些前置项，不能静默改合同或把T8当作已完成。
2. 确认M11-T8的交付缺口；M11-T1–T7已有工程证据，但T8材料/验收尚未启动。
3. 确认M8在线门仍code_complete、未有新的单次授权；只核对已有记录，不读取Key/尝试Provider。
4. 形成后续顺序；不要把个人progress作为可代填的工程状态，不重复已通过T6门。当前任务保留T6
   verified供恢复，后续任务与优先级以依赖核对结果和用户指令决定。

最小恢复：`git status --short`、continuity及V-20261029-008；只读依赖核对不需要重跑PG/Browser。
若后续改运行路径或进入真正新验收，再按对应范围运行必要测试。
