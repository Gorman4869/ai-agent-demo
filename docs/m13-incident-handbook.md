# M13 故障响应手册

本手册用于单实例 AI Agent 服务的受控教学排障。动态工程状态和历史实测结果仍以
[连续性状态页](continuity/status.md)与[验证日志](continuity/verification-log.md)为准。

## 一条原则

先保护证据和副作用边界，再恢复服务。未知故障不能用“多重试几次、重启全部容器、换一个
幂等键”碰运气。

## 事故响应七步

1. **止损**：暂停危险自动重试和新发布；不要删除容器、日志、数据库或历史 Run。
2. **定界**：记录时间、症状、HTTP status、Run ID、版本和受影响范围，不记录敏感正文。
3. **定位**：先看 run span，再下钻最细的 node/model/tool；用安全日志确认离散事实，用指标
   判断是单 Run 还是系统性故障。
4. **仲裁**：读取稳定错误码，确认结果是否未知，再走六道重试门。
5. **恢复**：只执行最小、可逆、作用域明确的动作；数据库/容器操作必须绑定精确 project。
6. **验证**：同时检查新 Run、故障前旧 Run、health/readiness、EventStore 终态和资源清理。
7. **复盘**：记录时间线、根因证据、失败尝试、恢复动作、残余风险和未验证范围。

## 首屏决策树

```text
用户症状
  -> 有 Run ID？
       否：从请求/页面安全元数据找；不要用 prompt 搜日志
       是：查 snapshot + observability
  -> run span 有终态？
       否：查 Store/readiness/正在运行或等待审批
       是：下钻最细 failed/retrying span
  -> 稳定错误是什么？结果是否未知？
       auth/invalid/rejected：不重试，修配置或请求
       transient + replay-safe：检查次数/deadline 后有界重试
       side effect/result-unknown：禁止自动重试，先权威仲裁
       store unavailable：fail closed，恢复数据库，不降级内存成功
  -> 运行最小验证层
  -> 新 Run 成功 + 旧 Run 可读 + 资源清理后才结束
```

## 六道重试门

下面六项必须全部为“是”，才允许进入下一次尝试：

1. 错误码稳定且 `retryable=true`；
2. 重试次数仍有余额；
3. 副作用操作具有持久幂等键；
4. 操作本身幂等且 replay-safe；
5. 结果未知时仍能证明重放安全；
6. 退避时间小于剩余 Run deadline。

人工审批只批准某次绑定后的工具调用，不会自动提供持久幂等键。任何证据缺失都 fail closed。

## 故障卡

### A. Provider 429 或临时不可用

- 第一证据：model span 的稳定错误码、attempt、delay 和剩余 deadline。
- 安全动作：只在模型重试预算内指数退避；确认 HTTP client 没有叠加隐藏重试。
- 恢复证明：出现有界 retry event，后续成功或稳定终态；取消获胜后不再开始下一次尝试。
- 不得宣称：Fake 429 等同真实 Provider 的限流、Token、费用或 SLA。

### B. Provider 401、请求拒绝或非法响应

- 第一证据：`provider_auth_failed`、`provider_request_rejected` 或
  `provider_invalid_response`。
- 安全动作：不重试；修复凭据注入或请求合同。不要把 Key 输出到终端、Trace 或文档。
- 恢复证明：离线合同先通过；在线复验必须获得新的单次授权。

### C. MCP/只读工具 timeout 或断线

- 第一证据：tool span、`mcp_timeout`/`mcp_disconnected`、工具的 side-effect policy。
- 安全动作：只有服务端目录确认无副作用并通过六道门时才有界重试。
- 恢复证明：retry attempt 有持久事件；结果由同一 Run 收敛，不重放整个 Runtime。

### D. 副作用工具 timeout 或结果未知

- 第一证据：ToolExecution、持久幂等键、approval binding 和权威外部状态。
- 安全动作：立即停止自动重试；先查询既有执行记录或由人工仲裁。审批不等于幂等。
- 恢复证明：同一操作只有一个权威结果；无法仲裁时保持 unknown，不伪装 failed/success。

### E. PostgreSQL 不可用

- 第一证据：HTTP 5xx、readiness、Store 稳定错误和 Run/Event 持久状态。
- 安全动作：fail closed；只恢复精确数据库/Compose project，不回退成内存成功。
- 结果未知：创建请求可能已提交但响应丢失，继续使用调用方持有的 capability 和同一幂等键。
- 明确终态：只有权威查询得到 `failed/cancelled`，才可用新 key 创建恢复验证 Run。
- 恢复证明：新 Run 成功、旧 completed Run 在 backend restart 后仍可读、无重复副作用。

### F. 容器 running 但服务不可用

- 第一证据：区分 container state、liveness、readiness、migration/seed 和业务纵切。
- 安全动作：按 `pgvector -> seed -> backend -> Nginx` 检查依赖，不跳过 migration。
- 恢复证明：health/readiness、migration 数量、课程 seed、Nginx API/SSE 和 restart recovery。

### G. Nginx 下 SSE 不实时或断线

- 第一证据：Run snapshot、EventStore sequence、SSE frame/cursor 和代理 buffering 配置。
- 安全动作：先确认 Run 是否仍在执行；观察断开不等于业务取消，不自动重放工具。
- 恢复证明：`run.started -> run.completed` 实时到达；断线后按 sequence 补发且无重复副作用。

### H. CI 显示成功但某层没跑

- 第一证据：七层汇总中的 `PASSED/FAILED/SKIPPED`，以及 job 的实际命令退出码。
- 安全动作：显式选择的 required layer 缺前置条件时失败；online 未授权只能明确 skip。
- 恢复证明：修复后的干净 runner 实际执行对应 job；不能用本地通过替代远程证据。

### I. 代码 Agent 无限输出、超时或残留孙进程

- 第一证据：稳定 process error、截断标记、采样预算、进程树清理结果和内容无关审计。
- 安全动作：持续排空 stdout/stderr，只保留有界前缀；timeout/取消/超限时终止整棵树。
- 恢复证明：父子孙进程均退出、资源回收、审计无源码/输出正文。
- 未证明：应用级 Job/process group 不是 cgroup、seccomp、VM 或默认禁网。

### J. usage 或成本异常

- 第一证据：同 Run 的有效 usage ledger sequence 与 `cost_source`。
- 安全动作：累计快照取最新值，不重复相加；`null/unknown` 保持未知。
- 恢复证明：账本可由 EventStore 重建，十进制费用来源明确。
- 未证明：当前没有逐调用 usage、版本化价格表或调用前硬成本门。

## 最小恢复五证

一次恢复至少同时提供：

| 证据 | 问题 |
| --- | --- |
| 新 Run | 新请求是否真正成功，而非只返回 health 200？ |
| 旧 Run | 故障前已完成数据是否仍可读取？ |
| 健康与依赖 | liveness、readiness、migration/seed 是否都满足？ |
| 持久终态 | EventStore/RunStore 是否收敛，是否有 unknown？ |
| 清理 | 临时 project、网络、卷、进程和 secret 文件是否精确清理？ |

只满足其中一项不能宣布恢复。例如 health 200 不能证明数据库写入，容器 running 不能证明
Nginx SSE，新的请求成功也不能证明旧数据没有丢失。

## 验证层选择

| 怀疑范围 | 先运行 | 升级条件 |
| --- | --- | --- |
| 稳定错误/重试 | reliability 定向测试 | 共享 Runtime 合同变化再跑 offline |
| MCP 协议 | `-Profile mcp` | 干净 runner/CI 失败再查 workflow |
| PostgreSQL | `-Profile integration` | 部署链问题再跑 deployment verifier |
| Vue 状态 | `-Profile frontend` | 浏览器恢复问题再跑 e2e |
| Compose 配置 | `-Profile docker` | 真实健康/SSE/restart 需 deployment verifier |
| 里程碑验收 | 默认 `verify.ps1` | 不自动包含在线或有状态 Docker 纵切 |
| 在线 Provider | `-Profile online` | 只有本次明确授权才加 online execution |

## 事故记录模板

```text
事故 ID：
时间范围：
版本/commit：
用户症状与影响范围：
HTTP status / Run ID：
最细失败层、步骤、稳定错误码：
相关日志事实（无正文/凭据）：
指标变化：
结果是否未知：
六道重试门结论：
止损与恢复动作：
失败尝试：
新 Run / 旧 Run / health / 持久终态 / 清理证据：
根因与修复：
残余风险和未验证范围：
```

## 禁止动作

- 不把 Key、Authorization、DSN、prompt、Memory、完整工具参数/结果或 raw exception 放入记录。
- 不因 timeout、页面刷新、SSE 断开或人工批准而自动重放副作用。
- 不把 unknown cost/usage 显示为 0，不把 skip 写成 pass。
- 不对不明确的 Docker project 执行全局 down/prune，不删除历史数据来“恢复”。
- 不把单机、Mock、短样本或配置检查描述为生产容量、HA、线上质量或费用事实。
