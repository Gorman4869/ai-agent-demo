# M12：统一 Run 与实时 Agent UI

> 工程状态只查看 `../continuity/status.md`。本阶段迁移 Vue 主链，但旧 API 在兼容验收前不会删除。

## 本阶段目标

让 Agent、RAG、记忆、工具、审批、引用、usage 和最终答案属于同一个持久 Run，并让 Vue 在执行中实时展示、断线续传和刷新恢复。

- 时间预算：2 周，约 20–30 小时。
- 任务：M12-T1 至 M12-T6。
- 工作映射：异步任务控制台、AI Copilot、审批型业务工作台。

## 20% 关键知识

| 类型 | 知识点 | 工作场景 | 学到什么程度 | 验证任务 |
| --- | --- | --- | --- | --- |
| 必学 | 持久 Run 状态机 | 长任务 API | 幂等创建和恢复 | M12-T1 |
| 必学 | EventStore + SSE | 实时进度 | 终态前可观察 | M12-T2 |
| 必学 | sequence/after/heartbeat | 断线续传 | 不丢、不重、不触发副作用 | M12-T2 |
| 高频 | Vue 判别联合和状态机 | Agent UI | 类型化处理全部事件 | M12-T4 |
| 高频 | 快照与增量合并 | 页面刷新 | 恢复同一 Run | M12-T4、T5 |
| 易错 | 流结束后再次请求答案 | 双链路 UI | 能识别并删除 | M12-T3、T4 |

## 统一事件最小集合

```text
run.queued
run.started
context.ready
model.delta
tool.requested
tool.started
tool.completed
approval.required
usage.updated
evidence.added
run.completed
run.failed
run.cancelled
```

每个业务事件包含 Run ID、递增 sequence、类型、时间和类型化 data；心跳不占业务 sequence。

## 跟练顺序

1. 新建持久 Run API，验证同幂等键同请求返回同一 Run、不同请求冲突。
2. 用可暂停 Fake Runtime 证明 SSE 在终态前收到中间事件。
3. 断开连接后使用 `after` 补发缺失事件，模拟通知丢失和应用重启。
4. 把 RAG、记忆、审批、usage 合并到一个 Run，保留旧接口兼容测试。
5. Vue 改用判别联合，删除独立 Research 覆盖答案的调用。
6. 添加 parser/state/component 测试和真实浏览器 E2E。

## 计划验证命令

```powershell
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_persistent_run_api -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_persistent_sse -v
npm.cmd run test --prefix frontend
npm.cmd run build --prefix frontend
npm.cmd run test:e2e --prefix frontend
```

前端测试依赖必须在安装前取得用户许可；命令只有进入 verification log 后才算已验证。

## 常见错误与排查

| 现象 | 原因 | 排查 |
| --- | --- | --- |
| 只在结束时收到全部事件 | Run 在响应生成器前已同步完成 | 用可暂停 Runtime 检查执行和传输并发 |
| 重连后事件重复 | after 语义或前端去重错误 | 对比最后 sequence 与服务端查询条件 |
| 刷新后找不到匿名 Run | capability 未保存或发送 | 检查 sessionStorage 和鉴权头 |
| 答案与引用不一致 | 仍存在独立 Research 双链 | 浏览器网络面板确认只有一个 Run |
| 点击取消但工具继续执行 | 只取消了 Fetch | 检查服务端持久取消和工具边界检查 |
| 审批换参数后仍执行 | 审批未绑定完整摘要 | 对比 tool call、参数摘要和单次状态 |

## 自测

1. SSE 和 WebSocket 在本项目中分别有什么取舍？
2. 为什么心跳不能占用业务事件 sequence？
3. 实现一个新事件类型并补齐类型、状态机和测试。
4. 用浏览器网络面板证明答案、引用和 usage 来自同一 Run。
5. 设计刷新、断线、取消同时发生时的状态合并规则。

## 费曼复述

用“快递流水号和物流记录”解释 Run ID、sequence、快照、增量和断线续传，并说明断线为什么不应自动取消后台任务。

## 官方资源

- MDN Server-sent events：<https://developer.mozilla.org/docs/Web/API/Server-sent_events>
- Vue Composition API：<https://vuejs.org/guide/extras/composition-api-faq.html>
- FastAPI StreamingResponse：<https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse>
