# M11-T5 默认 PostgreSQL Context composition 第三纵切交接

- 时间：2026-08-19 18:21，Asia/Shanghai
- 当前任务：`M11-T5 / in_progress`
- 验证基线：`ad7eafb`
- 第二纵切实现提交：`ad7eafb`
- 第三纵切实现提交：待本轮 Git 固定
- 证据：`V-20260819-003/004`
- 任务等级：A 类 async persistence/composition 边界；2–4 小时时间盒

## 已完成

- `PostgresExecutionComposition.open()` 新增同步 runtime factory seam，在 persistence setup 后、Coordinator/supervisor 前解析 built-in Runtime；显式 mapping 与 factory 必须二选一，结果复制为只读 mapping 并由 composition 暴露。
- factory 异常或返回空结果会关闭已打开 persistence；既有 setup、supervisor start/close、quiesce 和取消清理顺序保持。
- 默认 PostgreSQL `ApplicationContainer.open()` 使用 composition owned `async_memory_store`、进程内 Knowledge/Skill/system source 和单一 `AsyncContextAwareRuntime` 包装全部 built-in Runtime，不再叠加 `SkillAwareRuntime`。
- 默认内存 `ApplicationContainer.create()` 仍走同步 `ContextAwareRuntime`。显式 caller Runtime mapping 原对象透传，RuntimeRequest、AgentRuntime、Store、HTTP 和数据库 schema 没有变化。
- 受控真实纵切通过 Coordinator 执行 async Context Runtime，验证 system/skill/memory/recent/rag 五来源装配、同步 compatibility Memory 零调用、显式 Runtime 身份保持和应用生命周期。

## 修改文件

- `backend/app/postgres_execution.py`
- `backend/app/container.py`
- `backend/tests/test_postgres_execution.py`
- `backend/tests/test_container.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/implementation-plan.md`
- `docs/continuity/status.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/handoffs/2026-08-19-m11-t5-postgres-context-container.md`

## 验证快照

- 恢复基线：Context/async Store/Container/Memory/PostgreSQL composition 127 项、M1 隔离 10 项、连续性 52/107 通过。
- 最终 composition/Container 专项：39 项通过。
- 修改期共享回归：聚焦集合 131 项、扩大集合 283 项通过；最后新增 factory 空结果用例由专项 39 项和全量 578 项覆盖。
- 最终完整离线门：后端 578 项通过、1 项既有 Windows symlink 能力跳过；Code Agent、依赖、Vue、MCP TypeScript 与 Compose 配置全部通过。
- 首次完整门在 Node 14 下有 3 个 MCP SDK 启动超时；SDK 声明 `node >=18`。用户切换到 Node 22 后 MCP E2E 4 项通过。
- Node 22 下沙箱内完整门仍因 Vue tsbuildinfo 写入 `EPERM` 停止；同一脚本经授权在沙箱外退出 0。两次失败均已写入 `V-20260819-003`。

## 未验证与边界

- 未运行真实 PostgreSQL、数据库/进程重启、pgvector Context 或跨进程持久 fact→Agent；当前证据是 AsyncLocal façade 下的确定性应用接线 E3。
- 未实现主 Run 的 user/assistant 消息写入、纠正/删除、版本冲突、审计或模型推测禁写验收。
- Knowledge、Skill、summary 和 system source 仍只允许进程内非阻塞实现；不得把同步数据库或网络依赖放进 async collector。
- 未调用在线 Provider、读取 Key、产生费用、安装依赖、配置 remote 或执行 push。
- M11-T5 不得提升为 `verified`，KI-005/KI-014 只保持 mitigated。

## 失败尝试

- 首次专项有 2 个旧测试桩缺少新只读 `composition.runtimes` 属性；补齐测试桩后 39 项通过，未改变生产失败语义。
- Node 14 与 MCP SDK 1.29.0 引擎约束不兼容，导致 3 个 STDIO `startup_timeout`；切换 Node 22 后隔离与完整门通过。
- 沙箱内 Vue 构建无法写 `tsconfig.app.tsbuildinfo`；获批沙箱外重跑通过，没有改源码规避权限问题。

## 下一条原子动作

只开始 M11-T5 第四个离线纵切：先从现有 RunCoordinator、RuntimeResult 与 AsyncMemoryStore 合同确定 user/assistant 消息的唯一写入 owner、提交顺序、失败语义和幂等责任，再实现最小可验证链。保持读取主链、默认内存 compatibility、显式 Runtime mapping 和外部 API 不变；不提前实现纠正/删除、版本冲突/审计、真实数据库重启验收或 M11-T6。

## 恢复命令

```powershell
git status --short
git log -5 --oneline
node --version
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_postgres_execution backend.tests.test_container -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 Node 至少为 18；当前验证版本为 22.16.0。若上述 39 项和连续性与 `V-20260819-003/004` 一致，不要重做 M11-T1–T4 或 M11-T5 前三个纵切。
