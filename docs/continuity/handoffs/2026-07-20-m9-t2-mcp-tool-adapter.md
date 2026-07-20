# M9-T2 交接：MCP 工具发现与共同适配

- 日期：2026-07-20，Asia/Shanghai
- 完成任务：`M9-T2`
- 完成状态：`verified`
- 下一任务：`M9-T3 / planned`
- 验证基线 HEAD：`f8b59d2`
- M9-T1 实现提交：`f8b59d2`
- M9-T2 实现提交：`40b1257`
- 验证记录：`V-20260720-001`、`V-20260720-002`
- 架构决策：`ADR-0009`
- 分支：`main`
- 任务等级：`B`，普通后端框架纵切，时间盒 60–90 分钟
- 新增或安装依赖：无；沿用 `mcp==1.28.1`
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. `McpToolPolicy` 为每个 Server 固定远端 allowlist 与本地名称、可信描述、角色、风险、副作用和审批策略；请求或远端元数据不能改写这些字段。
2. `McpClientManager` 通过连接 worker 分页执行真实 `list_tools`，限制页数、工具数与游标，并将发现快照映射为共同 `ToolDefinition`。
3. Schema 归一化只接受有界的 object 子集，移除不可信提示元数据，强制拒绝额外字段；重复、缺失、非法 Schema 和跨 Server 名称冲突稳定失败。
4. 共同 handler 线程安全桥接回 owner loop，并在拥有 SDK context 的原 worker 中执行 `call_tool`；未列入策略的直接调用被拒绝。
5. 新增独立请求超时，调用不自动重试；参数、结构化结果和文本回退都有大小与结构上限，远端异常与原始内容不进入公共错误。
6. 同一 MCP `ToolDefinition` 已实际通过 ToolRegistry、ManualAgentLoop、OpenAI Agents SDK FunctionTool 与 LangGraphRuntime 执行；角色拒绝沿用共同 Registry。
7. 阶段 09 增加最小纵切和实际命令，后端规范增加 MCP 发现/映射/调用边界；没有提前扩写 M9 完整教程与题库。

## 真实证据边界

- 测试实际启动本地 Python MCP 子进程并完成 initialize、list_tools、call_tool 与关闭，不是依赖存在、import 或 mock Session 证据。
- 证据为本地 Python STDIO 和三 Runtime 集成 E3；Fake/Mock 只用于 Runtime 决策，不替代 MCP 协议调用本身。
- 没有构建或调用 TypeScript Knowledge Server，不能宣称 M9-T3 E2E 或关闭 `KI-002`。

## 本次修改文件

- `backend/.env.example`
- `backend/app/integrations/mcp/__init__.py`
- `backend/app/integrations/mcp/client.py`
- `backend/app/integrations/mcp/config.py`
- `backend/app/integrations/mcp/tools.py`
- `backend/app/settings.py`
- `backend/tests/mcp_tool_fixture.py`
- `backend/tests/test_mcp_tool_adapter.py`
- `backend/tests/test_settings.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/stages/09-mcp-client-skills.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/handoffs/2026-07-20-m9-t2-mcp-tool-adapter.md`

## 实际验证

- M9-T1 恢复：9 项生命周期测试通过且无 ResourceWarning；52 个稳定任务、55 个 Markdown 文件连续性检查通过。
- M9-T2 聚焦测试：7 项通过，覆盖真实发现/调用、可信映射、三 Runtime、RBAC、超时、错误/结果上限、allowlist 与名称冲突。
- 定向回归：126 项通过，覆盖 MCP 生命周期、Settings、工具安全、Manual、Agents SDK、LangGraph、Container 和 API；无 ResourceWarning。
- 静态检查：`git diff --check` 通过，只有既有 LF/CRLF 转换提示。
- 未执行全量门：没有依赖/锁文件、共同 ToolDefinition 公共契约、HTTP Schema、前端或跨前后端接口变化。

## 失败尝试与修复

- 初版 6 项测试通过后，审阅发现公开 `call_tool` 可绕过映射层直调未列入策略的工具；补充 allowlist 校验和真实用例后，最终 7 项与 126 项回归通过。
- 常见 Python 格式化配置路径搜索因文件不存在和 PowerShell 通配语法失败；改为查询实际文件清单，确认没有可用的项目格式化配置，未安装新工具。
- 中断恢复后的工作区仅有本任务 9 个代码/测试文件，与交接摘要一致，没有回滚或覆盖其他改动。

## 警告与未验证范围

- 既有 Starlette/httpx 弃用警告和 Windows asyncio debug 慢任务信息不变；未安装 `httpx2` 或升级依赖。
- 没有验证 TypeScript Server、远程 transport、断线重连、运行中健康检查、调用幂等、副作用恢复或生产容量。
- `KI-002` 保持 open；关闭证据仍要求 M9-T3 的 TypeScript STDIO 初始化、发现、调用、非法参数和关闭 E2E。
- 没有读取 Key、运行在线模型、访问网络服务或产生费用。

## 未提交改动

M9-T2 代码、测试、阶段材料和首轮连续性记录已提交为 `40b1257`。提交后只修改本 handoff、status 和 verification log 以固定实现锚点；这些记录由后续本地文档提交闭环，不得混入 M9-T3 实现。

## 下一条原子动作

开始 `M9-T3` 的 B 类协议 E2E：先只读检查实施计划 M9-T3、`mcp-servers/knowledge-server` 源码、锁文件和构建脚本，重跑已有 TypeScript build；再让 Python `McpClientManager` 对构建产物完成 initialize、list_tools、共同 ToolDefinition 调用、非法参数和关闭。不得用 import 或直接函数调用替代 STDIO，不提前进入 Skill 或 M10。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_tool_adapter -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 7 项测试通过且无 ResourceWarning，连续性为 52 个稳定任务和 56 个 Markdown 文件。若一致，不要重做 M9-T1/M9-T2，直接进入 M9-T3 TypeScript Knowledge Server 协议 E2E。
