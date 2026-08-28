# M11-T7 交接：DashScope Settings 前置检查阻断

- 日期：2026-08-28
- 任务：`M11-T7 / blocked`
- 验证：`V-20260828-003`
- 基线：`d64fd15`

## 已确认

- Codex 执行器现在可见 `DASHSCOPE_API_KEY`、百炼 endpoint 与本机 pgvector DSN，但只输出了三项布尔值，未读取或输出内容。
- 第三次授权命令因 `dashscope_smoke_settings_invalid` 在 Provider 构造前停止；没有网络请求、临时写入/查询、usage 或费用。

## 用户需补充的非敏感变量

```text
AI_AGENT_ONLINE_ENABLED=true
AI_AGENT_EMBEDDING_PROVIDER=dashscope
AI_AGENT_EMBEDDING_MODEL=text-embedding-v4
AI_AGENT_EMBEDDING_REVISION=m11-t7-dashscope-2026-08-28
AI_AGENT_EMBEDDING_DIMENSIONS=64
AI_AGENT_EMBEDDING_BATCH_SIZE=1
AI_AGENT_EMBEDDING_MAX_RETRIES=0
```

完成后完全重启 Codex；先做不联网的配置布尔预检。只有预检通过后，用户才可重新授权一次在线冒烟。
