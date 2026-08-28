# M12：统一 Run 与实时 Agent UI

> 工程状态只查看[连续性状态页](../continuity/status.md)。本章描述可重复执行的 M12
> 学习与验收路径，不把历史验证写成当前动态状态。

## 本阶段目标

让 Agent、RAG、记忆、工具、审批、引用、usage 和最终答案属于同一个持久 Run，并让 Vue 在执行中实时展示、断线续传和刷新恢复。

- 时间预算：6 次跟练，约 14–20 小时。
- 任务：M12-T1 至 M12-T6。
- 工作映射：异步任务控制台、AI Copilot、审批型业务工作台。

成功定义：能独立演示“创建 -> 观察 -> 暂停/恢复 -> 终态 -> 刷新恢复”，并用同一个
Run ID 与持久事件核验答案、引用、usage、审批和错误。M12 不证明生产 OIDC、HttpOnly
会话、CSP、Nginx、多实例通知、跨浏览器矩阵、在线模型质量、usage 账本或生产容量。

## 最小系统图

```text
Vue useAgentDesk
  -> POST /api/durable/runs + Idempotency-Key
  -> RunStore 创建 queued Run
  -> RunCommands / RunCoordinator
       -> Context + Memory + RAG
       -> Runtime + Tool + Approval
       -> EventStore(sequence)
  <- GET /api/durable/runs/{id}/events?after=N
  <- GET /api/durable/runs/{id} authoritative snapshot
  -> sessionStorage: capability + run/session/cursor + public approval state
```

SSE 提供低延迟增量，snapshot 提供恢复和最终权威状态。SSE 断开不会取消后台 Run；只有
显式调用 `/cancel` 才是业务取消。

## 20% 关键知识

| 类型 | 知识点 | 工作场景 | 学到什么程度 | 验证任务 |
| --- | --- | --- | --- | --- |
| 必学 | 持久 Run 状态机 | 长任务 API | 幂等创建和恢复 | M12-T1 |
| 必学 | EventStore + SSE | 实时进度 | 终态前可观察 | M12-T2 |
| 必学 | sequence/after/heartbeat | 断线续传 | 不丢、不重、不触发副作用 | M12-T2 |
| 高频 | Vue 判别联合和状态机 | Agent UI | 类型化处理全部事件 | M12-T4 |
| 高频 | 快照与增量合并 | 页面刷新 | 恢复同一 Run | M12-T4、T5 |
| 易错 | 流结束后再次请求答案 | 双链路 UI | 能识别并删除 | M12-T3、T4 |
| 易错 | Fetch Abort 等于业务取消 | 页面卸载 | 能区分断流和 `/cancel` | M12-T4、T5 |
| 易错 | 直接删除 legacy API | API 迁移 | 能列出兼容退出门槛 | M12-T6 |

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

学习者个人运行结果和复盘只写 `../progress.md`；工程状态、验证和 known issue 不写入个人
进度。每次先预测结果，再执行命令和阅读断言。

### 第 1 次：幂等 Run 与可信所有权

- 时间预算：2–3 小时。
- 目标：理解 `202 + run_id`、幂等重放、匿名 capability 和 owner scope。
- 代码入口：`backend/app/main.py`、`backend/app/api/schemas.py`、
  `backend/app/stores/base.py` 与 `backend/app/stores/memory.py`。
- 动作：比较同键同请求、同键改请求、错 capability、取消后重开和审批绑定。
- 命令：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_persistent_run_api -v
```

- 产出：一张“客户端字段/服务端可信字段”表和一次幂等冲突说明。
- 工作映射：重复提交订单、长任务创建、页面刷新后的请求重放。
- 通关：能说明幂等键防重复但不自动等于登录身份；匿名首次请求如何建立 capability；原始
  key 为什么不能持久化或记录。
- 常见错误：复用同一个 key 创建不同问题；让 body 提供 owner；把 202 当任务完成。

### 第 2 次：持久 SSE 与断线续传

- 时间预算：2–3 小时。
- 目标：掌握 EventStore、排他 `after`、心跳、终态关闭和断开不取消。
- 代码入口：`backend/app/main.py`、`backend/app/services/run_event_notifier.py`、
  `backend/tests/test_persistent_sse.py`。
- 动作：观察执行中事件；用 `after=1` 只补发后续事件；验证慢消费者、断开和终态竞态。
- 命令：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_persistent_sse -v
```

- 产出：SSE frame 示例、sequence 合并规则和一次断线恢复时序图。
- 工作映射：AI 生成进度、文件导入、批处理日志和审批等待。
- 通关：能解释 notifier 丢失为什么仍不丢历史；心跳为什么不能占 sequence；关闭 Fetch
  为什么不应重放或取消副作用。
- 常见错误：按时间戳排序、把 `after` 当包含式 cursor、只依赖内存队列、漏发最后终态事件。

### 第 3 次：同 Run 的答案、引用与 usage

- 时间预算：2–3 小时。
- 目标：证明引用来自本次 prompt 已选 RAG 片段，snapshot 不会重新检索。
- 代码入口：同步/异步 Context Runtime 与 `backend/app/main.py` 的 durable snapshot 投影。
- 动作：运行同 Run citation/usage 投影、RAG source 失败和畸形后续事件场景。
- 命令：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_durable_run_projection backend.tests.test_context_runtime backend.tests.test_async_context_runtime -v
```

- 产出：公开 citation 字段表、敏感 Context 排除表和 `usage=null` 解释。
- 工作映射：客服引用、知识问答溯源、模型用量展示。
- 通关：能说明 citation 是“进入本次上下文的证据”而不是“答案一定正确”；不能把未知 usage
  显示为 0；不能在终态后调用另一个 Research 覆盖结果。
- 常见错误：快照时重新搜索、公开完整 prompt/Memory、把所有候选片段当成实际证据。

### 第 4 次：Vue 状态机与刷新恢复

- 时间预算：2–3 小时。
- 目标：用判别联合消费稳定事件，并让当前标签页刷新后恢复同一 Run。
- 代码入口：`frontend/src/types/agent.ts`、`frontend/src/services/agentApi.ts`、
  `frontend/src/composables/useAgentDesk.ts`。
- 动作：追踪 create、snapshot、SSE、cancel、approval；检查恢复记录的字段。
- 命令：

```powershell
npm.cmd --prefix frontend run test:unit
npm.cmd --prefix frontend run build
```

- 产出：前端状态转换表、恢复记录 Schema 和一个新事件的类型化处理草案。
- 工作映射：Vue 任务工作台、标签页刷新、审批操作台。
- 通关：能解释为何使用可带 header 的 Fetch 流而不是原生 EventSource；capability 为什么只放
  当前标签页 sessionStorage；组件卸载为什么只 Abort 订阅。
- 常见错误：capability 进入 URL/localStorage；重复事件重复更新 UI；序号缺口仍继续拼答案。

### 第 5 次：真实浏览器恢复与审批

- 时间预算：2–3 小时。
- 目标：区分 parser 单测与浏览器纵切，验证首次断流、刷新和 waiting approval 恢复。
- 代码入口：`frontend/tests/unit`、`frontend/tests/e2e/durable-run.spec.ts`、
  `backend/tests/m12_frontend_e2e_server.py`。
- 动作：先跑 parser/状态机单测，再让本地 FastAPI + Vite + Chromium 执行两条 E2E。
- 命令：

```powershell
npm.cmd --prefix frontend run test:unit
npm.cmd --prefix frontend run test:e2e
```

- 产出：“单测能证明/浏览器 E2E 才能证明/仍未证明”的证据表。
- 工作映射：浏览器弱网恢复、刷新中审批、前后端联调验收。
- 通关：能指出测试 Runtime 与生产权限的边界；能用网络请求证明 UI 没有调用
  `/api/research` 或 legacy `/runs/stream`。
- 常见错误：把 fixture 审批工具说成生产权限；用 mock fetch 冒充真实浏览器；端口冲突后
  误判 Node 版本错误。

### 第 6 次：兼容迁移与里程碑验收

- 时间预算：3–4 小时。
- 目标：区分“主链已替代”和“旧端点可删除”，完成新旧契约和课程验收。
- 材料：[API 迁移记录](../m12-api-migration.md)、
  [ADR-0033](../continuity/decisions/ADR-0033-legacy-run-api-compatibility.md)、
  [M12 一页速查表](../m12-realtime-ui-cheat-sheet.md)。
- 动作：审计 `frontend/src` 的 legacy 引用；运行新旧后端契约、前端单元/E2E、构建和连续性
  检查；最后运行里程碑全量离线门。
- 命令：

```powershell
rg -n "/api/research|/runs/stream|/api/sessions|/api/runs/" frontend/src
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_api backend.tests.test_persistent_run_api backend.tests.test_persistent_sse backend.tests.test_durable_run_projection -v
npm.cmd --prefix frontend run test:unit
npm.cmd --prefix frontend run test:e2e
npm.cmd --prefix frontend run build
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/check-continuity.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify.ps1
```

- 产出：API 迁移评审、验收证据索引、自测答卷和费曼复述。
- 工作映射：公共契约迁移、灰度兼容、版本退出评审和发布门禁。
- 通关：Vue 主链无 legacy 调用；旧接口合同仍通过且无双写；能列出删除端点所需的消费者、
  通知、回归和新 ADR 证据。
- 常见错误：`rg` 无命中退出 1 被误报为失败；用“仓库没引用”推断“外部没人调用”；课程
  全量门通过后顺手进入 M13。

## 计划验证命令

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_api backend.tests.test_persistent_run_api backend.tests.test_persistent_sse backend.tests.test_durable_run_projection -v
npm.cmd --prefix frontend run test:unit
npm.cmd --prefix frontend run test:e2e
npm.cmd --prefix frontend run build
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/check-continuity.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify.ps1
```

命令只有以实际退出码和结果进入 verification log 后才算证据；本章代码块不是通过证明。

## 三张必须会画的图

### Run 生命周期

```text
queued -> running -> waiting_approval -> running -> completed
             |             |              |       -> failed
             +-------------+--------------+       -> cancelled
```

`completed`、`failed`、`cancelled` 是终态，不能重开。`waiting_approval` 不是终态，SSE
可以继续心跳；审批恢复后仍是同一个 Run。

### 事件提交与传输

```text
Runtime progress
  -> EventStore append + sequence
  -> best-effort notifier wakeup
  -> SSE 再从 EventStore 读取
  -> Vue 严格递增应用
```

notifier 只负责“提醒去读”，不是事件真相；进程重启或漏通知后仍可从 Store 补发。

### 浏览器恢复

```text
读取 sessionStorage 恢复记录
  -> capability 查询 snapshot
     -> 401/404：清理失效记录
     -> terminal：展示权威结果
     -> non-terminal：从保存 sequence 订阅 SSE
          -> 重复：忽略
          -> 连续：应用并保存 cursor
          -> 缺口/提前结束：停止不完整增量，snapshot 后有界重连
```

## 新旧 API 边界

M12 的兼容结论是：旧 Vue 双链主流程已被 durable 主链替代，旧 HTTP 端点尚未删除。
完整字段和迁移步骤见 [M12 durable Run API 迁移记录](../m12-api-migration.md)。

| 链路 | 当前职责 | 禁止扩展 |
| --- | --- | --- |
| durable `/api/durable/*` | 新 Agent UI、持久状态、续传、取消、审批、引用、usage | 生产认证、账本和多实例部署留 M13 |
| legacy Run API | 兼容既有同步/回放调用和旧课程测试 | 不新增 durable 能力，不双写 |
| `/api/research` | 独立 RAG/审核教学工作流 | 不再覆盖 Agent UI 的 durable Run 答案 |

## 常见错误与排查

| 现象 | 原因 | 排查 |
| --- | --- | --- |
| 只在结束时收到全部事件 | Run 在响应生成器前已同步完成 | 用可暂停 Runtime 检查执行和传输并发 |
| 重连后事件重复 | after 语义或前端去重错误 | 对比最后 sequence 与服务端查询条件 |
| 刷新后找不到匿名 Run | capability 未保存或发送 | 检查 sessionStorage 和鉴权头 |
| 答案与引用不一致 | 仍存在独立 Research 双链 | 浏览器网络面板确认只有一个 Run |
| 点击取消但工具继续执行 | 只取消了 Fetch | 检查服务端持久取消和工具边界检查 |
| 审批换参数后仍执行 | 审批未绑定完整摘要 | 对比 tool call、参数摘要和单次状态 |
| usage 显示为 0 | 把 unknown/null 转成默认数字 | 检查 snapshot projection，未知应显示“未知” |
| 迁移后旧调用方失败 | 只替换 URL，没处理 202/cursor/capability | 按迁移记录逐项比较新旧契约 |

固定排查顺序：owner/capability -> Run snapshot/version -> EventStore sequence -> SSE
cursor/envelope -> Vue last sequence -> sessionStorage -> approval/cancel -> citation/usage ->
legacy/durable 是否混链。不要先放宽身份、去重、审批或错误校验。

## 证据等级与边界

| 证据 | 最高等级 | 能证明 | 不能证明 |
| --- | --- | --- | --- |
| 类型检查、对象构造 | E1 | 契约形状可编译 | SSE、浏览器或 Store 真正执行 |
| Fake/Mock Runtime 走真实 Store/Coordinator | E2/E3 | 领域链、状态、顺序和失败语义 | 在线 Provider、生产容量 |
| 本地 PostgreSQL application lifespan | E3/C | 当次真实数据库持久与重启读取 | 生产数据库、多机网络分区 |
| FastAPI + Vite + Chromium | E3/C | 当次真实浏览器断线、刷新和审批恢复 | Nginx、生产认证、跨浏览器矩阵 |

M12 的既有不可变证据索引为 `V-20260828-007` 至 `V-20260828-012`。M12-T6 的实际
结果必须另行追加 verification，不能根据这段索引预先宣称通过。

## 自测题库

### 概念题（5 题，共 20 分）

1. RunStore、EventStore、notifier 和 SSE 各自负责什么，为什么 notifier 不能做真相源？
2. `Idempotency-Key`、session ID、capability 和认证 Principal 有什么区别？
3. snapshot 与 SSE 分别解决什么问题，为什么恢复时要先读 snapshot？
4. 心跳为什么不占 sequence，客户端为什么不能按 timestamp 修复乱序？
5. 为什么 Agent UI 不应在 Run 完成后再调用 `/api/research`？

评分：每题 4 分；定义/数据流 2 分，边界或反例 2 分。

### 实操题（4 题，共 40 分）

1. 运行 durable API 测试，记录同键重放、同键冲突、错 capability 和取消终态四条结果。
2. 从一组 SSE frame 中处理重复、缺口、心跳和终态，写出最后可安全应用的 cursor。
3. 在 `AgentEvent` 中设计一个新的公开事件：补齐类型、parser 校验、状态转换和单测，不允许
   `any` 或供应商原始 payload。
4. 用浏览器网络请求证明首次断线、刷新和审批都使用同一 Run，并证明没有 legacy/Research
   双链调用。

评分：每题 10 分；可复现证据 4 分，状态/数据流解释 3 分，安全与未验证边界 3 分。

### 工作场景题（4 题，共 40 分）

1. 用户点击“生成报告”后 202 响应丢失。设计重试规则，说明何时复用幂等键、何时创建新 key。
2. Run 正在调用高风险发布工具时浏览器断网。说明后台、SSE、ToolExecution、审批和 UI
   应怎样处理，哪些动作绝不能自动重放。
3. 团队想把 capability 放 URL 以便刷新恢复。指出泄漏路径，并给出教学和生产两级方案。
4. 产品要求今天删除所有旧接口。写迁移评审：列出调用方、协议差异、通知、监控、回滚和
   何时可用新 ADR 标记端点 `superseded`。

评分：每题 10 分；方案 4 分，取舍 3 分，风险与证据 3 分。

总分至少 80 分通关。出现任一红线即不通过：客户端选择 owner/审批绑定、capability 进入
URL/日志/localStorage、SSE 断开自动重放副作用、把 null usage 当 0、终态后 Research 覆盖
答案、把本地 E2E 写成生产/Nginx/在线模型证据，或在没有消费者证据时删除旧端点。

## 一页速查表

工作时打开 [M12 统一 Run 与实时 UI 一页速查表](../m12-realtime-ui-cheat-sheet.md)。先凭
记忆画三张图和写出恢复算法，再用速查表纠正。

## 费曼复述任务

不查资料，向一名只做普通 CRUD 的前端同事讲 6 分钟：

1. 用“快递单、物流流水、查询快照”解释 Run ID、sequence、SSE 和 snapshot。
2. 为什么网络断开只是不再看物流，不是取消快递？
3. 为什么同一 Run 的引用比完成后重新 Research 更可信？
4. 刷新后 capability、Run ID 和 last sequence 如何协作恢复？
5. 审批为什么只让浏览器提交 decision，工具和参数由谁绑定？
6. 为什么旧 UI 主链可标记被替代，但旧端点现在仍不能直接删除？
7. 举一个真实故障，按固定顺序说出第一检查点、安全结果和未验证范围。

复述合格标准：语言简单，能画出三张图，有一个前端业务例子、一个安全边界、一个兼容迁移
取舍和两个未验证边界。把 SSE 当存储、Abort 当 cancel、idempotency 当登录或
`superseded` 当物理删除时必须重述。

## 与 30 项大纲映射

完整目标见 [30 个主题映射](../syllabus-map.md)。M12 直接覆盖 04、19、20、22，并为
12、16、17、24、26、30 提供纵向整合证据：

| 编号 | 主题 | M12 产物 | 证据边界 |
| --- | --- | --- | --- |
| 04 | 前端基础 | Vue 3 Composition API、判别联合、Fetch SSE | 单页组合式状态；未引入路由/Pinia |
| 12 | Prompt 上下文工程 | 同 Run Context/RAG citation 投影 | 完整 prompt 不公开 |
| 16 | RAG 知识库 | `rag.citations` 与 snapshot | 证据可追溯，不等于事实一定正确 |
| 17 | 记忆系统 | durable Run 使用 M11 持久 Context/turn | Run/Memory 不是共同事务 |
| 19 | Agent UI | 状态机、时间线、审批、取消、刷新恢复 | 本地 Chromium；非生产认证 |
| 20 | 后端 API | 幂等 Run、快照、命令和兼容迁移 | durable/legacy 隔离；旧端点仍保留 |
| 22 | 流式输出 | EventStore、sequence、heartbeat、replay | Nginx/多实例留 M13 |
| 24 | 自动化测试 | parser、composable、浏览器和后端契约 | M13 才形成分层 CI 门 |
| 26 | 安全治理 | capability、服务端审批、敏感字段边界 | OIDC/HttpOnly/CSP 留 M13 |
| 30 | 系统设计 | 双链收敛、API 迁移与退出门槛 | 外部消费者和生产遥测未知 |

## 最终验收清单

- [ ] 能画出 Run 生命周期、事件提交链和浏览器恢复图。
- [ ] 能运行 durable API、SSE、projection、前端单元、E2E、构建和连续性命令。
- [ ] 能区分 RunStore、EventStore、notifier、snapshot、SSE 和 sessionStorage 的职责。
- [ ] 能演示同键重放、断线续传、刷新恢复、显式取消和服务端绑定审批。
- [ ] 能证明答案、citations 和 usage 来自同一 Run，且 `usage=null` 不伪装为 0。
- [ ] 能说明 capability、幂等键、session 和 Principal 的差异及泄漏边界。
- [ ] 能依据 [API 迁移记录](../m12-api-migration.md)解释旧 Vue 主链已替代但旧端点仍保留。
- [ ] 概念、实操和场景题至少 80 分，且没有证据或安全红线错误。
- [ ] 完成速查表使用练习和一次合格费曼复述。
- [ ] 能指出 M13 对认证、观测、CI 和部署的承接。

完成这些课程条目可验收 M12-T6 的材料；学习者个人完成情况只写 `../progress.md`，工程
状态仍以实际代码、verification log 和连续性状态页为准。

## 官方资源

- MDN Server-sent events：<https://developer.mozilla.org/docs/Web/API/Server-sent_events>
- Vue Composition API：<https://vuejs.org/guide/extras/composition-api-faq.html>
- FastAPI StreamingResponse：<https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse>
