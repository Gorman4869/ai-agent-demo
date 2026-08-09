# ADR-0024：Embedding 批次、元数据与在线边界

- 状态：accepted
- 日期：2026-08-09
- 任务：`M11-T3`
- 依赖：`ADR-0005`、`ADR-0023`

## 背景

M11-T2 的 `PgVectorKnowledgeBase` 只依赖单条 `embed(text)`，文档切片会逐条调用模型，也没有可比较的 provider/model/revision/dimensions 元数据。该形状无法安全判断向量维度漂移、拆分 Provider 批次或构造稳定缓存键；若直接在 PgVector adapter 内加入在线重试和缓存，又会把数据库事务、Provider 策略与授权混在一起。

M11-T3 要求默认离线、确定性、无 Key，同时为后续显式在线 Embedding、批处理、重试和缓存留下同一领域边界。当前 pgvector schema 已由 ADR-0023 固定为 `vector(3)`，本任务不能静默迁移维度。

## 决策

### 1. Embedding 合同属于 knowledge 层

`backend/app/knowledge/embeddings.py` 定义 Provider、Model、冻结元数据和稳定错误。Provider 只处理一个已拆分批次；Model 对调用方提供单条和任意长度批次接口。PgVector 只依赖 Model 合同，不读取环境、不构造 SDK Client，也不拥有 Provider 重试或缓存。

### 2. 元数据是向量合同的一部分

每个 Model 暴露冻结的 `provider`、`model`、`revision` 和 `dimensions`。批次开始后元数据变化、返回数量变化、向量维度不一致或出现非有限值都 fail closed，且错误不包含输入文本或 Provider 原始异常。

当前 `PgVectorKnowledgeBase` 构造时要求 metadata dimensions 与 adapter dimensions 一致；ADR-0023 的默认 migration 继续只接受三维。其他维度必须使用新 migration/表决策，不能通过配置覆盖现有列。

### 3. 单条调用复用批次路径

Model 的 `embed(text)` 等价于单元素 `embed_batch()`。通用批次包装器按固定正整数 batch size 拆分输入、保持顺序，并在全部批次成功后才返回结果。任一批次失败时不返回部分向量；PgVector 在打开数据库事务前完成整篇文档的 Embedding，因此部分失败不会改写文档。

空批次返回空 tuple；批次中的空白文本以稳定输入错误拒绝。进入 Provider 前只做确定性空白规范化，不保存或记录原始文本。

### 4. 首个 Provider 是确定性离线实现

首个 Provider 使用标准库 SHA-256 把规范化 token 投影到固定维度并做 L2 归一化。它用于课程调用链、批次和维度合同，不是语义质量、Provider tokenizer 或线上模型证据，也不用于关闭 RAG 指标缺口。

### 5. 缓存、重试和在线授权按后续原子步骤接入

缓存键使用版本化 canonical payload：metadata namespace 加规范化文本的 SHA-256；不得把原文放入 key、日志或异常。只缓存完整成功且通过维度校验的向量，不缓存失败或部分批次。本轮只固定该合同，不实现缓存 Store。

重试只能由后续 Model wrapper 对显式分类的暂时性 Provider 错误按批次执行；协议错误、维度漂移、认证、配额策略和输入错误不重试。Embedding 是只读调用，但未知失败仍受固定次数和超时约束。

在线 Adapter 不自行读取环境。Composition 必须同时满足 ADR-0005 的全局 online gate、显式 embedding provider/model 配置、SecretStr Key 与调用预算，才能注入 SDK Client；仅存在 Key 或 chat model 不启用 Embedding。真实在线执行仍需用户新的单次授权，并由 M11-T7 记录 E4。

## 首个纵切边界

- 实现冻结 metadata、确定性离线 Provider、批次包装器和 PgVector 批次调用链。
- 自动化覆盖批次拆分/顺序、空批/空文本、部分返回、metadata/向量维度漂移、非有限值，以及失败前不打开数据库。
- 不实现缓存 Store、重试 wrapper、在线 SDK Adapter、Settings 接线、Provider 调用或 pgvector schema 迁移；M11-T3 保持 `in_progress`。

## 后果

- 文档多个切片不再强制逐条 Provider 调用，未来在线 Adapter 可以复用相同批次边界。
- PgVector 与 Provider 生命周期解耦，数据库事务不会包住网络 Embedding。
- 三维离线向量只提供确定性工程证据；固定 50 条 RAG 指标仍由 M11-T6 完成。
