# 第 4 阶段：Vue Agent UI 与 SSE 事件流

## 目标与时间

预计 5–7 小时。完成后你应能设计与模型供应商无关的事件协议，通过 POST 请求消费 SSE，展示工具过程、运行状态、最终答案和引用，并正确处理失败与取消。

## 启动项目

打开两个 PowerShell 终端，在项目根目录分别运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

```powershell
cd frontend
npm install
npm run dev
```

浏览器访问 `http://127.0.0.1:5173`。Vite 将 `/api` 请求代理到 `http://127.0.0.1:8000`，因此学习阶段不需要修改后端 CORS。

## 界面操作顺序

1. 点击“装载课程资料”，确认应用启动时建立的固定课程索引已就绪。
2. 保留默认问题或输入自己的问题。
3. 点击“启动研究”，观察右侧事件时间线。
4. 检查答案上方审核结果及下方 evidence 来源与分数。
5. 在运行过程中点击“停止”，观察取消状态。

## 数据流

```text
Vue 输入
  → POST /api/sessions 获取匿名 session + capability
  → POST /api/sessions/{id}/runs/stream
     Header: X-Session-Token（仅保存在页面内存）
  → fetch ReadableStream
  → SSE 分帧与 JSON 解析
  → AgentEvent[] 时间线
  → POST /api/research
  → answer + critique + evidence
```

当前 Mock 运行很快，主要用于观察协议。后续接入真实模型或慢工具后，同一事件契约仍可使用。

`session.id` 用于定位会话，不承担身份认证。匿名 session 创建时返回独立 capability，`useAgentDesk()` 只保存在内存中，`streamRun()` 在每次流请求中回传；不得写入 URL、日志或 `localStorage`。

## 为什么不用 EventSource

原生 `EventSource` 主要发起 GET，不能直接携带本阶段的 POST JSON 请求体。`fetch` 可以提交消息并读取 `ReadableStream`，因此由 `src/services/agentApi.ts` 负责解码和分帧。组件不应处理 `event:`、`data:` 或半包缓冲。

## 目录职责

| 文件 | 职责 |
| --- | --- |
| `types/agent.ts` | 前后端事件、证据和状态类型 |
| `services/agentApi.ts` | HTTP、SSE、非 2xx 错误转换 |
| `composables/useAgentDesk.ts` | 页面运行状态和取消控制 |
| `components/RunTimeline.vue` | 只展示结构化事件 |
| `App.vue` | 组合研究工作台 |
| `styles/main.css` | 全局视觉系统和响应式布局 |

## 事件协议

本阶段复用后端稳定事件名：

- `run.started`
- `tool.started`
- `tool.completed`
- `tool.failed`
- `run.completed`
- `run.failed`

前端只依赖这些领域事件，不依赖 OpenAI、LangGraph 或其他模型供应商的原始流对象。

## 必做练习

1. 在后端事件中加入 `duration_ms`，在时间线展示耗时。
2. 将一个 SSE frame 拆成两个网络 chunk，验证缓冲解析仍正确。
3. 模拟 404、422 和流中 `run.failed`，分别检查错误提示。
4. 增加“重试研究”按钮，但禁止自动重放已经完成的副作用工具。
5. 将页面缩窄到 720px 以下，检查控制栏、内容和时间线的阅读顺序。

## 通关标准

- `npm run build` 同时通过 Vue 类型检查和 Vite 构建。
- 后端 SSE 契约测试通过。
- API 和 UI 本地探活均返回 200。
- 页面显示 idle、running、completed、failed 四类状态。
- 键盘能聚焦文本框和按钮，系统减少动画时禁用动态效果。
- 取消请求不会被展示为普通失败。

## 常见错误与排查

| 现象 | 常见原因 | 排查顺序 |
| --- | --- | --- |
| 页面请求 404 | Vite 代理或 FastAPI 未启动 | 检查两个进程、端口和请求路径 |
| 事件 JSON 解析失败 | 网络 chunk 不等于 SSE frame | 检查 buffer 与双换行分隔 |
| 页面一直 running | 缺少完成事件或异常未落状态 | 检查事件序列和 finally |
| 点击取消显示红色错误 | AbortError 未单独处理 | 检查 AbortController 分支 |
| 工具重复执行 | 断线后盲目重放 POST | 先查询 run 状态并使用幂等键 |

## 工程沉淀

保留 `AgentEvent`、SSE parser、状态机和错误转换。未来换模型、增加 WebSocket 或迁移 Pinia 时，应复用协议而不是让页面重新理解后端内部对象。
