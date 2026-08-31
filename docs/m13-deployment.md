# M13 Docker、pgvector 与 Nginx 实际部署

本页是 M13-T4 的单机部署和验收入口。它不代替生产 TLS、Secret Manager、备份、高可用、
容量测试或线上 Provider 验收。

## 组件和启动顺序

```text
pgvector healthy
  -> knowledge-seed 完成 knowledge migration + 幂等课程 seed
  -> backend healthy，应用 migration 完成
  -> frontend/Nginx healthy
```

部署使用 `deploy/compose.deployment.yaml`，默认只监听本机：

| 服务 | 默认宿主机端口 | 说明 |
| --- | ---: | --- |
| frontend/Nginx | 15173 | UI、`/health` 和 `/api/` 反向代理 |
| backend | 18000 | 只用于本机诊断；正常访问走 Nginx |
| pgvector | 55434 | 部署数据库；不占用 M11 integration 的 55433 |

backend 与 seed 固定 `manual + mock + offline embedding`，因此部署验收不需要任何模型 Key，
也不会产生 Provider 费用。Node 22 只存在于 frontend Docker build stage；不要求切换本机 NVM
版本。

## Secret 边界

Compose 要求调用进程提供以下两个仓库外 secret 文件路径：

- `AI_AGENT_DEPLOY_POSTGRES_PASSWORD_FILE`：PostgreSQL 密码文件；
- `AI_AGENT_DEPLOY_POSTGRES_DSN_FILE`：backend/seed 使用的完整容器内 DSN 文件。

两者只进入 Docker runtime secret，不应写入仓库 `.env`、Compose、文档、截图或 Git。应用侧
通过绝对路径 `AI_AGENT_POSTGRES_DSN_FILE=/run/secrets/postgres_dsn` 读取 DSN；直接 DSN 与文件
来源同时配置时 fail closed。

推荐使用下方验收脚本。它在系统临时目录生成两个一次性随机 secret 文件，只把路径传给
Compose，并在结束时逐个删除；它不读取用户 `.env`，也不要求手工填写真实密码。

## 一次完整验收

执行前确认 Docker Desktop 已启动，并取得本次镜像下载、构建、容器和临时卷操作授权：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify-deployment.ps1
```

脚本依次完成：

1. 校验 Compose，拒绝复用已有同名 project；
2. 构建 backend/frontend 镜像，启动独立 pgvector、seed、backend 和 frontend；
3. 检查 `/ui-health`、Nginx `/health` 和 backend `/health`；
4. 检查 6 个应用 migration、1 个 knowledge migration、课程 seed 和 vector extension；
5. 在两个独立测试库运行完整 PostgreSQL Store 与 pgvector integration；
6. 通过 Nginx 创建 durable Run，并实际读取 `run.started`、`run.completed` SSE；
7. 重启 backend，确认同一 Run 仍可从 PostgreSQL 恢复；
8. 删除且只删除本次唯一 project 的容器、网络和卷，保留构建镜像。

脚本默认 project 为 `ai-agent-demo-m13-<PID>-<随机后缀>`。如需在失败后人工检查，可显式使用
`-KeepRunning`；此时资源不会自动清理，操作者必须使用输出中的精确 project name处理，不能对
其他 Compose project 执行 down。

端口冲突时可显式指定三个本机端口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify-deployment.ps1 `
  -FrontendPort 25173 `
  -BackendPort 28000 `
  -PostgresPort 25434
```

## 通过标准

只有以下证据全部实际成功，M13-T4 才能标记 `verified` 并关闭 `KI-009`：

- backend/frontend 镜像实际 build；
- 四个服务满足健康或成功退出合同；
- 应用和 knowledge migration、seed、pgvector extension 数量正确；
- 两组真实数据库集成测试通过；
- Nginx 返回实时 SSE started/completed；
- backend 重启后 durable Run 仍为 completed；
- 验证 project 完成清理，现有 M11 integration 容器未受影响。

Compose `config --quiet`、静态测试或镜像构建单独成功都不是完整部署证据。

## 保留边界

- PostgreSQL 使用本地命名卷和密码鉴权，但没有 TLS、备份恢复、高可用、外部 secret manager、
  监控告警或生产容量证明。
- pgvector 中的课程 seed 是离线三维部署检查数据；默认 Agent Context 仍使用进程内 Knowledge，
  不能宣称主链已经切换为持久 RAG。
- Nginx 只验证本机 HTTP 反向代理与 SSE buffering；没有域名、证书、WAF、限流或公网暴露。
- backend 重启恢复不等于宿主机故障、数据库损坏、连接结果未知或多实例竞争验证；这些风险继续
  由相应 known issue 跟踪。
