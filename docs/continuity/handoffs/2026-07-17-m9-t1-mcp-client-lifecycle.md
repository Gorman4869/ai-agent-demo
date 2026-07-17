# M9-T1 交接：MCP Client 配置与 FastAPI 生命周期

- 日期：2026-07-17，Asia/Shanghai
- 完成任务：`M9-T1`
- 完成状态：`verified`
- 下一任务：`M9-T2 / planned`
- 验证基线 HEAD：`ba7adf9`
- M9-T1 实现提交：待本轮本地 commit 固定
- 验证记录：`V-20260717-004`
- 架构决策：`ADR-0009`
- 分支：`main`
- 任务等级：`B`，普通后端框架纵切，时间盒 60–90 分钟
- 新增或安装依赖：无；沿用 `mcp==1.28.1`
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 新增 `backend.app.integrations.mcp`，以冻结 `McpServerConfig` 定义服务端允许的 Server ID、command、args 和绝对 cwd；默认目录只登记本地 `python-knowledge`。
2. 新增 `Settings.mcp`，只解析 Server ID 列表与 100–30000 ms 启动超时；默认列表为空，普通应用启停不创建子进程。
3. 新增 `McpClientManager`，真实调用 MCP SDK 的 `stdio_client`、`ClientSession` 和 `initialize()`，并保存私有 Session 与安全的已连接 ID。
4. 每个 Server 使用独立 worker，在同一 asyncio Task 中进入和退出 SDK context manager。超时、取消和部分启动失败通过停止信号完成 all-or-nothing 清理。
5. FastAPI lifespan 统一启动和关闭 Manager；ApplicationContainer 支持默认目录、显式服务端目录或显式 Manager 注入，但不允许两个 MCP 真相源同时注入。
6. 稳定诊断覆盖未知 Server、进程缺失、启动超时、协议错误、启动/关闭取消和关闭失败；错误不包含命令、stderr 或原始异常。
7. SDK 无效 JSON-RPC 堆栈被改写为固定安全日志，Server stderr 写入空设备。
8. 阶段 09 增加 M9-T1 最小跟练与边界，后端规范新增 MCP Client 生命周期规则。

## 真实证据边界

- FastAPI 测试实际启动本地 Python MCP 子进程并完成 JSON-RPC initialize/initialized 与正常关闭，因此不是依赖存在或 import 证据。
- 本次证据为本地 STDIO 与应用集成 E3，不代表远程 transport、生产容量或外部 Server E4。
- 没有 `list_tools`、`call_tool`、Schema/RBAC 映射或 TypeScript Server E2E；不能宣称 MCP 工具链闭环或关闭 `KI-002`。

## 本次修改文件

- `backend/app/integrations/__init__.py`
- `backend/app/integrations/mcp/__init__.py`
- `backend/app/integrations/mcp/config.py`
- `backend/app/integrations/mcp/client.py`
- `backend/app/settings.py`
- `backend/app/container.py`
- `backend/app/main.py`
- `backend/.env.example`
- `backend/tests/test_mcp_client_lifecycle.py`
- `backend/tests/test_settings.py`
- `backend/tests/test_container.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/stages/09-mcp-client-skills.md`
- `docs/continuity/decisions/ADR-0009-mcp-client-lifecycle.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/handoffs/2026-07-17-m9-t1-mcp-client-lifecycle.md`

## 实际验证

- handoff 恢复：M8 Provider 错误 1 项、框架对照 12 项和 52 任务/53 Markdown 连续性检查通过。
- M9-T1 聚焦测试：9 项通过，覆盖真实 SDK 初始化/关闭、默认空选择、允许目录、进程缺失、超时、协议错误、取消与部分启动回滚。
- 定向回归：68 项通过，覆盖 Settings、Container、FastAPI/API 和离线 online-smoke；启用 ResourceWarning 后无资源泄漏。
- 连续性：handoff 前 52 个稳定任务、54 个 Markdown 文件通过；`git diff --check` 无空白错误。
- 未执行全量门：没有依赖/锁文件、HTTP Schema、前端或跨前后端契约变化，68 项定向回归覆盖本任务边界。

## 失败尝试与修复

- 首次补丁因新父目录不存在而未应用；沙箱内 `New-Item` 又被拒绝，经仅工作区目录创建授权后成功，没有修改工作区外文件。
- 首轮 36 项测试退出码为 0，但取消路径产生 4 个 anyio MemoryObjectStream ResourceWarning；未接受该结果。改成每 Server 专属 worker 后，36、67、最终 68 项均在 ResourceWarning 开启时通过。
- SDK 初始协议错误会打印含原始无效行的解析堆栈；新增精确日志过滤后只输出 `MCP server sent invalid JSON-RPC`，测试断言不包含原始行。
- 一次临时内联诊断命令因 PowerShell `-c` 引号失败，改用 here-string 管道后成功；没有创建临时源码文件。

## 警告与未验证范围

- 既有 Starlette/httpx 弃用警告不变；未安装 `httpx2`。
- SDK 进程启动调用本身依赖操作系统返回；当前超时覆盖 initialize 等待，未声称能硬终止所有异常 OS 进程创建情形。
- 没有运行远程 MCP、HTTP/SSE transport、断线重连、运行中健康检查、工具调用幂等或副作用恢复。
- `KI-002` 保持 open；关闭证据仍要求 M9-T3 的 TypeScript STDIO 初始化、发现、调用和关闭 E2E。
- 没有读取 Key、运行在线模型、访问网络服务或产生费用。

## 未提交改动

handoff 创建时以上 M9-T1 文件均未提交；不得回滚或混入 M9-T2 实现。提交后的新 HEAD 由下一条 verification 或 handoff 记录。

## 下一条原子动作

开始 `M9-T2` 的 B 类框架任务：先只读审阅实施计划 M9-T2、`backend/app/tools`、`backend/app/agent/sdk_tools.py` 与 M9-T1 私有 Session 边界；定义不可变发现快照、JSON Schema 规范化、Server 命名空间、角色过滤、名称冲突和调用超时。只实现 Python Client 到共同 ToolDefinition/调用适配器的离线纵切，不提前构建或执行 M9-T3 TypeScript E2E，不进入 Skill。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_lifecycle -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 9 项测试通过且无 ResourceWarning，连续性为 52 个稳定任务和 55 个 Markdown 文件。若一致，不要重做 M9-T1，直接进入 M9-T2 只读设计检查。
