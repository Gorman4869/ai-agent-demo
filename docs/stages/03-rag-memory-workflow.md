# 第 3 阶段：RAG、记忆与多 Agent Workflow

## 目标与时间

预计 6–8 小时。完成后你应能区分检索错误与生成错误、区分聊天历史与长期记忆，并用显式工作流组织研究员、写作者和审核员。

## 运行

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

打开 `/docs`，依次调用：

1. `POST /api/knowledge/demo-seed` 确认应用启动时已装载服务端固定课程资料；该接口可重复调用且不会重建索引。任意 `POST /api/knowledge/documents` 从 M5 起需要服务端 `knowledge_editor` 身份，且不能覆盖保留 ID `agent-course`。
2. `POST /api/research` 提问并观察 evidence、critique 和 answer。
3. 使用服务端解析出的 Bearer 身份调用 `POST /api/memories`，分别使用 `approved=false/true`；请求体不再接受 `owner_id`。
4. 使用两个不同身份调用 `DELETE /api/memories/{id}`，验证所有者不能由查询参数伪造。

## RAG 数据流

```text
文档 → 规范化 → 切片 → 确定性稀疏向量 → 内存索引
问题 → 向量化 → 相似度排序 → 引用 → 写作 → 审核 → 回答
```

当前实现不是生产 Embedding，而是中文双字组合与英文词频向量。它的价值是让切片、召回、排序和引用可以离线观察；后续迁移 pgvector 时，领域接口不变。

`backend/app/knowledge/pgvector.py` 已提供可选持久化适配器。它依赖注入的 Embedding 与数据库连接工厂，只有显式调用 `initialize_schema()` 才创建扩展和表；核心测试不要求安装 `psycopg` 或启动 PostgreSQL。真实接入前需要准备固定维度 Embedding、测试数据库和 pgvector 扩展，并补一次集成测试。

## 记忆边界

- 短期消息：属于一次会话，数量受窗口限制。
- 运行状态：属于任务恢复，不等同聊天消息。
- 长期事实：必须明确批准，记录 owner、key、value、scope，并允许删除。
- 不要默认把整段聊天写成长期记忆，否则会引入隐私、污染和冲突。

## 多 Agent 工作流

本阶段的“研究员—写作者—审核员”是确定性节点：

- 研究员只检索证据。
- 写作者只能基于 evidence 写草稿。
- 审核员检查是否存在证据和引用标记。
- 定稿节点在无证据时拒绝回答。

这比让三个自由 Agent 相互聊天更容易测试。只有当角色需要独立模型策略或工具集时，才升级为真正的多 Agent 调用。

## 必做练习

1. 给知识库添加两篇内容相近的资料，记录 Top-3 分数并分析误召回。
2. 修改已有 `document_id` 的文档，验证内存与 pgvector 适配器都执行原子替换。
3. 为记忆增加“同 key 更新”策略，说明覆盖还是保留版本。
4. 在审核节点加入最低检索分数，验证低相关证据会被拒绝。
5. 设计从内存索引迁移 pgvector 时不应变化的接口。

## 通关标准

- 全部自动化测试通过。
- 新资料可以索引并返回可核验 source。
- 无相关证据时系统明确拒答。
- 未批准的长期记忆返回 403，其他 owner 无法删除。
- 能分别定位切片、检索、写作和审核错误。

## 排查顺序

1. 原始文档是否为空或被错误规范化。
2. 切片是否把关键语义截断。
3. 查询与切片是否有共享 token。
4. 排名和 limit 是否丢失正确证据。
5. evidence 是否完整进入写作节点。
6. 审核规则是否与引用结构一致。
