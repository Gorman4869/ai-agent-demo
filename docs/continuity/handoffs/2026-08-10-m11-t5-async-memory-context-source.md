# M11-T5 交接：async Memory Context source 首个纵切

- 日期：2026-08-10，Asia/Shanghai
- 当前任务：`M11-T5 / in_progress`
- 内部步骤：第一离线纵切完成；async Runtime request preparation 尚未开始
- 任务等级：A 类 async persistence/context 边界；时间盒 2–4 小时
- 验证基线：`a96ea6d`（`feat: wire default container context`）
- 工作区验证：`V-20260810-001/002`
- 关联决策：`ADR-0014`、`ADR-0021`、`ADR-0022`、`ADR-0025`、`ADR-0026`；本轮没有改变既有协议结论，因此没有新增 ADR
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 真实数据库：未运行
- 远程仓库：未配置，未 push

## 本轮结果

- 新增显式 `AsyncMemoryContextSourceCollector`，只通过现有 `AsyncMemoryStore.messages()`/`facts()` 读取 Context Memory，不扩宽同步或异步 Store Protocol。
- 两次读取共享一个总 timeout；外层或 bridge Store timeout 映射为稳定 `memory_context_timeout`，其他 Store 错误映射为 `memory_context_unavailable`，调用方取消原样传播。
- async 读取结果进入请求级、非阻塞 Memory 快照，再复用现有同步 ContextSourceCollector，因此 owner 校验、source/trust、摘要、RAG/Skill fragment 与 Assembler 预算规则没有复制成第二套。
- 真实 AsyncLocalMemoryStore→collector→Assembler 纵切包含 system/Skill/approved fact/recent/RAG；两组 owner/session 隔离通过。
- 受控 AsyncPostgresMemoryStore façade 只调用 bridge，禁止直接执行的同步 Store 方法调用次数为 0；这不是实际 PostgreSQL 证据。

## 验证摘要

- 恢复上一 handoff 相关 244 项、M1 10 项和连续性 52/105 通过；HEAD `a96ea6d` 与 M11-T4 handoff 一致。
- 新增 11 个关键测试方法；首次 async+sync collector 20 项通过，聚焦复审后 collector+bridge 30 项通过。
- 最终 Context/async Store/Container/Memory/PostgreSQL composition 相关回归 116 项通过；只有既有 Starlette/httpx 警告，没有失败或新增 skip。
- M1 `python -S` 10 项通过；连续性落盘前为 52/105，落盘后预期为 52/106。
- 没有修改既有 Store/Runtime/Container 协议、依赖、数据库、构建或跨前后端接口，因此未运行完整全仓门、Vue/MCP 构建或真实数据库集成。

## 修改文件

- 实现：`backend/app/context/async_collector.py`、`backend/app/context/collector.py`、`backend/app/context/__init__.py`
- 测试：`backend/tests/test_async_context_collector.py`
- 规约与计划：`BACKEND_CODING_STANDARDS.md`、`docs/implementation-plan.md`
- 连续性：`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff
- handoff 写入时上述文件均为本轮未提交改动，没有发现任务外改动。最终本地提交由结束时 `git log` 确认，下一份 verification/handoff 再记录新 HEAD。

## 聚焦复审

- 顺序读取 message 后读取 fact；任一 Store 失败、timeout、取消、非法 payload 或 fact owner mismatch 均停止 Knowledge/Skill/summary，不返回部分结果。
- 外层 timeout 取消 façade await；若 PostgreSQL bridge worker 已运行，worker 生命周期仍由既有 bridge 追踪。本轮只有读取，没有自动重试，也不声称硬取消数据库 statement。
- 错误、repr 和预算报告不包含 owner、session、消息/fact 内容、DSN、原始 Store 错误或 bridge `result_unknown`。
- 同步 KnowledgeBase、SkillContextBuilder 和 summarizer 仍仅适用于进程内非阻塞实现；不得借新类把同步 pgvector、网络或模型调用放入事件循环。
- 没有业务测试失败、依赖安装、数据库操作、在线调用或范围扩张。

## 未验证范围

- 新 collector 尚未被 ContextAwareRuntime await，也未接默认 PostgreSQL Container；不能描述成持久 fact 已进入 Agent 或主 Run。
- 没有执行真实 PostgreSQL/pgvector、进程重启恢复、数据库连接超时或 pool 关闭；PostgreSQL no-direct-sync 使用受控 façade/bridge 合同，并引用既有 bridge 回归。
- Run 尚未写入用户/assistant 消息；纠正/删除、版本冲突、审计和“模型推测不自动写入”仍由 M11-T5 后续纵切承担。
- 没有在线摘要、Provider、真实模型、Token/usage、费用或账单证据；M11-T6/M11-T7/M12/M13 范围不变。

## 下一条原子动作

开始 `M11-T5` 第二个离线纵切，只固定 async Context Runtime request preparation：

- 新增独立 async preparation/Runtime adapter，await `AsyncMemoryContextSourceCollector.collect()`；不要改变现有同步 ContextAwareRuntime 行为或把两个 prompt owner 叠加。
- 复用 RuntimeIdentityBindingFactory、ContextCollectionInput、Assembler 和既有 `context_unavailable` 外部错误；已有 prompt、缺失 identity、owner mismatch 和 source 失败必须在 delegate 前 fail closed。
- 调用方 task 取消必须传播，不能归一为 Runtime failure；timeout/稳定 collection failure 才映射为 `context_unavailable`。正常终态、approval pause、执行/checkpoint context 与 delegate 单次调用保持。
- 本原子仍不接默认 PostgreSQL Container、不写入消息、不实现纠正/删除、版本冲突/审计，不运行真实数据库/在线 Provider，也不进入 M11-T6。

## 恢复命令

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_async_context_collector backend.tests.test_context_collector backend.tests.test_context_assembler backend.tests.test_context_runtime backend.tests.test_container backend.tests.test_memory backend.tests.test_memory_store_contract backend.tests.test_postgres_async_stores backend.tests.test_postgres_execution backend.tests.test_application_lifecycle backend.tests.test_runtime_contract -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

本轮相关 116 项与 M1 10 项已通过；连续性预期为 52 个稳定任务/106 个 Markdown。恢复一致后不要重做 M11-T1–T4 或第一纵切，下一步只固定 async Runtime preparation；未经新授权不安装依赖、不读取 Key、不执行在线/付费调用、不运行真实数据库、不配置或推送远程 Git。
