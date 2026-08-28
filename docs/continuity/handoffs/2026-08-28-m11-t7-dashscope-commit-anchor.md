# M11-T7 交接：DashScope 离线准备提交锚点

- 日期：2026-08-28
- 任务：`M11-T7 / blocked`
- 实现提交：`4a079e0 feat: prepare DashScope embedding smoke`
- 已有验证：`V-20260827-004`
- 设计依据：`ADR-0025`

## 已固定事实

- `4a079e0` 已提交 DashScope `text-embedding-v4` 的离线配置、64 维隔离 pgvector schema、受限在线冒烟入口及其离线和本机数据库验证。
- 该提交完成时工作区无未提交改动；远程仓库仍未配置。
- 尚未读取、输出或使用 `DASHSCOPE_API_KEY`，也尚未执行真实 DashScope 请求、写入或查询。因此 M11-T7 必须保持 `blocked`，不能把离线通过描述为 E4 在线证据。

## 唯一下一动作

先按 `2026-08-27-m11-t7-dashscope-offline-preparation.md` 在 Codex 本机环境配置百炼变量；不要把 Key 发到聊天。随后由用户明确授权一次、且只执行以下命令：

```powershell
./.venv/Scripts/python.exe -B -m backend.app.evals.dashscope_embedding_smoke --authorized
```

该命令固定 batch size 为 1、retry 为 0；成功路径最多两次 Provider 请求，最后删除临时文档。不要安装依赖、修改全局代理、自动重试或开始 M12。
