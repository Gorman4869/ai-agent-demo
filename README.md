# AI Agent 从原理到工程实战

这是一个面向前端开发者的 12 周渐进式课程。主线采用 Python + FastAPI、Vue 3 + TypeScript，并用 TypeScript 完成 MCP 专项实验。项目先手写 Agent Loop，再进入 OpenAI Agents SDK、LangGraph、RAG、多 Agent、工程化和高级 Agent。

## 现在开始

1. 阅读 [完整学习计划](docs/learning-plan.md)。
2. 在 [学习进度表](docs/progress.md) 中完成基础诊断。
3. 对照 [30 个主题映射](docs/syllabus-map.md) 理解最终路线。
4. 进入第一课：`docs/stages/01-manual-agent-loop.md`。
5. 在项目根目录运行：

```powershell
python -m unittest discover -s backend/tests -v
python -m backend.app.demo
```

M1 只使用 Python 标准库，不需要 API Key，也不需要安装依赖。

完成 M1 后进入 [第 2 阶段](docs/stages/02-api-frameworks-mcp.md)，学习 FastAPI、Agents SDK、LangGraph 与 MCP 的职责边界。

完成 M2 后进入 [第 3 阶段](docs/stages/03-rag-memory-workflow.md)，实现可引用 RAG、显式记忆策略和研究审核工作流。

完成 M3 后进入 [第 4 阶段](docs/stages/04-agent-ui-sse.md)，构建 Vue 3 Agent 工作台并消费 SSE 事件流。

完成 M4 后进入第 5 阶段：先完成[可观测性、离线评测与工具安全](docs/stages/05-observability-evals-security.md)，再完成[Docker 构建与最小部署](docs/stages/05-docker-deployment.md)。

完成 M5 后进入 [第 6 阶段](docs/stages/06-advanced-agent-safety.md)，以代码 Agent 为完整项目，并完成多模态与浏览器 Agent 的受控最小实验。

完成 M6 后进入 [第 7 阶段](docs/stages/07-system-design-capstone.md)，完成容量估算、故障演练、业务迁移与最终答辩。

## 当前完整启动方式

后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

Docker（默认 Mock，不需要密钥）：

```powershell
docker compose -f deploy/compose.yaml up --build
```

M6 代码 Agent 离线 Demo 与最终统一验收：

```powershell
.\.venv\Scripts\python.exe -m backend.app.advanced.code_demo
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

浏览器访问 `http://127.0.0.1:5173`；后端健康检查为 `http://127.0.0.1:8000/health`。

匿名 Mock 模式可以聊天、运行 SSE，并读取应用启动时装载的固定课程资料。每个匿名会话会获得独立、只保存在页面内存中的 capability token，创建运行、SSE 和运行查询都必须携带它；服务端只保存摘要。任意知识写入、长期记忆、观测查询和高风险工具需要服务端身份；本地配置与精确单次审批示例见 [M5 安全跟练](docs/stages/05-observability-evals-security.md)。不要把教学 Bearer Token 打包到前端。

## 学习闭环

每一阶段都按“原理 → 最小实验 → 主线功能 → 测试 → 排错 → 费曼复述”完成。只有测试证据、练习和复盘同时完成，才勾选进度表。

## 文档导航

- [设计规格](docs/specs/2026-07-15-ai-agent-learning-demo-design.md)
- [实施计划](docs/implementation-plan.md)
- [学习计划](docs/learning-plan.md)
- [考核题库](docs/assessments.md)
- [一页速查表](docs/cheat-sheet.md)
- [费曼复述模板](docs/feynman-template.md)
- [前端项目编码规约](docs/项目编码规约%20v1.0.md)
- [M5 可观测性、评测与安全](docs/stages/05-observability-evals-security.md)
- [M5 Docker 部署](docs/stages/05-docker-deployment.md)
- [M6 高级 Agent 与受控执行](docs/stages/06-advanced-agent-safety.md)
- [M7 系统设计与最终答辩](docs/stages/07-system-design-capstone.md)
- [最终系统设计基线](docs/capstone-architecture.md)
- [最终演示脚本](docs/capstone-demo-script.md)
