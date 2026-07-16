# M8-T2 持久 Run 与 Store 契约交接

## 快照

- 日期：2026-07-16，Asia/Shanghai
- 计划版本：2.0
- 完成任务：`M8-T2`
- 结果：`verified`
- 分支：`main`
- 已验证实现提交：`4ac81b4`
- 验证证据：`V-20260716-004`
- 远程仓库：未配置
- 在线调用：未执行，费用为 0

## 本次完成

1. 新增独立持久 Run 状态机、失败投影、ToolExecution、单模型调用 UsageRecord 与 StoredRunEvent。
2. 原始 Idempotency-Key 只保存 SHA-256；版本化规范请求摘要覆盖 session、Runtime、Provider、模型、输入和选项。
3. 新增 async `RunStore` / `EventStore` Protocol、稳定异常、内存实现和适配器无关合同 mixin。
4. 实现 owner 隔离、幂等重放/冲突、version CAS、event ID 重放、per-Run sequence、游标分页和深度 JSON 快照。
5. 内存 append 使用 Run lock → Event lock 固定顺序，关闭终态检查 TOCTOU；无反向公共锁链。
6. JSON 边界拒绝非标准数字、非法 Unicode、非字符串 Key、循环、超深/超多节点和超限字节。
7. 副作用工具从创建起要求幂等摘要；原始参数/结果不持久化，日志使用安全投影。
8. Container 增加成对 Store 扩展缝，同时保留旧 `run_service`，没有双写或改旧 HTTP/SSE。
9. 旧 API Run 类型在 `main.py` 中别名为 `LegacyRunRecord`，避免和新领域类型误导入。
10. 新增 ADR-0006、M8 跟练速查、编码规范和 `KI-015` 事务风险记录。

## 关键文件

- `backend/app/domain/run.py`
- `backend/app/stores/base.py`
- `backend/app/stores/memory.py`
- `backend/tests/test_run_domain.py`
- `backend/tests/test_run_store_contract.py`
- `backend/app/container.py`
- [ADR-0006](../decisions/ADR-0006-durable-run-store-contract.md)
- [M8 跟练文档](../../stages/08-real-model-runtimes.md)
- [当前状态](../status.md)
- [验证日志](../verification-log.md)

## 已固定的核心语义

```text
幂等范围：(owner_id, idempotency_key_digest)
请求相同：返回原 Run 的当前快照
请求不同：idempotency_conflict

状态 CAS：run_id + owner_id + expected_version
事件重放：run_id + event_id + type + step + normalized data
事件游标：per-Run sequence，按 sequence 升序
锁序：Run lock -> Event lock
```

Store 错误只使用稳定 code；输入模型非法继续使用 `ValueError`。unknown owner 与 missing Run 不可区分。心跳不存储。

## 旧链与新链边界

```text
旧 run_service：现有同步 API、Mock 执行、旧 RunResponse/SSE
新 run_store/event_store：M8+ 持久异步主链基础
```

M8-T3 前不要删除旧类型、修改旧 `InMemoryRunService.create_run()` 返回值或让旧 API 双写新 Store。Store 替换通过完整 Container 完成，不继续扩张 `create_app()` 参数。

## 实际验证摘要

- 最终全后端：156 项通过，1 项既有 Windows 环境跳过，0 失败。
- 统一验证：Controlled Code-Agent Demo、pip check、Vue、MCP、Compose 配置全部通过。
- 连续性检查：52 个稳定任务、42 个 Markdown 文件通过；handoff 创建后需再次运行。
- 未新增或安装依赖；未访问模型网络，费用为 0。

## 残余风险

- `KI-015`：终态 Run 与终态事件还没有通用一次提交/事务边界。M8-T3 必须先定义用例契约，M11 再用 PostgreSQL 同事务实现。
- 内存 Store 只适合离线测试、学习和单进程开发，不能证明多 worker 幂等或持久恢复。
- Docker Engine/数据库容器仍未运行验证。
- 既有 Starlette/httpx 弃用警告和 Windows 符号链接跳过仍在。

## 下一条原子动作

开始 `M8-T3`：先写 `backend/tests/test_runtime_contract.py` 与 `backend/tests/test_run_coordinator.py` 的失败测试，固定 async Runtime 输入/结果、事件持久后通知、总超时、取消、Runtime 错误和终态状态/事件一致性。然后用 `ManualRuntime` 包装现有 `ManualAgentLoop`，不得重写旧 Loop 或提前接真实 SDK。

## 恢复检查

```powershell
git status --short
git log -3 --oneline
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_run_domain backend.tests.test_run_store_contract -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

若结果与 `V-20260716-004` 不一致，先登记 known issue，再继续 M8-T3。
