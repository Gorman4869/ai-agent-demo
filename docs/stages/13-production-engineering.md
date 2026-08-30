# M13：生产工程、观测、测试与部署

> 工程状态只查看 `../continuity/status.md`。CI Provider 在用户提供远程仓库后确定；平台无关验证入口先完成。

## 本阶段目标

把主链路升级成可观测、可分层验证、可实际容器部署、可限流降级和可重复故障演练的单实例生产基线。

- 时间预算：2 周，约 22–34 小时。
- 任务：M13-T1 至 M13-T7。
- 工作映射：AI 服务上线、质量门禁、故障响应、成本治理和安全审计。

## 20% 关键知识

| 类型 | 知识点 | 工作场景 | 学到什么程度 | 验证任务 |
| --- | --- | --- | --- | --- |
| 必学 | 稳定错误、重试、超时、取消 | 外部模型和工具 | 按错误类型采取策略 | M13-T2 |
| 必学 | log/metric/trace | 故障定位 | run ID 可串联全链路 | M13-T1 |
| 必学 | 测试分层和 CI 门禁 | 团队交付 | 跳过不伪装通过 | M13-T3 |
| 必学 | migration/readiness/health | 容器部署 | 干净环境可启动 | M13-T4 |
| 高频 | usage、成本和质量阈值 | 预算治理 | 能解释质量/成本取舍 | M13-T1、T6 |
| 易错 | Observer/Exporter 失败拖垮业务 | 可观测性 | 观测降级不影响 Run | M13-T1 |
| 易错 | 输出截断等于内存有界 | 代码 Agent | 流式有界读取 | M13-T5 |

## 跟练顺序

1. 注入 provider 429、鉴权失败、工具超时和数据库断开，建立稳定错误与重试矩阵。
2. 为 Run、模型、工具、MCP、RAG、数据库增加相关联 trace/metrics sink，并验证脱敏。
3. 把验证拆成 offline、MCP、database、frontend、E2E、Docker 和 online profiles。
4. 修复“Docker 缺失仍打印全部通过”的误导行为。
5. 将 M11 integration Compose 生产化，实际验证 migration、readiness、Nginx SSE 和重启恢复。
6. 修复代码 Agent 无界输出和子进程树问题。
7. 运行固定负载和故障演练，更新容量估算与运行手册。

## 计划验证入口

脚本提供以下清晰 profile；名称进入代码后不得随意漂移：

```powershell
powershell -ExecutionPolicy Bypass -File ./scripts/verify.ps1 -Profile offline
powershell -ExecutionPolicy Bypass -File ./scripts/verify.ps1 -Profile mcp
powershell -ExecutionPolicy Bypass -File ./scripts/verify.ps1 -Profile integration
powershell -ExecutionPolicy Bypass -File ./scripts/verify.ps1 -Profile frontend
powershell -ExecutionPolicy Bypass -File ./scripts/verify.ps1 -Profile e2e
powershell -ExecutionPolicy Bypass -File ./scripts/verify.ps1 -Profile docker
```

以上命令落盘后统一使用正斜杠路径；`integration` 是 `postgresql` 的稳定别名。在线 profile
没有本次授权时只显式汇总为 `SKIPPED`，普通 CI 不传入密钥或授权开关：

```powershell
powershell -ExecutionPolicy Bypass -File ./scripts/verify.ps1 -Profile online
```

真实在线调用仍需用户对本次执行重新授权，再显式增加 `-AuthorizedOnline`；不得从旧会话、Key
存在或 CI secret 推断授权。

## 可观测性最低字段

- run ID、trace ID、principal 摘要和 Runtime。
- 节点、模型、工具、MCP、RAG、数据库耗时。
- 输入、输出、缓存等可用 usage 字段与估算成本版本。
- 重试次数、错误类别、取消和预算终止。
- 不记录 API Key、Authorization、默认 Prompt 原文、完整工具参数和原始图片。

## 常见错误与排查

| 现象 | 原因 | 排查 |
| --- | --- | --- |
| Trace exporter 挂了导致 Run 失败 | 观测与业务强耦合 | 隔离 sink 错误并记录降级指标 |
| CI 显示通过但 Docker 未跑 | skip 汇总不严格 | required profile 缺工具时直接失败 |
| 容器 healthy 但不能服务 | health 未检查依赖 | 区分 liveness 与 readiness |
| Nginx 下不实时 | 代理缓冲 | 检查 buffering、超时和响应头 |
| 命令输出仍耗尽内存 | 先 PIPE 全量读取再截断 | 改用增量读取和硬上限 |
| 取消后留下子进程 | 只终止父进程 | 验证进程组/Job Object 清理 |

## 自测

1. log、metric、trace 分别适合回答什么问题？
2. 429、401、参数错误和有副作用工具超时应如何处理？
3. 为什么 liveness 通过不代表服务 ready？
4. 设计 PR、合并和发布三个阶段的测试 profile。
5. 给定“质量上升 5%、成本翻倍”，如何决定是否发布？

## 费曼复述

用“医院急诊记录、生命体征和检查链路”解释日志、指标和 Trace；用“消防演练”解释故障注入为什么必须重复执行。

## 官方资源

- OpenTelemetry Documentation：<https://opentelemetry.io/docs/>
- Docker Multi-stage builds：<https://docs.docker.com/build/building/multi-stage/>
- Docker Compose services：<https://docs.docker.com/reference/compose-file/services/>
- OWASP Agentic Security Initiative：<https://genai.owasp.org/initiatives/agentic-security-initiative/>
