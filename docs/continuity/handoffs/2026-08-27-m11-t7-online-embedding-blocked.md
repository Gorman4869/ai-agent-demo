# M11-T7 交接：首次授权在线 Embedding 冒烟被 Provider 阻断

- 日期：2026-08-27
- 任务：`M11-T7 / blocked`
- 主要证据：`V-20260827-003`、`ADR-0023`、`ADR-0024`
- 修改范围：仅连续性文档；没有代码、依赖、schema、前端或默认配置改动

## 已确认事实

- `OPENAI_API_KEY` 已被当前进程识别，但从未输出或记录其内容。
- 用户明确授权一次在线测试。选择 `text-embedding-3-small`，固定三维、batch size 1、retry 0、20 秒 timeout；准备以两段非敏感合成文本验证真实 Embedding 写入 pgvector、相同文本查询和临时文档删除。
- pgvector integration 容器 healthy，绑定 `127.0.0.1:55433`。第一次和第二次失败发生在 SDK HTTP client 创建前：全局 `ALL_PROXY` 为 SOCKS5，而 `.venv` 缺少 `socksio`。
- 最终仅在子进程去除 `ALL_PROXY/all_proxy` 后重试，保留现有 HTTP/HTTPS proxy。请求到达 Provider，但以 `embedding_provider_quota_or_rate_limited` 失败；没有 usage、Token、费用、向量写入或查询成功证据。
- 数据库只读检查证明临时 `m11-t7-online-embedding-smoke` 文档数为 0。

## 禁止的后续动作

- 不自动重试，不以“已经有 Key”推断新的在线授权。
- 不安装 `socksio`、不改变系统/Codex 全局 proxy、不输出 Key 或代理地址。
- 不把失败错误码、SDK 初始化或本地 pgvector 健康描述成 M11-T7 E4 成功。

## 解除阻断后的唯一下一步

用户先在 OpenAI Platform 确认项目配额可用或限流窗口已恢复，然后明确回复：

> 已恢复额度，允许再执行一次在线 Embedding 冒烟测试。

收到新的授权后，先只读检查 Key 和容器健康；再以同一最小配置执行一次，记录 Provider 返回的 model、dimensions、batch、请求数、usage、耗时和成本（若 Provider 返回 usage）。成功后删除临时文档并写新的 verification；若再次失败，保留新错误事实，不继续重试。
