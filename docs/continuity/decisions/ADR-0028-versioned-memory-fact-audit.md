# ADR-0028：长期事实版本化纠正、删除与追加式审计

- 状态：accepted
- 日期：2026-08-20
- 任务：`M11-T5`
- 依赖：`ADR-0014`、`ADR-0021`、`ADR-0022`、`ADR-0025`、`ADR-0026`、`ADR-0027`

## 背景

既有 Memory Store 只支持经批准创建长期事实、按 owner 读取和兼容删除。事实没有版本，调用方无法区分“基于当前值纠正”与“覆盖了更新后的值”；物理删除也无法保留发生过纠正或删除的证据。M11-T5 需要在不扩大 HTTP、前端和默认 Runtime 范围的前提下，先固定内存与 PostgreSQL 共同的纠正、删除、并发冲突和审计合同。

事实可能包含敏感内容。公共 command、result、异常、审计记录、日志和跨进程探针不得通过 repr 或错误文本泄漏 owner、key 或 value；同时数据库写入必须保持事实状态与审计记录同事务。

## 决策

### 1. 使用显式 version CAS 命令

新增冻结、repr-safe 的 `CorrectMemoryFact` 与 `DeleteMemoryFact`。事实创建版本为 0；每次成功纠正或删除把版本增加 1。纠正只允许改变 value，key、scope、owner 和 fact ID 不变，并继续要求 `approved=true`。删除仍由可信 owner 限定。

两个命令都携带 `expected_version`。owner 不匹配、事实不存在或已经删除统一为内容无关的 `memory_fact_not_found`；expected version 不匹配为 `memory_fact_conflict`。适配器不根据异常内容推测可重试性，也不自动重试有副作用的纠正或删除。

### 2. 删除保留 tombstone 并清空内容

成功删除不再物理移除事实，而是保留 owner、scope、fact ID、version 与 `deleted_at`，同时清空 key/value。`facts(owner)` 只返回未删除事实，因此 Context collector 在删除后不会再次注入旧值。

内存实现以事实锁串行化 CAS、当前状态和审计更新。PostgreSQL 适配器在一个同步 pool 事务中 `SELECT ... FOR UPDATE`，校验 owner/deleted/version，再更新事实并插入同版本审计；任一步失败整体回滚。

### 3. 审计只记录动作、版本和内容摘要

审计动作固定为 `created`、`corrected`、`deleted`。每条记录包含 owner、fact ID、version、action、value digest 与时间，但冻结 repr 隐藏 owner，且不保存或返回 key/value。摘要使用带版本前缀和 UTF-8 长度的 SHA-256 canonical 输入，避免简单拼接歧义。

摘要用于一致性校验和结果未知后的人工仲裁，不是加密。低熵事实仍可能被离线猜测；它不能替代字段加密、访问控制或密钥化 MAC。删除审计保留删除前最后 value 的摘要，但 tombstone 不再保留原内容。

`fact_audit(owner, fact_id)` 保持 owner scope；其他 owner 只能得到空结果。兼容 `remember()` 与 `forget()` 也写入 created/deleted 审计，使现有 HTTP 行为不变但不会绕过账本。

### 4. migration 6 追加 schema 和防改写边界

`0006_memory_fact_version_audit.sql` 为事实增加非负 version 与 `deleted_at`，约束 tombstone 的 key/value 必须为空；新增 `(fact_id, version)` 唯一的审计表。迁移把当时仍存在的旧事实回填为 version 0 的 created 记录，并计算与 Python 相同的摘要。

数据库 trigger 拒绝普通 `UPDATE` 和 `DELETE` 审计行，应用只拥有追加路径。该边界不是外部不可篡改账本：数据库 owner 仍可禁用 trigger 或执行 `TRUNCATE`，迁移前已物理删除的历史也无法重建。生产级防篡改、备份/WAL 和独立审计汇聚仍属后续工程。

### 5. 保持 async bridge 与外部 API 边界

`AsyncLocalMemoryStore` 与 `AsyncPostgresMemoryStore` 只镜像三个新 Store 方法，继续通过既有有界 bridge 隔离同步 PostgreSQL。timeout、取消或连接中断可能产生 result-unknown；调用方可重新读取当前 version 和 audit digest 仲裁，但没有 mutation idempotency key，不能自动重放。

本纵切不新增 HTTP、前端或 Runtime 写入口。既有 memory HTTP 响应形状保持不变；公开读取/纠正/删除/audit API 由后续纵切在可信 owner、版本和兼容策略明确后单独接线。

## 后果

- 内存与 PostgreSQL 运行相同 version、owner、approval、conflict、tombstone 和 audit 合同。
- 错误事实纠正后，Context 只读取新值；删除后 active facts 为空，审计仍可证明 created→corrected→deleted。
- PostgreSQL 真实故障注入证明审计插入失败会回滚事实 version/value；并发相同 expected version 只有一个赢家。
- 四个不同 PID 的本地 PostgreSQL 探针证明 create、correct、delete、audit 可跨进程恢复，输出不含 owner/key/value。
- M11-T5 保持 `in_progress`；Store 能力尚未通过公开的可信 owner API 暴露，在线模型、Provider 与 M11-T6 也不在本结论内。

## 未采用方案

- 直接覆盖 value 而不带 expected version：会丢失并发更新，调用方无法识别陈旧编辑。
- 删除事实行和审计行：无法证明删除发生，也会让旧 Context/运维结果难以仲裁。
- 审计保存原始 key/value：扩大敏感内容保留面，且不满足探针与 repr 脱敏边界。
- 把摘要描述为匿名化或加密：SHA-256 对低熵内容不提供保密性。
- 在 async façade 对 timeout 自动重试：结果未知时可能重复推进 version 或产生冲突。
- 在本纵切直接修改 HTTP/前端：会把 Store/migration/concurrency 证据与外部兼容合同混为一个不可逆切片。

## 验证依据

- `backend/tests/test_memory_store_contract.py`
- `backend/tests/test_context_collector.py`
- `backend/tests/postgres_store_integration.py`
- `backend/app/stores/postgres_fact_audit_probe.py`
- `V-20260820-005`
