# M10 LangGraph 持久工作流一页速查表

## 一句话定义

- Checkpoint：工作流在一个 thread 上的版本化快照，不是 Run 事件流水。
- Interrupt/Resume：图在安全边界暂停，服务端核对审批后用 `Command(resume=...)` 继续。
- Replanning：失败后按白名单、类别、副作用和预算决定是否换路线，不是无条件重试。
- 多 Agent：一种有额外调用、预算和失败面的编排选择，只有固定对照显示收益时才采用。

## 三张图

```text
Run：created -> running -> waiting_approval -> running -> terminal

Graph：START -> plan -> execute -> END
                  ^        |
                  + replan <- diagnose

恢复：terminal -> 直接返回
      pending read-only -> 同进程共享 saver 后继续
      pending side-effect -> side_effect_resume_unsafe
      invalid/unavailable checkpoint -> 稳定失败
```

## 四类存储职责

| 组件 | 保存什么 | 不负责什么 |
| --- | --- | --- |
| Checkpointer | graph state、next node、版本化安全字段 | Run 事件查询、跨进程 exactly-once |
| RunStore | Run owner、状态、版本、终态 | graph 节点快照 |
| EventStore | 生命周期与过程事件顺序 | 恢复 graph 局部状态 |
| ApprovalStore | 服务端审批请求、决议、私有参数、单次 grant | 客户端授权、持久 ToolExecution 结果 |

## 重规划五问

按顺序全部回答“是”才允许 replan：

1. `failure.retryable` 是否为真？
2. code 是否命中服务端白名单？
3. category 是否避开 auth/validation/approval/security/storage/cancellation？
4. 失败步骤是否无副作用且不需要审批？
5. step、replan 和路径循环预算是否仍允许？

任一为“否”就稳定停止。不要原地重试结果未知步骤。

## 审批恢复检查

```text
server-owned run + principal + call + tool + arguments_digest
  -> prepare ApprovalRequest
  -> interrupt
  -> waiting_approval + event（原子提交）
  -> server resolution: approve | reject
  -> Command(resume={approval_id})
  -> ToolRegistry 再校验并消费一次 grant
```

- 原始参数只在服务端私有 Store，不进 checkpoint/event/repr。
- 客户端布尔值、模型文本、Skill 和 changed digest 都不能授权。
- 已消费 grant + 非终态 checkpoint 表示结果未知：`side_effect_resume_unsafe` + `approval.stopped`。

## Workflow、单 Agent、多 Agent 怎么选

| 场景 | 优先选择 | 判断依据 |
| --- | --- | --- |
| 固定步骤、固定规则 | Workflow | 可预测、易测试、无自主改路需求 |
| 开放任务、有限工具 | 单 Agent | 最低编排复杂度，先建立对照基线 |
| 角色确有独立上下文/工具且质量显著提升 | 多 Agent | 固定集质量/失败率收益覆盖额外调用与故障面 |
| 副作用结果未知 | 都不自动重试 | 先 fail closed，等待持久幂等与恢复仲裁 |

当前固定离线集：manager 与单 Agent 质量均为 1.0、失败率均为 0；manager 每例 9 次 fixture request/108 fixture Token/复杂度 12，单 Agent为 3/36/3，因此保留单 Agent。这不是 Provider usage、账单或生产性能结论。

## 稳定错误定位

| 稳定 code/事件 | 含义 | 第一检查点 |
| --- | --- | --- |
| `checkpoint_thread_required` | 缺可信 thread context | Coordinator 是否从 stored owner/run 派生 |
| `checkpoint_version_unsupported` | state 版本不支持 | migrator/fixture 是否存在；不要静默降级 |
| `checkpoint_scope_mismatch` | owner scope 不匹配 | owner/run/thread 绑定 |
| `checkpoint_state_invalid` | state 结构损坏 | Schema、计数、plan metadata |
| `approval_checkpoint_missing` | waiting 恢复缺 checkpoint | 是否误换 saver/进程已退出 |
| `approval_checkpoint_mismatch` | resume 与 checkpoint 不同 | call/tool/digest/approval ID |
| `replan_budget_exhausted` | 改路预算用尽 | replan count 与停止条件 |
| `replan_loop_detected` | 操作路径重复 | operation signature，不看 cosmetic step ID |
| `side_effect_replan_forbidden` | 副作用失败禁止改路 | step metadata 与真实工具策略 |
| `side_effect_resume_unsafe` | pending 副作用结果未知 | 不重放，查看 `plan.stopped`/`approval.stopped` |

排查顺序：Run/owner/thread -> saver -> state version/shape -> Run/Event -> approval binding/grant -> failure gate -> budgets -> side-effect outcome -> multi-Agent metrics。

## 最小命令

```powershell
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_langgraph_checkpointing backend.tests.test_langgraph_approval_resume backend.tests.test_langgraph_replanning backend.tests.test_langgraph_recovery_faults backend.tests.test_multi_agent backend.tests.test_workflow_comparison_eval -v
.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.multi_agent
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

## 证据红线

- `InMemorySaver` 只证明同进程跨 invocation/换 Runtime 实例，不证明操作系统进程重启。
- fixture Model/Token/延迟只证明离线框架和相对开销，不是 Provider、账单或生产性能。
- approval 单次消费证明 at-most-once；跨崩溃 exactly-once 仍需要持久 ToolExecution、lease 和恢复扫描。
- M10 的默认 Container、HTTP/SSE 和 PostgreSQL 尚未迁移，分别由 M11/M12 承接。

## 五问自检

1. checkpoint、EventStore、RunStore 各解决什么问题？
2. 为什么客户端不能提供 thread ID 或 `approved=true`？
3. 只读 timeout 和副作用 timeout 为什么走不同路径？
4. 同进程新 Runtime 恢复为什么不等于服务器重启恢复？
5. 什么固定证据足以让你从单 Agent 升级到多 Agent？
