# ADR-0009：MCP Client 使用服务端目录与同任务生命周期

- 状态：accepted
- 日期：2026-07-17
- 任务：`M9-T1`
- 依赖：`ADR-0001`、`ADR-0005`、`ADR-0007`

## 背景

M9-T1 需要在 FastAPI lifespan 中启动真实 MCP STDIO Client，同时保持默认离线、请求不可注入进程命令、失败可诊断且取消后不泄漏子进程。Python MCP SDK 的 `stdio_client` 与 `ClientSession` 使用 anyio context manager；如果一个任务进入、另一个任务退出，或取消恰好发生在 `__aenter__` 尚未注册退出回调的窗口，可能破坏 task-affine cancel scope 或遗漏资源清理。

## 决策

1. `Settings` 只接受服务端 Server ID 列表和启动超时。命令、参数和工作目录只来自不可变 `McpServerConfig` 目录，HTTP 请求没有这些字段。
2. 默认目录只登记本地 `python-knowledge` Server；默认选择为空，因此应用构造和普通 lifespan 都不启动子进程。
3. 每个 Server 使用独立 worker，在同一个 asyncio Task 中依次进入 `stdio_client`、进入 `ClientSession`、调用公开的 `initialize()`，并在收到停止信号后反向退出。
4. Manager 取消或超时时只发送停止信号并等待 worker 清理，不从外部直接取消 SDK context manager。FastAPI lifespan 独占 Manager 的启动和关闭。
5. 对外错误只使用 `server_not_allowed`、`process_unavailable`、`startup_timeout`、`protocol_error`、`startup_cancelled`、`shutdown_cancelled`、`shutdown_failed` 和 `invalid_state`；不附带原始命令、参数、Server 输出或异常文本。
6. SDK 的无效 JSON-RPC 解析日志改写为固定安全摘要。Server stderr 写入空设备，不进入应用日志。
7. M9-T1 只保留私有 Session 引用和已连接 Server ID，不暴露发现或调用 API；`list_tools`、Schema 映射和 `call_tool` 由 M9-T2 实现。

## 后果

- FastAPI 启停会真实执行 MCP SDK 与 STDIO 协议初始化，不是 import 或对象构造证据。
- 启动采用 all-or-nothing：任一 Server 失败时，已启动连接全部关闭，应用启动失败。
- 默认环境不产生网络、密钥读取或子进程；只有服务端显式选择已登记 ID 才启动本地 Server。
- 当前只证明单进程应用 lifespan；断线重连、工具调用幂等、远程 transport 和运行中健康恢复不在 M9-T1 范围。

## 验证依据

- `backend/tests/test_mcp_client_lifecycle.py`
- `backend/tests/test_settings.py`
- `backend/tests/test_container.py`
