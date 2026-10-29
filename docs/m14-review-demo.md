# 多源审查：本地启动与跟练

先在两个 PowerShell 终端分别启动。使用仓库现有依赖与已安装的 Playwright Chromium，无需模型 Key。

后端（在仓库根目录）：

```powershell
.\.venv\Scripts\python.exe -B -m backend.app.review_demo
```

前端：

```powershell
Set-Location D:\Demo\vue-theory-demo\ai-agent-demo\frontend
npm.cmd run dev -- --host 127.0.0.1
```

打开 <http://127.0.0.1:5173>，切换到“审查”，保留预填的六个业务字段，点击“启动审查”。
等待三条证据和 publish_review 审批卡出现，刷新页面；批准后会显示发布编号与版本2，再次刷新仍是同一 Run。
若测试拒绝，请在发布前选择“拒绝”；结果应为“需要人工处理”，没有已确认发布记录。

预填目录：review=`demo-review`，revision=1，image=`demo-image`，page=`demo-page`，topic=`review disclosure`。
“拟定结论”是业务请求，不能替代后续精确人工审批。图片是64×32合成PNG；离线观察不判断实际产品质量。
规则来自本地 KnowledgeBase，网页由真实 Chromium 读取受控 fixture。用量和费用保持未知。

此独立入口没有登录，服务端只给 loopback 请求提供合成 reviewer；发布只写内存，不关联真实账户或外部目标。
不要将它转发或部署到公网。普通应用与 PostgreSQL factory 的身份边界不变，见 ADR-0046。
停止后端后内存清空；再次启动可从revision1重新演示，旧页面恢复记录遇404会按既有规则清理。

普通“研究”模式请使用原后端启动入口。审查入口只装配审查 Runtime，不把普通消息解析为审查请求。
默认后端没有开启审查创建时，页面会显示404错误；请按上面的显式入口启动。

## 验证与排错

```powershell
# 在 frontend 下执行（命令会自启独立测试后端和Vite）
.\node_modules\.bin\playwright.cmd test --config playwright.review.config.ts
npm.cmd run test:unit
npm.cmd run build
```

- 缺 Node/已安装的 Chromium：按项目已有安装流程处理，不会静默下载或自动改依赖。
- `review_revision_conflict`：核对当前发布revision，重新确认业务字段和审批；不要循环重放发布。
- `tool_result_unknown`：停止自动发布，查同一 Run 的 ToolExecution/publication；前端不把它显示成已发布。
- 跨进程数据库恢复使用 create_postgres_review_app，见 m14-review-api-contract；本教程仅内存演示。

真实工作映射：后台内容审核可通过相同创建、证据、审批、快照/SSE流程恢复页面。常见错误是把拟定结论
当审批、把completed当published，或刷新后重新创建一个Run。实践时核对Run ID、三源摘要和发布revision。
验证记录：V-20261029-005；没有在线模型、真实账户、公网访问或实际部署证据。
