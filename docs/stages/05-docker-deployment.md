# 第 5 阶段：Docker 构建与最小部署

## 目标与边界

本练习把 FastAPI 与 Vue 分成两个可独立构建的容器：后端运行 Uvicorn，前端由 Nginx 托管静态文件并把 `/api`、`/health` 同源代理到后端。默认继续使用内存 Mock，不读取模型密钥，也不启动 PostgreSQL、Redis 或 pgvector。

## 启动

先确认 Docker Desktop 已启动，然后在项目根目录运行：

```powershell
docker compose -f deploy/compose.yaml config
docker compose -f deploy/compose.yaml up --build
```

打开 `http://127.0.0.1:5173`。如需直接查看 FastAPI 文档，可访问 `http://127.0.0.1:8000/docs`。

停止服务：

```powershell
docker compose -f deploy/compose.yaml down
```

## 健康检查

```powershell
docker compose -f deploy/compose.yaml ps
curl.exe http://127.0.0.1:5173/ui-health
curl.exe http://127.0.0.1:5173/health
curl.exe http://127.0.0.1:8000/health
```

`/ui-health` 只验证 Nginx；前端入口的 `/health` 经 Nginx 验证后端；Compose 还会使用镜像内置的健康检查，并等待后端健康后再启动前端。

## 配置与密钥

默认端口是前端 `5173`、后端 `8000`，可在当前终端临时覆盖：

```powershell
$env:FRONTEND_PORT = '8080'
$env:BACKEND_PORT = '8081'
docker compose -f deploy/compose.yaml up --build
```

Compose 不声明 `OPENAI_API_KEY`，也不挂载 `.env`。当前应用路径不需要真实模型；以后接入供应商时，应通过部署平台的 Secret 功能注入，并确保缺失密钥时明确失败，不能把密钥写入镜像、Compose 或 Git。

## 为什么这样拆分

| 组件 | 构建与运行 | 责任 |
| --- | --- | --- |
| `backend.Dockerfile` | Python 3.12 + Uvicorn | API、SSE、内存 Mock、后端健康检查 |
| `frontend.Dockerfile` | Node 构建阶段 + Nginx 运行阶段 | 生成静态资源，不把 Node 工具链带入运行镜像 |
| `nginx.conf` | Nginx 8080 | SPA fallback、同源 API 代理、关闭 SSE 缓冲 |
| `compose.yaml` | 两个服务 | 构建、端口、启动依赖和最小权限 |

后端和前端运行文件系统均设为只读，只给临时目录提供 `tmpfs`；容器移除 Linux capabilities，并启用 `no-new-privileges`。这能减少误写和提权面，但不替代生产环境的 TLS、身份认证、限流与集中日志。

## 验收清单

1. `docker compose ... config` 可无密钥展开。
2. 两个镜像可在没有本地 `.venv`、`node_modules` 的干净环境完成构建。
3. `docker compose ... ps` 显示两个服务为 `healthy`。
4. 浏览器能装载资料、运行 SSE 时间线并得到研究结果。
5. 镜像历史、Compose 配置和浏览器响应中不出现密钥。

## 常见错误

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 无法连接 Docker API | Docker Desktop 未启动 | 启动 Docker Desktop 后重试 |
| `npm ci` 或 `pip install` 失败 | 注册表网络不可用 | 检查代理与 DNS，不要改成未锁定依赖 |
| 前端 502 | 后端未健康或已退出 | 查看 `docker compose ... ps` 与后端日志 |
| SSE 最后一次性显示 | 反向代理启用了响应缓冲 | 保留 `/api/` 下的 `proxy_buffering off` |
| 端口被占用 | 本机已有 5173/8000 进程 | 临时设置 `FRONTEND_PORT`、`BACKEND_PORT` |

## 必做练习

1. 修改宿主端口并证明容器内部端口不变。
2. 暂时破坏后端健康检查路径，观察前端的启动依赖，再恢复配置。
3. 使用 `docker compose ... config` 检查最终配置中是否含有意外环境变量。
4. 解释为什么本阶段没有加入 PostgreSQL/Redis，以及何时才值得加入。
