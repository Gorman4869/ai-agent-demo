# 多源审查：本机 PostgreSQL 组合部署

本实验将构建后的Vue、真实FastAPI/PG应用、受控Chromium和PostgreSQL发布记录连成一条链。
适合复现后台审核的“刷新与后端重启后继续审批”，使用合成资料，不需要模型Key。

## 一条命令复现

前提：仓库既有 `.venv`、`frontend/node_modules` 与Playwright Chromium已安装，Docker Desktop运行中，
本机已有 `pgvector/pgvector:0.8.1-pg17` 镜像。脚本不会下载缺失镜像、执行npm install或安装浏览器。

在仓库根目录运行：

```powershell
.\scripts\verify-review-deployment.ps1
```

端口默认Vue15174、后端18082、PostgreSQL55435；占用时用 `-FrontendPort`、`-BackendPort`、
`-PostgresPort` 指定三个不同空闲端口。所有HTTP/数据库端口仅绑定127.0.0.1。

脚本依次启动唯一项目中的缓存PG镜像和命名卷，构建Vue，再让Playwright运行完整场景。它会：

1. 创建审查，读取图片、规则与受控网页的三条证据，进入等待审批。
2. 终止并重开自己启动的后端，刷新页面，核对同一Run和原证据后批准。
3. 再次重开后端，核对同一发布编号、版本2与连续SSE；重复审批返回409。
4. 新建第二个Run并拒绝人工审批，确认没有新增publication。
5. 查询数据库确认8条迁移、2个私有请求、1次发布、revision2与6条evidence事件，最后清理自建资源。

成功输出以 `[review-deployment] PASSED` 开头。截图位于忽略目录
`frontend/test-results/review-postgres/published-after-restart.png`。脚本退出后不会保留演示服务或数据。

## 运行位置与身份

| 部分 | 本实验位置与边界 |
| --- | --- |
| Vue | 本机Vite preview服务构建后的dist，通过同源代理访问API；不使用开发页冒充构建产物 |
| FastAPI | 本机独立PG review factory；不使用内存Run/spec/publication |
| Vision/RAG | OfflineVisionModel与内存合成规则库，重启按同一目录装配；不是在线视觉或向量检索质量证据 |
| Browser | 后端启动真实Playwright Chromium，仅读取server-owned route fixture，禁止公网/上传/下载 |
| PostgreSQL | 既有deployment Compose中的密码secret和命名卷，保存Run/spec/审批/事件/ToolExecution/publication |
| 身份 | 固定合成reviewer，仅本机client和Host；不打包静态Bearer到前端，也不模拟生产登录 |

此入口不得通过代理提供给其他用户。普通应用鉴权和原M13容器链保持独立。完整Linux
backend/Nginx/Chromium镜像没有在本轮构建；这里的可复现证据限于上表组合。

若手动为自己的**隔离合成数据库**提供连接文件，显式启动命令为：

```powershell
$env:AI_AGENT_REVIEW_DEMO_DSN_FILE = 'C:\your-private-directory\local-demo-dsn.txt'
.\.venv\Scripts\python.exe -B -m uvicorn backend.app.review_demo:create_postgres_demo_review_app --factory --host 127.0.0.1 --port 18082 --loop asyncio:SelectorEventLoop --no-proxy-headers --no-access-log
```

请使用仓库外绝对路径；不要把DSN内容放入源码、控制台或Git。自动验证不需要手工准备该文件。
手动演示发布后revision已推进，重开factory不会把数据库head重置为1；下一次请求须使用当前revision。

## 排错与迁移练习

- `StoreUnavailableError`：先检查本次PG服务健康、连接文件与端口；Windows还须使用上面的Selector循环。
- `already owns resources`：脚本拒绝复用旧项目。使用默认随机project，不要为了验证删掉已有项目。
- 重启时SSE出现ECONNRESET：本实验主动停止后端会断开连接；恢复后通过snapshot/SSE读取原Run，不再创建一条替代。
- revision冲突或结果未知：沿同Run的ToolExecution/publication查事实，不循环批准或自动重放发布。

工作映射：把页面sessionStorage当作恢复坐标，把数据库事件当作事实。先写下原Run ID与publication ID，
再解释为什么后端重启后仍能继续审批，以及为什么“completed”不能单独证明发布成功。
移植到公司项目时优先替换真实身份与server-owned资源目录，保留精确审批、版本CAS和结果未知对账合同。

证据：V-20261029-006、ADR-0047。没有在线Provider、真实费用、生产账户、PG重启、HA或进行中工具hard-kill证据。
