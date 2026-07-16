# 第 1 阶段：手写最小 Agent Loop

## 目标与时间

预计 3–4 小时。完成后你应能解释模型、工具、循环、停止条件和事件的职责，并在没有 API Key 时运行完整闭环。

## 前置检查

```powershell
python --version
python -S -m unittest backend.tests.test_manual_agent_loop -v
```

要求 Python 支持项目使用的类型语法；当前基线为 Python 3.11+。

如果 WindowsApps 占位符抢占了 `python`，而项目已有 `.venv`，把命令中的 `python` 替换为 `.\.venv\Scripts\python.exe`。`-S` 会禁用 `site-packages`，因此这仍然是在验证 M1 的标准库边界。

## 核心原理

模型不会直接执行 Python 函数。它只返回“最终答案”或结构化的 `ToolCall`。Agent 运行时检查工具名和参数，调用本地函数，把结果作为 `tool` 消息送回模型。循环直到得到最终答案或触发最大步数。

## 代码阅读顺序

1. `backend/app/domain/agent.py`：稳定的输入输出类型。
2. `backend/app/tools/registry.py`：工具发现、校验和执行。
3. `backend/app/models/mock_model.py`：确定性模型替身。
4. `backend/app/agent/manual_loop.py`：循环与停止条件。
5. `backend/tests/test_manual_agent_loop.py`：可观察行为。

## 运行 Demo

```powershell
python -S -m backend.app.demo
```

预期依次看到 `run.started`、`tool.started`、`tool.completed`、`run.completed`。

## 必做练习

新增 `convert_temperature` 工具：输入 `value`、`from_unit`、`to_unit`，只支持摄氏与华氏。补充成功、缺少参数、单位不支持三个测试。

## 完成标准

- `backend.tests.test_manual_agent_loop` 中的现有测试全部通过；测试数量以命令实际输出为准，不在文档中写死。
- 新工具至少三个测试通过。
- 能指出未知工具为什么没有立刻让整个运行崩溃。
- 能演示把 `max_steps` 改为 1 后的失败事件。
- 完成一次费曼复述并把测试结果填入进度表。

## 常见错误与排查

| 现象 | 常见原因 | 排查顺序 |
| --- | --- | --- |
| 找不到 `backend` | 不在项目根目录运行 | 查看当前目录，再使用 `python -m` |
| `python` 打开商店或无法运行 | WindowsApps 占位符排在真实 Python 前 | 用 `Get-Command python -All` 确认原因；已有 `.venv` 时使用仓库内解释器并保留 `-S` |
| Mock 决策耗尽 | 脚本没有为下一轮准备决策 | 数工具调用次数与决策数量 |
| 参数校验失败 | Schema 类型或 required 不匹配 | 打印 arguments，再检查 properties |
| 无限调用 | 缺少停止条件或模型一直请求工具 | 查看 max_steps 和事件序列 |

## 工作映射与沉淀

真实客服、数据助手和运维 Agent 都需要这套循环。保存 `ToolDefinition` 模板、事件命名和排错顺序；后续 FastAPI、LangGraph 与 Vue UI 会直接复用这些领域概念。
