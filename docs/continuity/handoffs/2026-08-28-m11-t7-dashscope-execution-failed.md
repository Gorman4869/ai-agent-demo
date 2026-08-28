# M11-T7 交接：DashScope 执行失败待离线归类

- 日期：2026-08-28
- 任务：`M11-T7 / blocked`
- 验证：`V-20260828-004`
- 基线：`5466279`

## 已确认

- 当前执行器的 Key、endpoint、DSN、online switch、provider、model、revision、64 维、batch=1、retry=0 均已完成非敏感预检。
- 单次授权命令返回 `dashscope_smoke_failed`；retry 仍为 0，未自动重试，且没有输出敏感配置或原始异常。
- 本机只读检查证明隔离表存在、临时 document ID 计数为 0。它不能证明 Provider 请求是否到达、是否返回向量、usage 或费用。

## 下一条原子动作

离线审查 `dashscope_embedding_smoke.py`、`openai_embeddings.py` 与现有测试：将预期的 Provider/响应/数据库边界收敛为不泄露信息的稳定错误码，并补回归。不得读取 Key、发在线请求、修改全局代理或自动重试。完成离线验证后，才请求用户新的单次授权。
