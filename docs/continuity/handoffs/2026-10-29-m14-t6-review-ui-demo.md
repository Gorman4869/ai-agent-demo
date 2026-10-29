# M14-T6 Vue审查与loopback演示交接

- M14-T6 / in_progress；A类前后端/审批恢复+C类本地Chromium；base HEAD `fd04c70`；验证V-20261029-005。
- 新增 ReviewWorkspace、review types/API、复用useAgentDesk与timeline、独立review Playwright config/E2E；
  后端review_demo和边界测试；文档新增ADR-0046和启动跟练，更新前后端连续性。
- 六字段创建走/api/durable/reviews；审批仍只提交decision。Review事件在API边界解析，composable
  应用严格sequence并在snapshot恢复review。mode为v1恢复记录的可选字段，旧记录兼容。
- 本地demo只合成资料和内存发布；固定reviewer由独立后端提供，限制loopback client/Host，无真实账号、
  凭据、个人数据或外部发布。普通应用鉴权不变；禁止将无登录demo直接部署公网。
- Vision Offline，Browser真实Playwright route fixture；CLI `python -B -m backend.app.review_demo`
  固定127.0.0.1:8000。前端按现有Vite启动，切“审查”；具体见docs/m14-review-demo.md。
- 恢复82/82；前端15/15、类型+build通过；后端相关17/17；真实审查E2E1/1，旧研究E2E2/2。
  首轮Vitest沙箱Temp rename EPERM且0项执行，沙箱外通过；保留故障事实，无新依赖。
- 桌面/390px截图已view_image检查，sources=3，publish版本2，移动端无横向溢出。
  截图位于忽略的frontend/test-results/review，不作为tracked源码提交。
- 未运行完整数据库或全仓门；没有Vue→PostgreSQL→真实Chromium组合部署证据。没有Provider/公网/
  账单证据；KI-034保持open，KI-035未改；未改学习者进度或push。
- 所有未提交变更属于本任务。文件范围见git status及验证日志，不包含生成dist/test-results。

## 恢复

frontend下：`npm.cmd run test:unit`、`npm.cmd run build`。
真实浏览器：`.\node_modules\.bin\playwright.cmd test --config playwright.review.config.ts`；自动启动两台
loopback服务并清理，使用现有Chromium，不会安装新依赖。普通研究回归使用原playwright.config.ts。

## 下一条原子动作

先检查现有deployment Compose/Dockerfile/Nginx与verify-deployment脚本，为作品集形成可复现组合部署：

1. 选择server-owned演示目录如何注入PostgreSQL factory与Chromium镜像。保留原M13部署默认路径。
2. 明确演示身份边界；review_demo的无登录固定reviewer只接受loopback，不适合直接置于docker proxy
   后冒充生产身份。不要把静态Bearer或模型Key打包前端，也不要将Host/client检查直接删除。
3. 验证同一部署的Vue创建→审批→publication→页面刷新、backend重开、PostgreSQL持久snapshot/SSE；
   实际构建/容器执行按既有外部门禁处理，不安装新依赖或调用Provider。
4. 然后更新作品集架构、演示、成本、威胁、故障、迁移与证据索引；不提前推进M14-T7/T8。

学习迁移和常见错误在docs/m14-review-demo.md；个人跟练勾选仍只由学习者写docs/progress.md。
