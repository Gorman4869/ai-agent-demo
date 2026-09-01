# M13-T6 基础压测与故障演练

本文记录单机 Docker Desktop 环境中的一个可重复工作点，以及离线故障合同。它是工程验收证据，
不是生产容量、SLA 或线上 Provider 性能承诺。

## 一条命令

在仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify-load-fault.ps1
```

脚本为每次运行创建唯一 `ai-agent-demo-m13-load-*` Compose project，复用 M13-T4 的临时 secret
文件生命周期，完成后只删除该 project 的容器、网络、卷和临时文件。它不删除镜像，不触碰
`ai-agent-demo-integration`，也不读取 Provider Key 或用户 `.env`。

默认负载固定为 16 个 Run、并发度 4。`Runs` 允许 1–100，`Concurrency` 允许 1–16 且不能
超过 Runs；参数是有界验证开关，不是任意压测入口。

## 覆盖场景

| 场景 | 真实路径 | 通过条件 |
| --- | --- | --- |
| 并发 Run | 内存 `ApplicationContainer` 与 localhost Nginx/FastAPI/PostgreSQL durable HTTP | 全部完成、错误率 0，记录延迟、吞吐、并发峰值和 RSS |
| 慢 SSE 客户端 | 实际 `_durable_event_stream`，客户端读取 started 后暂停 100ms | Run 完成不被慢消费阻塞 |
| 模型限流 | `ManualAgentLoop` 与确定性 `RetryableModelError` | 仅重试一次、第二次恢复、产生一个 retry event |
| PostgreSQL 断开 | 停止本次 project 的 postgres，再发送 durable Run | 请求无响应或返回 5xx；不得退回内存成功 |
| 数据库恢复 | 启动 postgres 后以幂等请求验证新 Run | 响应未知时重放同一键；明确终态失败后才换键，最多 8 次，最终完成 |
| backend 重启 | 重启本次 project 的 backend | 健康恢复，故障前已完成 Run 仍可读取 |

结果未知与明确失败必须分开：若数据库已经提交 Run、但响应组装失败，重放响应可以不再次回传
`session_capability`；客户端继续使用自己持有的 capability 查询原 Run。只有查询明确得到
`failed/cancelled`，旧请求才已确定终止，演练才能换新幂等键验证恢复。

## 2026-09-01 实测工作点

相同负载/故障逻辑连续三次完整通过并自动清理；第三次还验证了修正后的 skip 证据标签：

| 指标 | 第一次 | 第二次 | 最终标签修正后 |
| --- | ---: | ---: | ---: |
| 部署 Run | 16/16，0% 错误 | 16/16，0% 错误 | 16/16，0% 错误 |
| 配置并发度 | 4 | 4 | 4 |
| 吞吐 | 17.333 Run/s | 11.557 Run/s | 6.639 Run/s |
| p50 | 148.315 ms | 219.651 ms | 354.138 ms |
| p95 / max | 498.490 ms | 708.766 ms | 1,542.506 ms |
| Probe 进程 RSS 增量 | 10,481,664 bytes | 10,936,320 bytes | 11,292,672 bytes |
| DB outage | HTTP 5xx | HTTP 5xx | HTTP 5xx |
| 恢复前明确失败 Run | 3 | 2 | 3 |
| 新 Run 恢复 / backend restart 读取 | 通过 / 通过 | 通过 / 通过 | 通过 / 通过 |

因此当前容量估算只固定为：在这台机器、当前镜像、离线 Mock Runtime、单 backend 和本地
PostgreSQL 下，`16 Runs / concurrency 4` 是重复三次无错误的工作点；保守观测吞吐约 6.6 Run/s，
观测 p95 不高于约 1.55s。三轮差异本身说明短样本波动明显，没有证据把更高并发、长时间持续
负载或该数值外推到生产。

Docker `stats --no-stream` 是四个阶段的点快照，不是峰值采样。三次 `after_load` 的大致内存为：

- backend：97.75–97.91 MiB；
- PostgreSQL：49.15–51.11 MiB；
- frontend：7.60–7.67 MiB。

CPU 快照受采样时刻影响较大，只保留在 verification 原始报告中，不用来计算容量上限。

## 安全报告

`backend.app.load_fault_probe` 只输出场景名、计数、稳定错误码、延迟、吞吐、RSS 和受控测量值。
它不保留 prompt、answer、capability、异常文本或响应正文；未知异常统一为
`scenario_internal_error`。localhost 探针只接受显式 `http://127.0.0.1:port` 或
`http://localhost:port`，拒绝凭据、路径、query、fragment 和远程主机。

## 证据边界

- 模型限流使用确定性 Fake Model，证明本项目重试合同和指标，不证明真实 Provider 的限流语义、
  Token、usage、费用或网络撤销。
- 慢客户端是单客户端 100ms 暂停，不是大量长连接、代理超时或公网断流测试。
- 数据库演练证明 fail-closed、连接恢复和已完成数据的 backend restart 可读；不证明高可用、备份、
  failover、多主、多进程终态竞争或进行中 Run 被硬杀后的完整恢复。
- 三次短样本不能替代 soak、阶梯增压、峰值资源采样、TLS、公网入口和生产流量回放。

## 失败排查

脚本失败时会打印本次 project 的有界 `compose ps` 和尾部日志，然后仍执行精确 cleanup。先确认
失败阶段，再看安全错误码或 HTTP 状态；不要用全局 `docker compose down`、删除镜像或清理其他
project 作为恢复手段。重复运行前可用本次输出的 project 名只读检查是否残留。
