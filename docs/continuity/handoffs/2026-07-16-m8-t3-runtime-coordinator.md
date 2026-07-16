# M8-T3 交接：异步 Runtime 与 RunCoordinator

- 日期：2026-07-16，Asia/Shanghai
- 任务：`M8-T3`
- 状态：`verified`
- 实现提交：`b171ad0`
- 验证记录：`V-20260716-005`
- 分支：`main`
- 远程仓库：未配置
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0

## 本次完成

1. 新增 SDK 无关的 `RuntimeRequest`、`RuntimeControl`、`RuntimeEvent`、`RuntimeResult` 与 async `AgentRuntime` Protocol。
2. 新增 `ManualRuntime`，用 worker thread 包装现有同步 Loop；不改旧 Loop，按白名单映射过程事件并隐藏输入、工具参数、结果和错误文本。
3. 新增 `PersistentEventEmitter`：先 Store 后有界 notifier；通知失败不回滚，精确重放不重复通知。
4. 新增 `RunCoordinator`：Runtime 选择、同实例 singleflight、跨实例 durable start claim、执行 deadline、取消和终态仲裁。
5. 新增 `StartCommit`：内存 Run→Event 临界区内一次提交 `queued -> running + run.started`。
6. 新增 `TerminalCommit`：一次提交 completed/failed/cancelled、答案或安全失败和匹配终态事件。
7. 普通 EventStore append 拒绝 Coordinator 拥有的 started/completed/failed/cancelled 生命周期事件。
8. Container 默认注册 `ManualRuntime + MockModel` 与新 Coordinator，并消费 max steps、model retries 和 Run execution deadline；默认仍零网络。
9. 旧 HTTP/GET/SSE 继续使用 legacy run_service，响应字段不变；测试证明 durable Store 为空，没有双写。
10. 新增 ADR-0007、M8-T3 跟练、编码规范和已知问题记录。

## 关键文件

- `backend/app/agent/runtime.py`
- `backend/app/agent/manual_runtime.py`
- `backend/app/services/run_coordinator.py`
- `backend/app/stores/base.py`
- `backend/app/stores/memory.py`
- `backend/app/container.py`
- `backend/tests/test_runtime_contract.py`
- `backend/tests/test_run_coordinator.py`
- `backend/tests/test_run_store_contract.py`
- [ADR-0007](../decisions/ADR-0007-runtime-coordinator-lifecycle-commits.md)
- [M8 跟练文档](../../stages/08-real-model-runtimes.md)
- [验证日志](../verification-log.md)
- [当前状态](../status.md)

## 已固定的运行时契约

```text
queued Run
  -> StartCommit(created=true)
  -> Runtime.run(request, emit, control)
       progress: append -> notify
  -> TerminalCommit
  -> completed | failed | cancelled
```

- Runtime 不发 `run.*`；Coordinator 独占生命周期。
- `RuntimeResult` 当前只有三个终态；waiting approval/resume 留 M10。
- 只有 StartCommit 的创建者执行 Runtime。相同 start 命令重放者等待 durable 赢家，不重复工具副作用。
- cancel 既设置 token，也提交 cancelled CAS。完成、取消和 timeout 不靠内存先后猜测，以 Store version 赢家为准。
- 生命周期 event ID 稳定且包含阶段/终态；相同命令重放不增 sequence，不重复 notify。
- Store 锁固定 Run → Event，临界区内没有 await；notifier、模型和工具都在锁外。
- Store 不可用时不通知、不伪造内存终态，也不重跑可能已有副作用的 Runtime。

## 审查中发现并修复的竞争

- start 状态与事件最初分两次写；已改为 StartCommit，并证明发布前故障后两边都不变。
- active cancel 最初只设 token；已改为 cancelled TerminalCommit 与 complete 共享 CAS。
- 终态最初共用一个 event ID；已按目标状态区分，竞争失败方得到 version winner。
- cancel 可能穿过 emit 的 token 检查；blocked append 测试证明晚到事件被拒绝且 execute 返回 durable cancelled。
- 两个 Coordinator 可能重放 start 后都执行；现在只有 `created=true` 执行，另一方等待相同结果。
- ManualRuntime 最初取消后无界等待线程；现在只有有限 grace，并消费迟到结果/异常。
- notifier 最初无时间上限；现在有独立短超时且不改变 durable 结果。

## 实际验证摘要

- 提交前新旧链兼容门：107 项通过。
- 实现提交后 Runtime/Coordinator/Store 核心门：60 项通过。
- `scripts/verify.ps1`：197 项后端测试通过，1 项既有 Windows 符号链接能力测试跳过。
- Controlled Code-Agent Demo、`pip check`、Vue 生产构建、MCP TypeScript 构建和 Compose 配置全部通过。
- handoff 前 continuity：52 个稳定任务、44 个 Markdown 文件通过。
- 敏感模式扫描只命中既有空 `OPENAI_API_KEY=` 测试断言；无真实 Key、Token 或密码。

## 旧链与新链边界

```text
旧 HTTP/SSE
  -> InMemoryRunService
  -> legacy RunRecord / RunResponse

新程序化主链
  -> durable RunStore + EventStore
  -> RunCoordinator
  -> AgentRuntime
```

不要把新 durable `RunRecord` 传给旧 `_to_run_response()`，也不要让旧路由双写新 Store。统一 API、真实 SSE、断线续传与 Vue 状态迁移属于 M12。

## 残余风险

- `KI-015`：mitigated。内存一次提交已完成，但 PostgreSQL 同事务、多进程竞争、连接结果未知和重启证据未完成。
- `KI-016`：open。Runtime 开始后的过程 Store 故障会留下 running Run；当前 fail closed，等待 lease、recovery scan 和安全重调度。
- `KI-017`：open。ManualRuntime 完成同步 Loop 后才回放过程事件；Python worker 不能硬取消，宽限后可能后台收尾。
- 终态提交和有界通知可以在 execution deadline 后完成，因此不是严格端到端硬墙钟。
- Docker Engine、PostgreSQL/pgvector、Nginx、真实 SDK Runtime 和在线模型均未验证。
- 既有 Starlette/httpx 弃用警告与 Windows symlink skip 保持不变。

## 下一条原子动作

开始 `M8-T4`，顺序固定：

1. 阅读当前锁定的 `openai-agents==0.18.2` 本地包 API，并用官方 OpenAI Agents SDK 文档核对公开接口。
2. 先写 `test_openai_agents_runtime.py` 的 fake runner/event fixture，覆盖文本增量、工具调用/结果、usage、Provider 错误、取消和脱敏。
3. 实现 OpenAI Agents Runtime 适配器，不把 SDK 对象泄漏到 RuntimeResult/EventStore。
4. 默认测试继续离线；没有用户新的单次授权，不执行在线 Runner 或付费冒烟。

## 恢复检查

```powershell
git status --short
git log -4 --oneline
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_runtime_contract backend.tests.test_run_coordinator backend.tests.test_run_store_contract -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

若实现提交 `b171ad0` 存在且核心门为 60 项通过，不要重做 M8-T3；从 M8-T4 fake fixture 开始。
