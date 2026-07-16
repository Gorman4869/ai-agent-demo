# ADR-0006：持久 Run 与 Store 契约

- 状态：accepted
- 日期：2026-07-16
- 任务：`M8-T2`

## 背景

旧 `InMemoryRunService` 同步执行 Mock Agent，只保存最终 API 展示记录；它没有 queued、审批暂停、CAS、幂等创建、可续传事件或数据库替换语义。直接修改旧类型会同时破坏 M1–M7 教学链、现有 HTTP 响应和 SSE 测试，因此 M8 需要独立迁移缝。

## 决策

1. 在 `backend.app.domain.run` 建立独立 `RunRecord`、`StoredRunEvent`、`ToolExecution`、`UsageRecord` 和稳定状态枚举。Settings 从领域层导入 Runtime/Provider 名称，领域层不反向依赖配置或适配器。
2. Run 状态固定为：

```text
queued -> running | cancelled
running -> waiting_approval | completed | failed | cancelled
waiting_approval -> running | failed | cancelled
completed | failed | cancelled -> 无后续状态
```

3. Run 创建幂等作用域固定为 `(owner_id, idempotency_key_digest)`。请求摘要使用带 `run-request-v1` 标记的规范 JSON SHA-256，覆盖 session、runtime、provider、model、输入和执行选项。原始幂等键不保存。
4. 状态写入使用 `expected_version` CAS。owner 不匹配和 Run 不存在对外不可区分；冲突使用稳定 Store 异常，不泄漏输入、Key、事件数据或驱动异常。
5. 调用方生成稳定 event ID，Store 分配 per-Run sequence 和 UTC 时间。同 ID 同内容返回原事件；同 ID 不同内容为 `event_conflict`。心跳不存储。
6. 事件、工具参数和工具结果只接受标准 JSON，拒绝 NaN/Infinity、非字符串键、非法 Unicode、循环结构、超深/超多节点和超过 64,000 字节的数据。写入及返回均生成深度隔离快照。
7. `UsageRecord` 每次模型调用一条，费用未知保持 `None`，已知费用使用 `Decimal` 并记录来源。副作用工具在记录创建时必须已有幂等摘要；原始参数和结果不进入模型。
8. `RunStore` 与 `EventStore` 从第一版就是 async Protocol。内存实现只承诺单 event loop、单进程；嵌套锁固定为 Run lock 后 Event lock，使终态检查和事件追加线性化。
9. Container 默认创建匹配的内存 Store 对；显式替换必须同时提供 RunStore 和 EventStore，且调用方负责两者确实属于同一持久化组合。
10. 旧 `run_service` 与新 Store 暂时并存但不双写。旧 API 类型在 `main.py` 中显式别名为 `LegacyRunRecord`，M8-T3 前不改变旧响应结构。
11. Store 合同测试抽成适配器无关 mixin；M11 PostgreSQL 实现必须运行同一套所有权、幂等、CAS、事件重放、分页和并发测试。

## 尚未解决的事务边界

`RunStore.transition()` 与 `EventStore.append()` 仍是两次调用。内存实现已经阻止“读取 running 后等锁、Run 先完成、晚到事件仍写入”的 TOCTOU，但终态状态和终态事件还没有通用原子 Unit of Work：进程可能在两次调用之间退出。

该风险登记为 `KI-015`。M8-T3 固定 Coordinator 使用的一次提交用例契约，M11 用 PostgreSQL 同事务 CAS 与事件写入关闭崩溃窗口。本 ADR 不把当前两次调用描述成事务。

## 后果

- M1–M7 旧教学链继续稳定，M8 可独立发展持久异步主链。
- API、Coordinator 和 PostgreSQL 适配器有明确所有权、幂等和并发语义。
- 内存锁不能替代多进程或数据库约束；部署切换前必须完成 M11。
- 仓库短期存在两个 RunRecord，导入时必须显式区分。

## 未采用方案

- 直接扩展旧 `services.run_service.RunRecord`：会把同步演示记录和持久领域状态混成一个迁移热点。
- 用同状态重复转换实现幂等：会掩盖并发写入和非法状态机，幂等应由 Key、event ID 与 CAS 处理。
- 用 `MAX(sequence) + 1` 或无锁 `len(events) + 1`：并发下会重复，数据库阶段必须使用事务内 per-Run 分配器。
- 把未知费用写成 0：会让成本分析产生错误结论。
