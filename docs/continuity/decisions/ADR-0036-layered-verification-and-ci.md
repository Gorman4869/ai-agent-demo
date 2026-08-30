# ADR-0036：分层验证、显式跳过与无密钥默认 CI

- 状态：accepted
- 日期：2026-08-30
- 任务：`M13-T3`
- 依赖：`ADR-0002`、`ADR-0005`、`ADR-0023`、`ADR-0035`

## 背景

旧 `scripts/verify.ps1` 把后端、代码 Agent、依赖、Vue、MCP 和 Compose 配置串成一条命令。
任一步失败会立即抛错，但 Docker CLI 缺失时只输出 warning，脚本末尾仍会打印统一成功文案。
PostgreSQL、pgvector、前端单测、Chromium E2E 和在线授权入口又分散在不同命令中，无法从一次
CI 结果判断哪些层实际执行、哪些层被跳过。

在线 Provider 还受 `ADR-0002` 的双重门和用户单次授权约束。把仓库 secret 直接注入普通 PR
工作流会扩大凭据暴露面，也会让默认 CI 依赖费用和外部可用性。

## 决策

### 1. 使用七个稳定验证层

统一入口固定为 `offline`、`mcp`、`postgresql`、`frontend`、`e2e`、`docker` 和 `online`：

- `offline`：完整后端离线 discovery、代码 Agent Demo 和 `pip check`；
- `mcp`：TypeScript Server 构建及本地 Python/TypeScript STDIO 集成；
- `postgresql`：真实 PostgreSQL Store 与 pgvector integration；
- `frontend`：Vitest 单元测试和 Vue 生产构建；
- `e2e`：真实本地 FastAPI、Vite 和 Chromium durable Run 场景；
- `docker`：主 Compose 与 integration Compose 的纯配置校验；
- `online`：仍委托独立在线脚本，并要求本次显式授权。

`default` 只展开为无数据库、无浏览器、无 Docker 的 `offline + mcp + frontend`。`integration`
是 `postgresql` 的稳定别名，`all` 展开七层；显式选择的非 online 层缺少工具或配置时必须失败，
不得自动降级为跳过。

### 2. 汇总是唯一最终结论

脚本为七层都输出 `PASSED`、`FAILED` 或 `SKIPPED`。首个 required layer 失败后停止执行后续
命令，但仍打印完整汇总；失败计数大于零时退出 1，且绝不打印全部通过。未选层、显式
`-SkipCompose` 和未获授权的 online 均必须带稳定原因显示为 `SKIPPED`。

只有零失败且零跳过时才打印全部所选 required layer 通过；存在跳过时只打印通过、跳过和失败
计数，避免把部分执行描述成完整发布门。

### 3. 默认 CI 不接收仓库密钥

GitHub Actions 使用只读 `contents` 权限，并把七层拆成独立 job。offline 的全量 backend
discovery 包含 TypeScript MCP E2E，因此干净 runner 先安装已锁定的 Node/MCP 依赖。
PostgreSQL job 只使用工作流内声明的 localhost trust 测试数据库；workflow 不引用 `${{ secrets.* }}`，也不使用
`pull_request_target`。online policy job 只证明无本次授权时得到显式 `SKIPPED`，不会传入
`-AuthorizedOnline`，不会读取 Provider Key 或发起在线调用。

真实在线验证继续由操作者在仓库外安全注入环境并取得单次授权后执行；普通 push、PR 和手动
默认 CI 都不能把仓库 secret 变成在线授权。

### 4. CI 配置和实际 CI 运行是两级证据

本地可以验证 profile 命令、失败/跳过语义、真实数据库、真实 Chromium 和 Compose 配置，
但 workflow 文件存在或静态检查不等于 GitHub runner 已执行。远程仓库未配置时 M13-T3 最高为
`code_complete`；只有远程 CI 的七个 job 产生可引用成功记录后才能标记 `verified` 并关闭
`KI-008`。

## 后果

- 开发者可以只运行修改面对应层，不再为一个前端问题隐式要求 PostgreSQL 或 Docker。
- 明确选择 `postgresql` 或 `docker` 时，缺少 DSN/CLI 会 fail closed；默认 profile 仍保持无
  Key、无 DSN、无 Docker 可运行。
- workflow job 可以并行，且每个失败都能定位到单一层；在线未授权是显式跳过而不是 Provider
  成功或失败。
- `docker` 当前只验证 Compose 展开，不构建镜像、不启动服务、不检查健康或 Nginx SSE；这些
  仍属于 M13-T4。

## 未采用方案

- 保留一个长脚本并用 warning 表示缺失工具：会继续产生部分门禁被误读为全部通过的问题。
- 在 PR workflow 注入 Provider secrets：扩大凭据和费用风险，也违反一次授权边界。
- 缺少 PostgreSQL DSN 时让显式 integration profile 退出 0：会把未运行数据库测试伪装成通过。
- 在 M13-T3 构建并启动生产 Compose：会提前进入 M13-T4 的 migration、health 和 Nginx 验收。

## 验证依据

- `backend/tests/test_verification_entrypoint.py`
- `scripts/verify.ps1`
- `.github/workflows/verification.yml`
- 本任务对应 verification 记录
