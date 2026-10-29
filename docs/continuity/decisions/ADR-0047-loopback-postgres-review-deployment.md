# ADR-0047：本机 PostgreSQL 审查组合部署

- 状态：accepted
- 日期：2026-10-29
- 任务：M14-T6
- 依据：ADR-0037/0044/0045/0046

## 决策

新增显式 `create_postgres_demo_review_app`，只读取 `AI_AGENT_REVIEW_DEMO_DSN_FILE` 指定的连接文件，
通过固定offline/manual Settings装配现有PG review应用。同内存入口共用合成资料目录与loopback
client/Host限制；固定reviewer仍只用于本机教学，不修改普通应用身份，不将它变成代理后的生产身份。

本轮复现采用宿主机Python/已安装Chromium、构建后的Vue `dist`与loopback Vite preview，以及既有
deployment Compose的PostgreSQL服务/密码secret/命名持久卷。只启动postgres，不启动或重构原M13的
backend、seed或Nginx。选择该路径是为了复用已安装运行时，不在没有许可时下载Linux Chromium或安装包。

`scripts/verify-review-deployment.ps1` 创建唯一 `ai-agent-demo-m14-*` 项目，拒绝同标签既有容器、卷或
网络；`--no-build --pull never`只使用缓存PG镜像。临时密码/DSN写仓库外文件，环境只传路径，结束时
清理本次资源并恢复环境。已有项目不能被验证脚本接管或清理。

浏览器测试拥有独立后端进程，在等待审批与已发布两个稳定点分别重开，再刷新同一页面。Windows
显式使用Uvicorn公开的 `--loop asyncio:SelectorEventLoop`，匹配Psycopg异步连接要求；不修改全局策略。
三个证据工具照常真实执行，Vision保持离线。发布与私有spec使用同一PostgreSQL persistence。

## 边界

- 这是可复现的本机组合部署，不是完整Docker backend/Nginx镜像、生产登录、HA或公网安全证据。
- Vite preview只是本机演示静态产物与同源代理。不能作为公网生产Web服务，也不能转发此固定身份给其他用户。
- 终止后端发生在已持久等待/终态，没有证明进行中工具hard-kill；PG服务本身未重启。
- 命名卷在验证过程中承载恢复事实；脚本最终删除自建卷以隔离下一次验证，不保留真实业务数据。
- 如果未来需要完整Linux镜像，再单独确认浏览器运行时、镜像构建/下载与身份方案，不借此默许安装。

验证：V-20261029-006；两次后端进程重启、审批重复409、拒绝不发布、SQL事实与资源归属检查。
