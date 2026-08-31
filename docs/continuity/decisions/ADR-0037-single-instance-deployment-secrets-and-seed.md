# ADR-0037：单实例部署、运行时 Secret 与显式 Knowledge Seed

- 状态：accepted
- 日期：2026-08-31
- 任务：`M13-T4`
- 依赖：`ADR-0023`、`ADR-0033`、`ADR-0036`

## 背景

M13-T3 只验证两份既有 Compose 可以展开，没有构建镜像、启动服务、执行 migration/seed、
检查健康、通过 Nginx 读取 durable SSE 或证明 PostgreSQL 重启恢复。M11 的
`deploy/compose.integration.yaml` 又是 localhost、trust、tmpfs 的测试数据库，不能被描述为部署
配置，也不能因 M13 验收而改变其既有集成测试合同。

部署时还需要同时向 PostgreSQL 传入密码和向后端传入 DSN。把任一值写进 Compose、源码、
文档或命令输出都会扩大凭据暴露面；只支持普通环境变量又会把完整 DSN直接放进容器环境。

## 决策

### 1. 新增独立的单实例部署 Compose

`deploy/compose.deployment.yaml` 使用独立 project name，包含固定版本 pgvector、一次性
`knowledge-seed`、FastAPI backend 和 Nginx frontend。PostgreSQL 使用命名持久卷，所有宿主机
端口只绑定 `127.0.0.1`；应用容器保持非 root、只读根文件系统、`no-new-privileges` 和 capability
drop。

M11 的 integration Compose 保持不变。部署验收使用唯一的 `ai-agent-demo-m13-*` project，不能
复用、停止或清理现有 `ai-agent-demo-integration` 容器和 55433 端口。

### 2. Secret 只从运行时注入

Compose 的 `postgres_password` 与 `postgres_dsn` 都来自操作者指定的仓库外 secret 文件，
调用进程环境只传文件路径，不在仓库保存 secret 值。PostgreSQL 使用 `POSTGRES_PASSWORD_FILE`；后端 Settings 新增
`AI_AGENT_POSTGRES_DSN_FILE`，与直接 `AI_AGENT_POSTGRES_DSN` 互斥。

DSN 文件只在显式 `AI_AGENT_PERSISTENCE=postgres` 时读取，必须是绝对路径、UTF-8 且非空。
读取失败只返回稳定的无内容配置错误；Settings repr、JSON 和安全摘要继续隐藏 DSN。

### 3. Knowledge migration/seed 使用一次性显式任务

应用启动继续负责既有 `app_schema_migrations`；独立 `knowledge-seed` 服务复用
`PgVectorKnowledgeBase.initialize_schema()` 与 `seed(DEMO_COURSE_DOCUMENT)`，固定离线三维
Embedding，并在成功退出后才允许 backend 启动。

该任务是显式、幂等、无在线 Provider 的初始化命令。FastAPI import/lifespan 不隐式写知识库，
也不把 pgvector 接入默认 Context 主链；部署库存在课程向量不能被描述为主 Agent 已使用持久
RAG。

### 4. 健康、SSE 与恢复组成一条实际部署证据链

backend 使用 `/health` 容器健康检查；frontend 只有在 backend healthy 后启动，并通过
`/ui-health` 检查 Nginx。Nginx `/api/` 保持 HTTP/1.1、关闭 proxy buffering/cache，并保留
长连接 timeout；后端 SSE 继续返回 `X-Accel-Buffering: no`。

`scripts/verify-deployment.ps1` 在唯一 project 中实际 build/up，检查两个 migration 命名空间、
课程 seed、vector extension、Nginx SSE 的 started/completed 事件和 backend 重启后的 Run 恢复。
PostgreSQL Store 与 pgvector 集成测试使用同一临时容器中的两个独立测试数据库，不能清理部署
库。

### 5. 验证资源必须可证明归属

验证脚本只接受 `ai-agent-demo-m13-*` project name；默认生成 PID 加随机后缀。脚本在系统临时
目录创建两个随机文件，并在结束时逐个删除；不递归删除目录。结束时只对该 project 执行
`down --volumes --remove-orphans`，不删除镜像，也不操作其他 Compose project。操作者显式传入
`-KeepRunning` 时只保留容器和卷供检查，临时 secret 文件仍会删除，已启动容器继续使用 Docker
挂载的 secret。

## 后果

- 部署路径默认使用 mock model、offline Embedding，不读取 Provider Key、不访问在线模型。
- 实际验收需要 Docker Engine；缺失 Engine 或镜像/依赖下载失败时只能记为失败或
  `code_complete`，不能关闭 `KI-009`。
- 部署 Compose 提供单机持久卷、健康顺序和运行时 secret，但不提供 TLS、外部 secret manager、
  备份、高可用、滚动升级或生产容量结论。
- 验收脚本会构建本地镜像并创建临时容器、网络、数据库和卷；因此执行前仍需用户对本次外部
  下载和有状态操作明确授权。

## 未采用方案

- 修改 M11 integration Compose：会混淆 tmpfs/trust 测试数据库与部署合同，并可能破坏已有
  55433 集成环境。
- 把 DSN 或密码写入 `.env`/Compose：会让秘密进入工作树、日志或 Git。
- 在 backend 启动时自动 seed：隐藏写副作用，也无法把 migration/seed 失败与应用健康清晰分开。
- 直接在部署库运行既有数据库集成测试：测试会 TRUNCATE/DROP 表，可能删除 migration、Run 和
  knowledge seed。
- 用 Compose 配置成功代替实际 build/up：不能证明镜像依赖、容器权限、健康、SSE 或重启恢复。

## 验证依据

- `backend/tests/test_deployment_contract.py`
- `backend/tests/test_deployment_seed.py`
- `backend/tests/test_settings.py`
- `scripts/verify-deployment.ps1`
- 本任务对应 verification 记录
