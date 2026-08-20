# ADR-0027：Run-bound 原子会话回合发布与重放收敛

- 状态：accepted
- 日期：2026-08-20
- 任务：`M11-T5`
- 依赖：`ADR-0014`、`ADR-0021`、`ADR-0022`、`ADR-0026`

## 背景

M11-T5 第四纵切让 `RunCoordinator` 在 durable completed terminal 之后按 user→assistant 调用两次 `AsyncMemoryStore.append_message()`。这固定了唯一写入者和顺序，但两个调用不是一个事务：进程可能在 terminal 后、消息前退出，也可能只写入 user。terminal replay 当时直接返回 Run，无法安全补写，因为普通 append 没有 Run-bound 幂等键。

PostgreSQL Run/Event 使用异步 pool，Memory 使用同步 pool 与 async bridge；两者不共享连接。把 terminal 与 Memory 强行合并为一个数据库事务会推翻 `ADR-0014/0022` 的已验证 composition，并让默认内存、同步 compatibility 和恢复生命周期同时重写。

## 决策

### 1. 新增显式 PublishTurn 命令

Memory 层增加冻结、repr-safe 的 `PublishTurn`：包含可见 Run ID、隐藏的 session、plain user message 和 plain assistant message。命令校验两个标识以及固定 role，不接受 tool metadata。

命令以版本化 canonical JSON 计算 SHA-256 digest；digest 绑定 session 和两条完整消息。幂等账本只保存 session 与 digest，不额外长期保存消息内容。相同 Run/相同 binding 返回 `created=false`；相同 Run 改 session 或任一消息抛稳定、无内容 `memory_turn_conflict`。

### 2. 一个 Store 命令发布完整回合

同步与异步 `MemoryStore` 共同合同新增 `publish_turn(command)`。默认 `append_message()` 保持兼容，Context 读取、HTTP 和记忆 fact 合同不改。

内存参考实现用同一把消息锁完成幂等检查、消息窗口替换与 digest 账本写入；并发相同命令只有一个 `created=true`。账本不保存完整命令，避免绕过短期消息窗口无限保留内容。

PostgreSQL `0005_conversation_turn_publications.sql` 新增 Run ID 主键账本，只保存 session、digest 和时间。适配器在一个同步 pool 事务中完成：插入幂等账本、为 session 分配两个连续 sequence、单语句插入 user/assistant、裁剪窗口。任一步失败时消息、sequence 与账本一起回滚；并发 `ON CONFLICT` 后读取权威 binding。

### 3. terminal replay 负责跨域收敛

新 completed terminal 继续按 `terminal commit -> publish_turn -> live notify -> lease release` 排序。若发布失败，durable Run 不回滚，日志仍只有稳定 code、Run ID 与 result-unknown。

当 `execute()` 或 `resume_approval()` 读到既有 completed Run 时，Coordinator 不调用 Runtime，而是重放同一个 `PublishTurn` 后返回 terminal。该命令可安全补写 terminal 后崩溃留下的缺口；成功发布后的重复重放只返回 `created=false`，不产生重复消息。

### 4. 不宣称跨 Store 共同事务

Run terminal 与 Memory turn 仍跨 async/sync pool，不是一次 ACID commit。当前保证是：每次 turn 发布内部 all-or-nothing，且 completed Run 的显式 replay 可幂等收敛。若 terminal 成功后永远没有后续 execute/resume，缺失消息不会由后台任务自动扫描修复；这不是外部副作用 exactly-once。

幂等账本当前没有 TTL/归档/删除策略。删除旧消息不会删除账本，否则旧 Run replay 会重新插入。容量与保留策略由后续生产化任务单独设计。

## 后果

- user-only 半回合被消除；Memory 写入结果未知时可由 terminal replay 安全仲裁。
- 默认内存与 PostgreSQL 运行相同 command、replay、conflict、窗口和并发合同；现有 append 与 fact API 保持兼容。
- 两个不同 PID 的真实 PostgreSQL 探针证明：进程 A 只提交 completed Run 且零消息，进程 B replay 两次后恰有一对消息，Runtime 调用为 0。
- migration 5 是不可改写历史；后续 schema 变化只能新增 migration。
- M11-T5 仍未完成长期事实纠正/删除后的主 Run 行为、version CAS 与 audit，任务保持 `in_progress`。

## 未采用方案

- 把 Run terminal 与 Memory 消息放入一个跨 pool 事务：当前 composition 没有共同连接，会推翻已接受边界。
- 只给两次 append 使用相同 event ID：Memory 行没有 Run-bound 幂等合同，仍可能半写或重复。
- 在 terminal 后无限自动重试：running timeout 结果未知，普通 append 重试会重复；新命令只在明确 replay 时重放。
- 在幂等账本保存完整 user/assistant 内容：会绕过消息窗口，扩大敏感数据保留。
- 为账本设置短 TTL：过期后旧 terminal replay 会重新发布消息，破坏幂等语义。

## 验证依据

- `backend/tests/test_memory_store_contract.py`
- `backend/tests/test_run_coordinator.py`
- `backend/tests/test_postgres_async_stores.py`
- `backend/tests/postgres_store_integration.py`
- `backend/app/stores/postgres_turn_replay_probe.py`
- `V-20260820-003`
