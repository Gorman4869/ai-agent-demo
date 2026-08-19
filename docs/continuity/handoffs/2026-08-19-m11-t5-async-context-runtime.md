# M11-T5 交接：async Context Runtime preparation 第二纵切

- 日期：2026-08-19，Asia/Shanghai
- 当前任务：`M11-T5 / in_progress`
- 内部步骤：第二离线纵切完成；默认 PostgreSQL Runtime composition 尚未开始
- 任务等级：A 类 async persistence/context 边界；时间盒 2–4 小时
- 验证基线：`f06b510`（`feat:m2 stage`）；第一纵切实现提交：`2b248a5`
- 工作区验证：`V-20260819-001/002`
- 关联决策：`ADR-0014`、`ADR-0021`、`ADR-0022`、`ADR-0025`、`ADR-0026`；本轮没有改变既有协议结论，因此没有新增 ADR
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 真实数据库：未运行
- 远程仓库：未配置，未 push

## 本轮结果

- 新增独立 `prepare_async_context_request()` 与 `AsyncContextAwareRuntime`，await `AsyncMemoryContextSourceCollector` 后复用既有 Runtime binding、Assembler、PreparedContextRequest 和稳定失败合同。
- 已有 prompt、缺失 identity、cross-owner、Store failure/timeout 在 delegate 前 fail closed；调用方取消和依赖程序错误原样传播。
- 正常结果与 approval pause 原样透传；非空 Context 只替换 prompt_context，execution/checkpoint/context identity、emit 与 control 保持，delegate 只调用一次。
- 聚焦复审后让同步 `backend/app/context/runtime.py` 保持无 diff；async 代码只位于独立模块并由 Context package 导出。

## 验证摘要

- 恢复 handoff 相关 116 项、M1 10 项和连续性 52/106 通过；Git 确认第一纵切提交为 `2b248a5`，后续学习提交没有修改 M11 Context 实现。
- 新增 11 个关键测试；async/sync Runtime 专项 24 项通过。
- 最终 Context/async Store/Container/Memory/PostgreSQL composition 相关回归 127 项通过；只有既有 Starlette/httpx 警告。
- M1 `python -S` 10 项通过；没有修改共享 RuntimeRequest/AgentRuntime/Store/Container/HTTP 合同，因此未运行完整全仓门。

## 修改文件

- 实现：`backend/app/context/async_runtime.py`、`backend/app/context/__init__.py`
- 测试：`backend/tests/test_async_context_runtime.py`
- 规约与计划：`BACKEND_CODING_STANDARDS.md`、`docs/implementation-plan.md`
- 连续性：`docs/continuity/verification-log.md`、`docs/continuity/known-issues.md`、`docs/continuity/status.md` 与本 handoff
- handoff 写入时上述文件均为本轮未提交改动，没有发现任务外改动。最终本地提交由结束时 `git log` 确认，下一份 verification/handoff 再记录新 HEAD。

## 聚焦复审

- prompt 冲突先于 binding/Store；missing identity、cross-owner、Store failure/timeout 都不会调用 delegate。
- CancelledError 没有归一为 Runtime failure；binding/dependency TypeError 不被吞掉。
- Runtime failure、repr 与公开导出不包含 owner、session、query、fact content、原始 Store 错误或 bridge 结果细节。
- 同步 ContextAwareRuntime、默认内存 Container、显式 caller Runtime mappings 和 PostgreSQL legacy Skill wrapper 均保持不变。

## 未验证范围

- 新 AsyncContextAwareRuntime 尚未进入默认 PostgreSQL Container；不能描述成持久 fact 已进入 Agent 或主 Run。
- 没有执行真实 PostgreSQL/pgvector、数据库重启、连接/pool 故障或持久 Context→Agent。
- Run 尚未写入用户/assistant 消息；纠正/删除、版本冲突、审计和“模型推测不自动写入”仍由 M11-T5 后续纵切承担。
- 没有在线摘要、Provider、真实模型、Token/usage、费用或账单证据；M11-T6/M11-T7/M12/M13 范围不变。

## 下一条原子动作

开始 `M11-T5` 第三个离线纵切，只迁移默认 PostgreSQL built-in Runtime composition：

- 使用 composition owned `async_memory_store` 构造 `AsyncMemoryContextSourceCollector`，并以单一 `AsyncContextAwareRuntime` 包装内建 Manual/LangGraph/SDK Runtime；不得叠加 legacy `SkillAwareRuntime`。
- 默认内存 `ApplicationContainer.create()` 与显式 caller-supplied Runtime mappings 保持原对象和现有行为；RuntimeRequest、AgentRuntime、HTTP 与 Store Protocol 不变。
- Knowledge、Skill、summary 仍只允许进程内非阻塞实现；不要把同步 pgvector、网络或模型调用放入事件循环。
- 本原子不写入消息、不实现纠正/删除、版本冲突/审计，不执行在线 Provider，也不进入 M11-T6。

## 恢复命令

```powershell
git status --short
git log -8 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_async_context_runtime backend.tests.test_async_context_collector backend.tests.test_context_collector backend.tests.test_context_assembler backend.tests.test_context_runtime backend.tests.test_container backend.tests.test_memory backend.tests.test_memory_store_contract backend.tests.test_postgres_async_stores backend.tests.test_postgres_execution backend.tests.test_application_lifecycle backend.tests.test_runtime_contract -q
.\.venv\Scripts\python.exe -S -X utf8 -B -m unittest backend.tests.test_manual_agent_loop -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

本轮相关 127 项与 M1 10 项已通过；连续性落盘后以 `V-20260819-002` 为准。恢复一致后不要重做 M11-T1–T4 或前两个纵切，下一步只迁移默认 PostgreSQL built-in Runtime composition；未经新授权不安装依赖、不读取 Key、不执行在线/付费调用、不运行真实数据库、不配置或推送远程 Git。
