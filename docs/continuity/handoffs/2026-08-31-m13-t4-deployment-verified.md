# M13-T4 交接：Docker、pgvector 与 Nginx 实际部署验收通过

- 日期：2026-08-31，Asia/Shanghai
- 完成任务：`M13-T4 / verified`
- 验证基线：`15fdf2b6ae7d20127f31b705d566fa8876a1122f`
- 验证记录：`V-20260831-003`
- 关联决策：`ADR-0037`
- 在线模型/付费调用：未执行，费用 0

## 本轮结果

新增独立单实例部署 Compose、运行时 secret 文件、显式 pgvector migration/seed 和隔离验收脚本。
最终随机 project `ai-agent-demo-m13-31796-2e35bbd1` 实际 build/up，PostgreSQL、seed、backend、
frontend/Nginx 全部满足健康或成功退出合同；120 项 PostgreSQL/pgvector 集成、Nginx durable SSE
started→completed 顺序和同一个 backend 容器 restart 后的 Run 恢复通过。

最终清理只删除该 project 的容器、网络和卷，保留构建镜像。只读复核没有任何
`ai-agent-demo-m13-*` 资源；既有 `ai-agent-demo-integration-postgres-1` 继续在
`127.0.0.1:55433` healthy。

## 修改文件

- 配置/镜像：`deploy/compose.deployment.yaml`、`deploy/backend.Dockerfile`、
  `backend/.env.example`、`backend/app/settings.py`。
- 显式初始化：`backend/app/deployment_seed.py`。
- 验收入口：`scripts/verify-deployment.ps1`。
- 测试：`backend/tests/test_deployment_contract.py`、
  `backend/tests/test_deployment_seed.py`、`backend/tests/test_settings.py`。
- 决策/说明/规约：`ADR-0037`、`docs/m13-deployment.md`、
  `BACKEND_CODING_STANDARDS.md`。
- 连续性：实施计划、verification、known issues、status 和本 handoff。
- 未修改 `docs/progress.md`，学习者个人进度保持不变。

## 实际验证

| 命令/范围 | 结果 |
| --- | --- |
| `./.venv/Scripts/python.exe -B -m unittest backend.tests.test_deployment_contract backend.tests.test_deployment_seed backend.tests.test_settings -q` | 33 项通过 |
| PowerShell parser 检查 `scripts/verify-deployment.ps1` | 通过 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify-deployment.ps1`（最终） | build/up、migration/seed、健康、120 项 DB、Nginx SSE、restart recovery、清理全部通过 |
| 同一部署脚本内 PostgreSQL/pgvector integration | 120 项通过；保留既有不可达连接 timeout 日志 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify.ps1`（沙箱外） | backend 681 项通过/1 项既有 symlink skip；MCP 11 项、Vue 12 项和 production build 通过 |
| `powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/check-continuity.ps1`（代码文档阶段） | 52 个稳定任务、153 个 Markdown 文件通过；连续性闭环后需再跑 |
| Docker 资源只读复核 | 无 M13 容器/卷/网络；既有 55433 integration healthy |

## 保留的失败与修复

1. 首次 build 成功后，Compose runtime 拒绝 `secrets.environment`，本机只支持 `file`；改为仓库外
   临时 secret 文件和路径环境变量，finally 逐文件删除。
2. 第二次 seed 成功但 backend unhealthy；有界日志定位到镜像漏复制根目录 `skills/`，补入只读
   Skill 目录。
3. 四服务 healthy 后，PowerShell 把 `/ui-health` 的 `ok` 加换行误判为失败；规范化文本后通过。
4. 初版 restart 等待调用第二次 `compose up`，会因镜像元数据 recreate；最终改为 restart 后只
   轮询 backend/Nginx 健康，证明同一容器恢复。
5. 最终脚本首次复跑的 120 项中，一条 recovery 子进程因 psycopg rollback stderr/timeout 失败；
   相同最终脚本重跑后 120 项全部通过。失败不删除，后续若复现应按 `KI-016` 继续调查。
6. 完整默认门在沙箱内因 Windows temp ACL 和 MCP 子进程权限失败；相同命令在沙箱外完整通过。

## 边界

- 临时密码和 DSN 从未写入仓库、测试固定值、文档或 Git；没有读取用户 `.env` 或 Provider Key。
- Docker 首轮经授权下载固定基础镜像并在镜像内安装现有锁定依赖；未修改依赖或 lockfile。
- 部署只证明本机单实例 HTTP/pgvector/Nginx；没有 TLS、备份、高可用、外部 secret manager、
  生产容量或公网入口。
- pgvector seed 是离线三维课程数据；默认 Agent Context 仍为进程内 Knowledge，不能描述为主链
  已使用持久 RAG。
- 本轮构建镜像保留；验证容器、网络、卷均已清理。

## 下一条原子动作

恢复 M13-T5：只读审查 ControlledCodeAgent 的子进程启动、stdout/stderr 缓冲、timeout/cancel、
环境 allowlist、审计和 Windows 进程树边界，再确定流式有界输出与整棵进程树清理的最小纵切。
未经新授权不升级依赖、不读取 Key/用户 `.env`、不执行在线调用或 push。

## 交接时工作区

本 handoff 创建时 M13-T4 实现与连续性文件尚未提交；分支 `main` 在 `origin/main` 之上已有本地
M13-T3 文档提交 `15fdf2b`。结束前只提交本任务文件，不 push；新 HEAD 由后续状态或 handoff
补记。
