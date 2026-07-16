# M11：上下文、持久记忆与真实 RAG

> 工程状态只查看 `../continuity/status.md`。M11 使用集成专用 Compose；主 Compose 的生产化由 M13 完成。

## 本阶段目标

把 Run、事件、审批、checkpoint、记忆和知识库从进程内迁移到 PostgreSQL/pgvector，建立可解释的上下文预算和固定 RAG 评测。

- 时间预算：3 周，约 28–42 小时。
- 任务：M11-T1 至 M11-T8。
- 在线门：M11-T7 单独授权，不阻塞默认数据库集成。
- 工作映射：企业知识库、长会话助手、任务恢复和检索质量治理。

## 20% 关键知识

| 类型 | 知识点 | 工作场景 | 学到什么程度 | 验证任务 |
| --- | --- | --- | --- | --- |
| 必学 | migration、事务、约束 | 持久 Agent 服务 | 空库可迁移且重复安全 | M11-T1 |
| 必学 | Run/Event/Checkpoint 差异 | 恢复与审计 | 能重启后恢复 | M11-T1 |
| 必学 | Embedding、pgvector、引用 | RAG | 真实写入和查询 | M11-T2、T3 |
| 必学 | 上下文选择和 Token 预算 | 长对话 | 能解释保留/裁剪 | M11-T4 |
| 高频 | 记忆来源、审批、纠正和删除 | 个性化助手 | 持久且不污染 | M11-T5 |
| 易错 | 只测 Fake DB 就宣称向量库完成 | 集成验收 | 能区分单测和真实集成 | M11-T2 |
| 易错 | 召回正确等于回答正确 | RAG 评测 | 能分层定位失败 | M11-T6 |

## 跟练顺序

1. 用 `deploy/compose.integration.yaml` 启动 PostgreSQL/pgvector，在空库运行 migration。
2. 让内存和 PostgreSQL Store 运行同一契约；演示等待审批后销毁并重建应用实例。
3. 使用确定性 Embedding 走真实 vector 列，完成文档增删改和引用检索。
4. 实现 ContextAssembler，输出每段上下文的来源、信任等级、Token 与裁剪原因。
5. 将消息与批准记忆接入主上下文，演示纠正、删除、越权拒绝和重启恢复。
6. 建立不少于 50 条查询的固定评测，分别分析切片、召回、排序和生成失败。
7. 只有单次授权后运行真实 Embedding 冒烟。

## 计划验证命令

```powershell
docker compose -f deploy/compose.integration.yaml up -d --build
.\.venv\Scripts\python.exe -B -m unittest backend.tests.integration.test_migrations -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.integration.test_postgres_stores -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.integration.test_pgvector_retrieval -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_context_assembler backend.tests.integration.test_persistent_memory -v
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_rag_evals -v
```

在线计划命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify-online.ps1 -Suite M11
```

## 评测最低要求

- 固定数据集不少于 50 条查询。
- 每条期望文档和引用均版本化。
- 同时记录 Recall@K、MRR、回答依据正确率、延迟和失败类别。
- 空证据受控拒答；引用必须能定位文档和切片。
- 阈值由首个可复现基线确定并版本化，不根据失败结果临时下调。

## 常见错误与排查

| 现象 | 原因 | 排查 |
| --- | --- | --- |
| 应用启动自动改表 | migration 与启动逻辑混合 | 把 Schema 变化移到显式 migration |
| 重启后 Run 有但 checkpoint 无 | Store 与 checkpointer 不是同一持久配置 | 检查连接、thread ID 和提交事务 |
| 向量维度错误 | Embedding 配置漂移 | 对比模型、维度和配置指纹 |
| 长对话关键事实消失 | 裁剪顺序或摘要错误 | 查看预算报告和来源标记 |
| 删除记忆后仍出现 | 缓存或 Context 未刷新 | 查 MemoryStore 版本与 assembler 输入 |
| 回答错但 hit-rate 高 | 生成阶段未使用证据 | 分开检索指标与答案依据指标 |

## 自测

1. EventStore、ConversationMessage 和 checkpoint 为什么不能合成一张无边界表？
2. 从空数据库完成 migration，并排查一次故意失败。
3. 给定超预算上下文，手工预测保留和裁剪顺序。
4. 为什么模型总结不能自动成为长期事实？
5. 给定一个错误答案，判断是切片、Embedding、召回、排序还是生成问题。

## 费曼复述

用“有限行李箱”解释上下文预算，用“图书索引”解释 Embedding/pgvector，用“经本人确认的档案”解释长期记忆。

## 官方资源

- pgvector：<https://github.com/pgvector/pgvector>
- PostgreSQL Transactions：<https://www.postgresql.org/docs/current/tutorial-transactions.html>
- LangGraph Persistence：<https://docs.langchain.com/oss/python/langgraph/persistence>
- OpenAI Embeddings：<https://developers.openai.com/api/docs/guides/embeddings>
