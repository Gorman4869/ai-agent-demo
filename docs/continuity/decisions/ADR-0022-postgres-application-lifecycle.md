# ADR-0022：显式 PostgreSQL 应用组合与 FastAPI 生命周期

- 状态：accepted
- 日期：2026-08-08
- 任务：`M11-T1`
- 依赖：`ADR-0005`、`ADR-0009`、`ADR-0019`、`ADR-0020`、`ADR-0021`

## 背景

M11-T1 前九个纵切已经提供 PostgreSQL Store、checkpointer、ToolExecution、lease/recovery、显式 execution composition、Coordinator quiesce 和同步 Approval/Memory 的 async bridge，但默认 `ApplicationContainer` 与 FastAPI lifespan 仍只使用内存资源和 MCP 生命周期。若只把 DSN 传给某个 adapter，应用仍可能双写、静默回退，或者在 HTTP/线程工作尚未结束时关闭 pool。

当前旧 Run HTTP/SSE 仍由 `InMemoryRunService` 提供，统一 durable Run API 明确属于 M12。M11-T1 需要接入数据库 application composition，但不能借此提前改写 M12 的公开 API 合同。

## 决策

### 1. PostgreSQL 必须显式选择并 fail closed

`Settings.persistence.backend` 只接受 `memory` 或 `postgres`，默认仍为 `memory`。`AI_AGENT_POSTGRES_DSN` 使用 `SecretStr`，不进入 repr、普通 dump、安全摘要、错误或日志；仅配置 DSN 不会自动启用数据库。

选择 `postgres` 时必须提供可解析 DSN，否则 Settings 构造失败。数据库打开、migration、checkpointer setup 或 supervisor 启动失败继续返回既有稳定错误，不创建内存 Store 作为后备。

### 2. 同步 create 与异步 open 分离

`ApplicationContainer.create()` 只组装默认内存应用。PostgreSQL 必须通过 `await ApplicationContainer.open()`：先构造无网络 Runtime/MCP 配置，再调用 `PostgresExecutionComposition.open()`，最后把真实 Run/Event Store、lease-aware Coordinator、同步 compatibility Store 和 `async_approval_store`/`async_memory_store` 放入同一 Container。

PostgreSQL 模式拒绝 `create_app()` 的 memory override，避免同一个应用同时暴露数据库 execution composition 与替代 memory adapter。旧 Run HTTP 仍使用 legacy service 且不向 durable Store 双写；该 API 迁移继续由 M12 负责。

### 3. 应用启动与回滚顺序固定

FastAPI lifespan 的启动顺序为：

```text
PostgresExecutionComposition.open/setup/supervisor
  -> MCP manager start
  -> application admission accepting
```

PostgreSQL Container 在 lifespan 内延迟打开；模块 import 和 `create_app()` 本身不连接数据库。MCP 启动失败或后续应用初始化失败时，关闭已经打开的 composition，并保留原始启动错误。

### 4. HTTP 与命令共享 admission

一个 `ApplicationAdmission` 同时服务纯 ASGI HTTP middleware 和 `ApplicationRunCommands`。关闭时先原子停止新工作，再等待 active 数归零。ASGI middleware 包裹完整 `receive/send` 调用，因此 StreamingResponse body 尚未结束时不会提前释放 admission。

应用关闭顺序为：

```text
HTTP/command admission close and drain
  -> PostgresExecutionComposition.close
     -> Coordinator quiesce
     -> recovery supervisor close
     -> sync Store bridge and pools close
  -> MCP manager close
```

composition 在 MCP 前关闭，是为了让 Coordinator 排空 active Runtime 时 MCP 连接仍可用。每一步即使取消也先完成其 owned cleanup；资源错误保持可见。

### 5. async 主链只使用 façade

记忆 HTTP 写入和删除改为 async handler，只调用 Container 的 `async_memory_store`。持久审批通过 `async_approval_store` 提供给 application command 边界；真实 PostgreSQL 用例实际执行 grant/consume。默认内存模式使用仅包装进程内非阻塞 Store 的 async adapter。

为兼容 M1–M10，Container 仍暴露同步 Approval/Memory Store，legacy ToolRegistry 也仍是同步合同。它们不得从 async event loop 直接调用；当前 legacy HTTP 的同步工具链由 FastAPI/显式 worker 承载并受外层 HTTP admission 追踪。`AI_AGENT_DEMO_AUTH_JSON` 的 legacy 静态预授权继续使用进程内 Store，避免在每次应用启动时重放持久 grant；统一持久审批 API 属于 M12。

## 后果

- 默认 import、测试和无配置运行继续离线、内存、无 Key、零费用。
- 显式 PostgreSQL 应用不再只证明 adapter import；真实 FastAPI lifespan 已跨两个应用实例恢复并删除同一 fact，Container 的 Approval façade 也执行真实 grant/consume。
- `KI-023` 的默认 async façade、HTTP/命令 admission 和 lifespan 关闭条件满足，可关闭。
- 旧 Run HTTP 尚未迁移到 durable Coordinator，不能把本决策描述成 M12 统一 API 已完成。
- Windows 上 psycopg async 仍要求宿主在创建事件循环前选择 Selector loop；库模块不修改全局 policy。本轮真实测试显式使用 Selector policy，不是通用部署配置证据。
- 本地 trust/tmpfs PostgreSQL、线程软取消、跨 pool 事务和外部副作用 exactly-once 的限制保持不变。

## 未采用方案

- DSN 存在即自动启用 PostgreSQL：会把凭据存在误当授权，并破坏默认离线行为。
- 在同步 `ApplicationContainer.create()` 内运行 event loop：会与 FastAPI/测试现有 loop 冲突并破坏资源所有权。
- FastAPI 函数式 middleware 只包裹 `call_next()`：可能在 StreamingResponse body 完成前释放 admission。
- shutdown 先关闭 MCP 再 quiesce Coordinator：active Runtime 可能在排空期间失去已建立的 MCP 工具连接。
- 把 legacy auth 静态 grant 每次启动写入 PostgreSQL：重启会重放一次性审批并与持久唯一约束冲突。
- 同时迁移旧 Run/SSE 与审批端点：属于 M12，超出 M11-T1 原子边界。

## 验证依据

- `backend/app/application_lifecycle.py`
- `backend/app/container.py`
- `backend/app/main.py`
- `backend/app/stores/async_facade.py`
- `backend/tests/test_application_lifecycle.py`
- `backend/tests/postgres_store_integration.py`
- `V-20260808-013`
