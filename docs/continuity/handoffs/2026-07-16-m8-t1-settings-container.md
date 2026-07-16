# M8-T1 Settings 与应用容器交接

## 快照

- 日期：2026-07-16，Asia/Shanghai
- 计划版本：2.0
- 完成任务：`M8-T1`
- 结果：`verified`
- 分支：`main`
- 已验证实现提交：`c8b968b`
- 验证证据：`V-20260716-003`
- 远程仓库：未配置
- 在线调用：未执行，费用为 0

## 本次完成

1. 新增冻结 Settings 与单 Run 预算，显式解析进程环境，不自动加载 `.env`。
2. 分离 Runtime 与 Model Provider；默认固定为 `manual + mock + online=false`。
3. 建立 OpenAI 完整门禁：在线 Runtime、Provider、开关、Key、模型名和有限预算缺一不可。
4. 使用 `SecretStr`、字段排除、安全错误摘要和 `safe_summary()` 防止 Key 进入表示、JSON、异常和普通日志。
5. 分离 Run 总超时、模型超时、模型调用数和模型重试；Token 与费用按单 Run 累计限制。
6. 新增小型 `ApplicationContainer`，收拢现有 Run Service、Knowledge、Memory 和 Authenticator。
7. `create_app()` 支持 Container 与显式 Settings，同时保留旧四参数的关键字和位置注入兼容。
8. 配置错误在知识 seed 等副作用前失败；默认 Container 通过双 socket 守卫证明不发网络连接。
9. 新增 ADR-0005、环境模板、后端规约和 M8 配置速查；未新增或安装依赖。

## 关键文件

- `backend/app/settings.py`
- `backend/app/container.py`
- `backend/app/main.py`
- `backend/tests/test_settings.py`
- `backend/tests/test_container.py`
- `backend/.env.example`
- [ADR-0005](../decisions/ADR-0005-explicit-settings-without-dotenv.md)
- [M8 跟练文档](../../stages/08-real-model-runtimes.md)
- [当前状态](../status.md)
- [验证日志](../verification-log.md)

## 已固定的配置边界

```text
默认：manual + mock + online=false

openai 有效配置：
  runtime in {agents_sdk, langgraph}
  + provider=openai
  + online=true
  + non-empty safe API key
  + non-empty safe model name
  + bounded per-run budget
  + trace_include_sensitive=false
```

仅设置 Key 或模型名不会切换 Provider，也不会创建在线 Runner。`langgraph + mock` 是合法离线路径；`agents_sdk + mock` fail closed。

## 实际验证摘要

- 定向 Settings、Container、API、Identity：46 项通过。
- 全后端：121 项运行，120 项通过，1 项既有 Windows 符号链接能力测试跳过，0 失败。
- `pip check`：通过；Pydantic 版本 2.13.4。
- Vue 生产构建与 TypeScript MCP Server 构建：通过。
- Compose 配置解析、连续性检查与 `git diff --check`：通过。
- 敏感扫描没有发现真实 API Key 或认证 Token。

## 失败尝试与警告

- 测试先行的第一次运行因 `settings.py`、`container.py` 尚不存在而产生 2 个预期 ImportError；实现后转绿。
- 审查补测第一次运行因测试补丁缩进错误产生 `IndentationError`；修正后定向与全量回归均通过。
- 后端仍有既有 Starlette/httpx2 弃用警告，没有在本任务擅自升级依赖。
- Windows 符号链接安全测试仍按 `OSError` 跳过，与 C0 基线一致。
- Docker Compose 能解析，但用户级 Docker config 无法读取且 Engine 未运行；未验证容器运行态。

## 尚未完成

- Settings 预算目前只负责解析与校验；M8-T3/M8-T4 才接入 Runtime 消耗与中止逻辑。
- Container 尚未包含 Runtime、RunCoordinator 或 Store；这些分别属于 M8-T2/M8-T3。
- SDK 文件仍只构造 Agent，真实 Runner/stream 属于 M8-T4。
- 在线模型冒烟属于 M8-T6，仍需用户单次授权。

## 下一条原子动作

开始 `M8-T2`：读取 `backend/app/services/run_service.py`、`backend/app/domain/agent.py`、`backend/app/api/schemas.py` 和关联测试；先定义不可变状态转换、事件序号和异步 Store 契约测试。不要提前接 Runtime、数据库或 SSE，也不要删除旧 `RunRecord`，直到迁移兼容测试明确通过。

## 恢复检查

```powershell
git status --short
git log -3 --oneline
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_settings backend.tests.test_container -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

如果结果与 `V-20260716-003` 不一致，先登记 known issue，再继续 M8-T2。
