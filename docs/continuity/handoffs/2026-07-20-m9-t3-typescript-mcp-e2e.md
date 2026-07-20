# M9-T3 交接：TypeScript MCP Server 协议端到端

- 日期：2026-07-20，Asia/Shanghai
- 完成任务：`M9-T3`
- 完成状态：`verified`
- 下一任务：`M9-T4 / planned`
- 验证基线 HEAD：`c3972b6`
- M9-T2 实现提交：`40b1257`
- M9-T3 实现提交：`5aba130`
- 验证记录：`V-20260720-003`、`V-20260720-004`
- 架构决策：沿用 `ADR-0009`，没有新增不可逆决策
- 分支：`main`
- 任务等级：`B`，本地协议 E2E，时间盒 60–90 分钟
- 新增或安装依赖：无；使用现有锁文件与 node_modules
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 服务端目录新增 `typescript-knowledge`，固定 Node 构建入口、绝对工作目录和只读 `lookup_concept` 可信策略；默认选择保持为空。
2. 新增 `backend.tests.test_mcp_client_e2e`，真实启动 `node build/index.js`，由 Python MCP SDK 完成 initialize、list_tools、call_tool 和关闭。
3. 发现结果经 M9-T2 适配器映射成共同 `ToolDefinition`；已知和未知概念均通过 ToolRegistry 返回有界文本结果。
4. 类型错误 `{name: 42}` 真实进入 TypeScript Server 并由 Zod 拒绝，只向公共边界返回稳定 `remote_tool_error`；未列入策略的工具在调用前拒绝。
5. 阶段 09 增加最小构建/E2E 命令和证据边界，后端规范补充禁止直接 import Server 函数冒充 E2E。
6. `KI-002` 达到关闭条件；`KI-008` 只移除 MCP 协议缺口，前端、真实数据库和统一分层门仍保持 open。

## 真实证据边界

- `npm.cmd run build --prefix mcp-servers/knowledge-server` 实际执行锁定环境中的 `tsc`，Python 测试实际启动构建后的 Node 进程并交换 JSON-RPC。
- 证据为 Windows 本地 Node/Python STDIO E3，不是依赖存在、import、Fake Session、远程 Server 或生产 E4。
- 没有修改 TypeScript 业务逻辑、依赖、锁文件或构建配置；没有验证其他平台、远程 transport、重连或容量。

## 本次修改文件

- `backend/.env.example`
- `backend/app/integrations/mcp/config.py`
- `backend/tests/test_mcp_client_e2e.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/stages/09-mcp-client-skills.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/handoffs/2026-07-20-m9-t3-typescript-mcp-e2e.md`

## 实际验证

- M9-T2 恢复：7 项 MCP 工具适配测试通过且无 ResourceWarning；52 个稳定任务、56 个 Markdown 文件连续性检查通过。
- TypeScript build：`tsc` 通过，使用现有依赖，没有安装或更新依赖，也没有留下构建产物改动。
- M9-T3 聚焦测试：4 项通过，覆盖 8 个关键行为，包括真实 initialize/list/call/close 与协议非法参数。
- 定向回归：67 项通过，覆盖 TypeScript/Python MCP、生命周期、Settings、Container/FastAPI 和 API；无 ResourceWarning。
- 连续性：52 个稳定任务、57 个 Markdown 文件通过；`git diff --check` 无空白错误，只有既有 LF/CRLF 提示。
- 未执行全量门：本任务未触发依赖、构建配置、公共契约、HTTP Schema 或前端变化。

## 失败尝试与修复

- 首次组合关键词搜索被 PowerShell 双引号改写为未闭合正则；改用字面关键词时一个带转义引号的参数又被解释为路径。随后按实际文件清单逐个读取 package、lock、tsconfig、源码和 build，确认内容一致。
- `status.md` 顶部最新实现摘要停留在 M8，但 M9-T1/T2 独立锚点与 Git 证据正确；本轮将摘要修正到已确认的 M9-T2 实现 `40b1257`，未改写历史 verification。

## 警告与未验证范围

- 既有 Starlette/httpx 弃用警告与 Windows asyncio debug 慢任务信息不变；未安装 `httpx2` 或升级依赖。
- 只验证当前 Windows、Node 和锁定依赖组合；未验证 Linux/macOS、远程 MCP、HTTP/SSE transport、断线重连、健康检查、调用幂等、副作用恢复或生产容量。
- `KI-002` closed；`KI-008` 仍因前端、真实数据库和统一分层测试缺口保持 open。
- 没有读取 Key、运行在线模型、访问网络服务或产生费用。

## 未提交改动

M9-T3 代码、测试、阶段材料和首轮连续性记录已提交为 `5aba130`。提交后只修改本 handoff、status 和 verification log 以固定实现锚点；这些记录由后续本地文档提交闭环，不得混入 M9-T4 实现。

## 下一条原子动作

开始 `M9-T4` 的 B 类只读 Skill 纵切：先只读审阅实施计划 M9-T4、`skills/research-summary`、现有路径解析与缓存风格；定义固定根目录、元数据格式、显式/自动触发、引用加载、大小上限和稳定错误。只实现 Catalog/Resolver，不提前注入 Runtime 上下文或执行 M9-T5 评测，不进入 M10。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
npm.cmd run build --prefix mcp-servers/knowledge-server
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_e2e -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 TypeScript build 通过，4 项 E2E 无 ResourceWarning，连续性为 52 个稳定任务和 57 个 Markdown 文件。若一致，不要重做 M9-T1–M9-T3，直接进入 M9-T4 Skill Catalog/Resolver。
