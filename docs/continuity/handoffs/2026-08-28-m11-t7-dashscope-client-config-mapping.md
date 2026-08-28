# M11-T7 交接：DashScope SDK 客户端配置错误映射

- 日期：2026-08-28
- 任务：`M11-T7 / blocked`
- 验证：`V-20260828-005`
- 验证基线：`dedd10d`

## 本次实现

- 新增 `EmbeddingClientConfigurationError`，稳定码为 `embedding_provider_client_configuration_invalid`。
- OpenAI-compatible Embedding Provider 只在 SDK 客户端创建抛出 `ImportError` 时映射该领域错误；原始异常、proxy 地址、Key 和请求文本不进入错误输出。
- 新增 DashScope 离线回归，使用私有文本的模拟 `ImportError`，断言只得到稳定错误码。相关 Provider/configuration/container/pgvector 回归共 75 项通过。

## 诊断事实与边界

- 只读预检显示当前 `ALL_PROXY` 与 `all_proxy` 都是 SOCKS。第四次在线冒烟在此修复前返回 `dashscope_smoke_failed`，因此 SOCKS 缺失可选依赖是高概率原因，但没有新的在线执行证实。
- 没有安装 `socksio`、改变全局代理、自动重试、读取 Key 或进行新的网络调用。

## 下一条原子动作

用户选择其一并明确授权新的单次在线尝试：

1. 允许只在该命令子进程清除 `ALL_PROXY/all_proxy`，其他环境变量保持；或
2. 明确授权安装兼容的 SOCKS 依赖。

未经该选择和新的单次授权，不执行在线 CLI。无论选择哪项，都不能修改全局代理或开始 M12。
