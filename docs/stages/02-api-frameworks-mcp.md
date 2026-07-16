# 第 2 阶段：FastAPI、Agents SDK、LangGraph 与 MCP

## 目标

把 M1 的原理实现放入真实工程边界，并用相同问题比较四类抽象：HTTP API、OpenAI Agents SDK、LangGraph 和 MCP。预计 5–7 小时。

## 安装与运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-m2.txt
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

如果 `.venv` 已存在，跳过创建和安装步骤。课程仓库不依赖某台电脑上的 Python 绝对路径；可用 `Get-Command python -All` 确认当前解释器。

打开 `/docs` 查看 FastAPI 自动生成的接口文档。真实 OpenAI 调用不是本阶段默认测试的一部分。

## 阅读顺序

1. `main.py` 与 `api/schemas.py`：HTTP 只负责校验和转换。
2. `run_service.py`：业务流程不依赖 FastAPI。
3. `sdk_runtime.py`：SDK 管理 Agent、工具与运行器。
4. `graph_runtime.py`：状态、节点、边和条件分支。
5. `mcp_server.py`：Python 最小 MCP 对照实现。
6. `mcp-servers/knowledge-server`：主线 TypeScript STDIO MCP Server。

## 四者边界

| 能力 | 解决的问题 | 不负责什么 |
| --- | --- | --- |
| FastAPI | 对外 HTTP 契约与校验 | Agent 推理策略 |
| Agents SDK | Agent loop、工具、handoff、guardrail 等运行时 | 业务数据库设计 |
| LangGraph | 有状态、可恢复、显式图工作流 | 自动替你设计正确流程 |
| MCP | 客户端与工具/资源的互操作协议 | 决定何时调用工具 |

## 必做练习

1. 为 API 添加查询会话接口，并写 404 测试。
2. 给 LangGraph 增加“空问题拒绝”节点，断言不会进入 answer。
3. 给 MCP Server 增加 `list_concepts` 工具。
4. 配置真实模型前，先写出会产生费用和网络波动的测试标记策略。

## 通关标准

- M1 与 M2 全部测试通过。
- API 输入为空返回 422，不存在资源返回 404。
- 不设置 API Key 也能导入并测试所有模块。
- 能解释 MCP 工具和本地函数工具的相同点与不同点。
- 能说明什么任务应使用确定性 LangGraph，而不是让模型自由循环。

## 常见错误

- `ModuleNotFoundError`：确认使用 `.venv` 解释器并在项目根目录运行。
- 真实 SDK 调用报 401：确认只在需要时设置 `OPENAI_API_KEY`，不要写进源码。
- 图没有结束：检查条件边映射和 END。
- MCP 客户端找不到工具：先确认 Server 进程、transport，再检查工具注册。
