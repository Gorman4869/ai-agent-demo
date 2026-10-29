# M14-T6 本机PG组合部署交接

- M14-T6 / in_progress；A类部署/持久化/身份，C类本地Docker/Chromium；base HEAD `2129d0d`；
  V-20261029-006。工作开始Git干净；本轮所有变更均属本任务，未改学习者进度、依赖或远程Git。
- `review_demo.py`新增显式PG factory，共用合成registry和loopback限制；专用DSN_FILE、固定offline/
  manual，publisher使用同PG pool。普通应用身份/默认入口不变，固定reviewer不代表生产登录。
- 新增 `scripts/verify-review-deployment.ps1`、`frontend/playwright.review-postgres.config.ts` 与
  `frontend/tests/e2e/review-postgres.spec.ts`。使用缓存PG命名卷容器、本机后端/Chromium、Vue dist preview。
  没有安装Linux Chromium或构建完整backend/Nginx镜像。原M13部署脚本的migration期望从6修为8。
- 更新test_review_demo、后端规约、HTTP/启动/实施说明；新增ADR-0047和m14-review-deployment教程。
  KI-036记录迁移数/API文档漂移并关闭；KI-034材料仍open，KI-035未改。

## 命令与实际证据

1. frontend：`npm.cmd run test:unit; npm.cmd run build`，恢复15/15、类型和构建通过。
2. root：`python -B -m unittest backend.tests.test_review_demo backend.tests.test_review_application backend.tests.test_review_projection backend.tests.test_deployment_contract -q`，25/25。
3. frontend：`.\node_modules\.bin\playwright.cmd test --config playwright.review.config.ts`，原内存链1/1。
4. root：`.\scripts\verify-review-deployment.ps1`，组合E2E1/1（25.7s），SQL全部通过；截图已view_image检查。
5. 另外实测唯一guard标签网络：脚本拒绝接管、保留原网络、恢复环境，然后检查者清理自己创建的网络。

组合场景：三源证据→等待→终止/重开自己后端→刷新恢复同Run→批准→终止/重开后端→刷新恢复publication
版本2→重复审批409→同Run连续SSE。第二Run拒绝不发布；数据库2个spec/1条publication/6条evidence。
每次组合尝试均清理自建PG项目容器、网络、卷和临时连接文件。截图/test-results保持忽略，不提交生成物。
收尾continuity为52个稳定任务/202个Markdown，PowerShell Parser/diff通过；无M14资源或本次端口遗留，
原integration与M11两个PG容器仍healthy。资源guard实际调用先 `docker network create --label
com.docker.compose.project=$guardProject $guardNetwork`，再 `& .\scripts\verify-review-deployment.ps1
-ProjectName $guardProject`，捕获预期already-owns拒绝并核对网络仍在；finally仅删除刚创建的guard网络。

失败事实：前两轮StoreUnavailableError，定位为Windows Uvicorn默认Proactor与Psycopg异步PG不兼容，
命令显式 `--loop asyncio:SelectorEventLoop` 后解决；第三轮测试把UI短Run ID当全UUID，修正断言；
第四轮全链通过。guard首轮发现缺失环境变量被PowerShell恢复为空，改用移除Env项后通过。
重开后端时Vite的SSE ECONNRESET符合故障注入预期，后续snapshot/SSE已恢复；没有忽略未知故障。

没有重跑完整PG/全仓/完整M13容器门。没有在线模型、API Key使用、镜像拉取、Provider费用、生产身份、
PG重启、进行中工具hard-kill或HA证据。当前Windows/本机组合结果不能扩张为Linux全镜像兼容。

## 下一条原子动作

先阅读M14-T6 gap audit与现有capstone文档清单，按本轮实际链路更新作品集架构、可复现部署入口、
演示/故障脚本、评测与unknown成本、威胁模型、迁移说明和证据索引。复用现有材料，不重写已验收教程。
不要进入T7/T8；只有T6全部交付物和演练真实证据齐全才推进状态。不替学习者填写个人验收。

恢复最小门：上述第2条定向后端测试；修改运行路径时再执行组合脚本，纯材料整理不重复构建全套。
本机手动/自动命令与工作迁移见 `docs/m14-review-deployment.md`。未来如需完整Linux镜像，先提交可审查
方案，再单独取得浏览器安装/镜像下载等许可；不能把本轮“继续”扩张为在线模型或新依赖授权。
