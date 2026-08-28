# M11-T7 交接：DashScope pgvector DSN 前置检查阻断

- 日期：2026-08-28
- 任务：`M11-T7 / blocked`
- 验证：`V-20260828-001`
- 基线：`c130863`

## 本次实际结果

- 用户明确授权后，执行了一次 `dashscope_embedding_smoke --authorized`。
- 命令在本机配置预检返回稳定错误码 `pgvector_dsn_required`，因此没有建立数据库连接、没有触达 DashScope、没有读取或输出 Key、没有写入/查询临时文档，也没有 Provider usage 或费用。
- 该授权已使用；不得自动重试。

## 唯一下一动作

用户在 Windows 用户环境变量中新增以下非敏感本机测试库地址，并完全重启 Codex：

```text
AI_AGENT_TEST_PGVECTOR_DSN=postgresql://ai_agent@127.0.0.1:55433/ai_agent_integration?sslmode=disable
```

随后用户必须重新明确授权一次。收到授权后，只运行：

```powershell
./.venv/Scripts/python.exe -B -m backend.app.evals.dashscope_embedding_smoke --authorized
```

不要改动 Key、endpoint、依赖、全局代理或测试代码；不要开始 M12。
