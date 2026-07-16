# 第 5 阶段：可观测性、离线评测与工具安全

## 1. 本阶段目标

本阶段把“能运行的 Agent”升级为“能定位、能回归、能拒绝危险动作的 Agent”。完成后，你需要能够：

1. 用同一个 `run_id` 关联运行结果、SSE 与结构化观测记录。
2. 从事件数量、耗时、错误分类判断故障发生在哪一层。
3. 用固定样例检查答案、事件序列和工具选择，而不是只比较整段文本。
4. 让工具权限来自可信执行上下文，阻止模型通过参数自行提权。
5. 解释 Mock 测试、真实模型评测和生产监控分别解决什么问题。

建议分三次完成，每次 90～120 分钟：第一次练可观测性与离线评测，第二次练身份、RBAC 与审批，第三次练取消、故障演练和完整回归。

## 2. 当前边界

这是一个教学用、默认离线运行的最小实现：

- 已覆盖运行总耗时、模型/工具分项耗时、事件与错误分类、隐私收敛日志、固定离线评测、RBAC、精确单次审批、协作式取消、截止时间和有限重试。
- Mock 模型的 `usage` 为 `null`，不会把未知 Token/成本伪造成零；真实适配器可写入 `ModelUsage`。
- `StaticTokenAuthenticator` 是服务端静态 Token 教学适配器，不是生产 OIDC/JWT 方案；浏览器端不保存该 Token。
- 匿名会话使用独立的高熵 capability token；明文只在创建响应中出现并保存在页面内存，服务端仅保存 SHA-256 摘要。创建运行、SSE 和读取运行都重新校验该 token。
- 内置课程文档使用服务端保留 ID `agent-course`；即使具有 `knowledge_editor` 角色，也不能通过通用写接口覆盖它。
- 同步工具已经开始执行后，协作式取消不能强杀线程；生产高风险工具还需要可取消 HTTP 客户端、子进程/任务队列隔离与幂等键。
- 暂不接入分布式 Trace、指标数据库和告警平台；Prompt Injection 本阶段验证“不能越过程序权限”，不宣称能识别所有恶意文本。

真实工作中应先保证指标可信，再扩展指标数量。把“未知成本”记录成 `0` 会误导容量和预算判断。

## 3. 20% 关键知识

| 类型 | 知识点 | 工作场景 | 学到什么程度 | 验证任务 |
| --- | --- | --- | --- | --- |
| 必学 | `run_id` 关联 | 排查一次跨 API、Agent、工具的失败 | 能从入口追到终态 | 创建运行后查询观测接口 |
| 必学 | 可信执行上下文 | 用户让模型调用有副作用工具 | 知道身份和审批不能来自工具参数 | 运行参数提权测试 |
| 高频 | 结构化错误分类 | 统计模型、工具、检索故障 | 能按类别聚合，不依赖日志全文搜索 | 构造未知工具失败 |
| 高频 | 固定离线评测集 | Prompt、模型或工具改动后的回归 | 能解释每个断言验证什么 | 让一个用例失败并定位原因 |
| 易错 | 把 Prompt 当权限控制 | Prompt Injection 或模型误判 | 能说明程序边界为何更可靠 | 演示高风险工具无审批被拒绝 |
| 易错 | 默认记录原始输入和异常 | 日志泄露用户内容、密钥或工具参数 | 能做字段白名单 | 运行隐私日志测试 |
| 暂缓 | 全链路平台与成本看板 | 多服务、真实供应商、大规模生产 | 知道接入时机 | 写出需要新增的遥测字段 |

## 4. 代码地图

| 文件 | 责任 | 阅读重点 |
| --- | --- | --- |
| `backend/app/observability/runs.py` | 运行计时、事件/错误汇总、JSON 日志 | `RunObserver`、`RunObservation`、`JsonLogSink` |
| `backend/app/evals/offline.py` | 固定样例执行与断言 | `EvalCase`、`OfflineEvaluator`、`EvalReport` |
| `backend/app/tools/registry.py` | Schema、RBAC、风险与审批 | `_authorize()` 必须早于参数校验和执行 |
| `backend/app/security/identity.py` | 服务端身份解析与角色/审批配置 | 客户端参数不能构造 `Principal` |
| `backend/app/agent/cancellation.py` | 截止时间与协作式取消 | 工具执行前再次检查取消信号 |
| `backend/app/services/run_service.py` | 会话隔离并将观测包装到真实用例入口 | 匿名 capability 只存摘要；业务运行与评测共用 `execute_agent()` |
| `backend/app/main.py` | 暴露观测与默认评测接口 | `/api/observability/runs`、`/api/evals/default` |
| `backend/tests/test_observability.py` | 时间、错误与隐私测试 | 注入时钟，避免依赖真实耗时 |
| `backend/tests/test_offline_evals.py` | 评测通过、失败和 runner 异常 | 失败报告必须可解释 |
| `backend/tests/test_tool_security.py` | 越权、审批和参数提权测试 | 未授权调用不能执行 handler |

运行主线：

```text
HTTP 请求
  -> InMemoryRunService.create_run()
  -> RunObserver.observe(execute_agent)
  -> ManualAgentLoop -> ToolRegistry
  -> RunRecord + RunObservation
  -> API / SSE / JSON 日志
```

## 5. 跟练一：建立可观测运行

### 目标

理解观测代码只包装运行，不改变 Agent 的业务结果；同一次运行的 `RunRecord.id` 与 `RunObservation.run_id` 必须一致。

### 执行动作

在项目根目录运行观测测试：

```powershell
.\.venv\Scripts\python.exe -m unittest backend.tests.test_observability -v
```

先在本机终端配置一个只用于学习的服务端 Token，再从同一终端启动 API：

```powershell
$authConfig = @{
  'local-learning-token' = @{
    principal_id = 'learner-1'
    roles = @('observer', 'knowledge_editor', 'editor')
    approvals = @(
      @{
        tool_call_id = 'api-publish-call'
        tool_name = 'publish_report'
        arguments = @{ report_id = 'report-7' }
      }
    )
  }
}
$env:AI_AGENT_DEMO_AUTH_JSON = $authConfig | ConvertTo-Json -Depth 8 -Compress
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

这里的审批只匹配 `learner-1 + api-publish-call + publish_report + report-7`，成功后立即消费。不要把这个 Token 写入源码、Vite 环境变量或提交记录。

如果不提供 Bearer 身份，`POST /api/sessions` 会在 `access_token` 中返回该匿名会话的临时 capability。后续创建运行、SSE 与读取运行必须发送 `X-Session-Token`；另一个匿名会话的 token 即使配合同一个 session ID 也只会得到 404。前端只把它保存在组合式函数内存，不写入 `localStorage`。

```powershell
$anonymous = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/sessions
$anonymousHeaders = @{ 'X-Session-Token' = $anonymous.access_token }
$anonymousBody = @{ message = '20 加 22' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Headers $anonymousHeaders -ContentType 'application/json' `
  -Body $anonymousBody -Uri "http://127.0.0.1:8000/api/sessions/$($anonymous.id)/runs"
```

在另一个 PowerShell 终端创建会话和运行：

```powershell
$headers = @{ Authorization = 'Bearer local-learning-token' }
$session = Invoke-RestMethod -Method Post -Headers $headers -Uri http://127.0.0.1:8000/api/sessions
$body = @{ message = '20 加 22' } | ConvertTo-Json
$run = Invoke-RestMethod -Method Post -Headers $headers -ContentType 'application/json' -Body $body `
  -Uri "http://127.0.0.1:8000/api/sessions/$($session.id)/runs"
$observations = Invoke-RestMethod -Headers $headers http://127.0.0.1:8000/api/observability/runs
$run
$observations
```

### 观察结果

- `run.id` 与最后一条观测记录的 `run_id` 相同。
- 数字问题会产生 `tool.started`、`tool.completed` 和 `run.completed`。
- `model_duration_ms` 与 `tool_durations_ms` 分开记录；Mock 的 `usage` 明确为 `null`。
- 日志包含状态、总耗时、事件计数和错误类别，不包含问题正文、回答正文和原始异常文本。

### 工作映射

线上出现“用户没得到答案”时，先按 `run_id` 判断请求是否进入系统、是否调用工具、在哪个终态结束，再决定查模型、工具还是传输层。不要先盲目修改 Prompt。

### 通关标准

你能指出 `RunObserver.start()`、`complete()`、`fail()` 分别应放在何处，并解释为什么测试注入 `ScriptedClock`。

## 6. 跟练二：运行固定离线评测

### 目标

理解单元测试验证代码边界，离线评测验证 Agent 行为。评测不要求答案逐字相同，而是检查任务所需证据。

### 执行动作

```powershell
.\.venv\Scripts\python.exe -m unittest backend.tests.test_offline_evals -v
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/evals/default | ConvertTo-Json -Depth 8
```

默认评测包含三个用例，每次执行生成不同的 `batch_id`：

| 用例 | 检查内容 | 为什么不只检查答案 |
| --- | --- | --- |
| `direct-answer` | 状态、答案片段、完成事件 | 确认无需工具的路径正常 |
| `tool-selection` | 答案片段、工具名、工具完成事件 | 防止模型碰巧答对但没走规定工具 |
| `approval-denied` | 高风险工具被选择、失败事件、`approval_required` | 防止评测只看 HTTP 200 或工具名称 |

### 故障练习

临时把 `main.py` 中 `tool-selection` 的 `answer_contains=("42",)` 改为 `("43",)`，重新调用评测接口，观察：

- `pass_rate` 从 `1.0` 下降。
- 失败项的 `check` 为 `answer_contains`。
- `expected` 与 `actual` 足以定位失败。

练习结束后恢复为 `42` 并重新运行完整测试。

### 通关标准

你能新增一个不联网的 `EvalCase`，同时验证状态、必需事件和必需工具；用例失败时报告能说明失败原因。

## 7. 跟练三：RBAC 与高风险审批

### 目标

掌握三条安全边界：

1. 角色与审批来自服务端构造的 `ToolExecutionContext`。
2. 模型生成的 `arguments` 只能作为业务参数。
3. 审批绑定主体、调用 ID、工具名和参数摘要，并且只能消费一次。
4. 高风险或有副作用的工具即使配置疏忽，也必须审批。

### 执行动作

```powershell
.\.venv\Scripts\python.exe -m unittest backend.tests.test_tool_security -v
```

重点阅读以下四个测试：

- `test_role_restriction_returns_structured_denial_without_execution`
- `test_high_risk_tool_requires_explicit_approval`
- `test_side_effect_cannot_disable_mandatory_approval`
- `test_declared_security_named_arguments_cannot_elevate_context`
- `test_approval_is_bound_to_arguments_and_consumed_once`
- `test_prompt_injection_cannot_bypass_programmatic_tool_policy`

授权顺序是：

```text
工具是否存在 -> 角色授权 -> 审批授权 -> Schema 校验 -> handler 执行
```

把授权放在 Schema 校验之前，可以避免未授权调用者通过不同校验错误探测受限工具的参数结构。

### API 演练

内置 `publish_report` 已配置为 `editor` 角色、高风险且有副作用。使用上一节的会话依次执行：

```powershell
$deniedBody = @{ message = '发布报告 report-8' } | ConvertTo-Json
$approvedBody = @{ message = '发布报告 report-7' } | ConvertTo-Json
$uri = "http://127.0.0.1:8000/api/sessions/$($session.id)/runs"

Invoke-RestMethod -Method Post -Headers $headers -ContentType 'application/json' -Body $deniedBody -Uri $uri
Invoke-RestMethod -Method Post -Headers $headers -ContentType 'application/json' -Body $approvedBody -Uri $uri
Invoke-RestMethod -Method Post -Headers $headers -ContentType 'application/json' -Body $approvedBody -Uri $uri
Invoke-RestMethod -Headers $headers http://127.0.0.1:8000/api/observability/runs | ConvertTo-Json -Depth 8
```

预期：`report-8` 因参数不匹配被拒绝，`report-7` 第一次成功，第二次因审批已消费被拒绝。

### 必做练习

复制该模式新增 `archive_report`，并补 viewer 拒绝、参数 A/B 不匹配、过期审批和重放测试。Schema 使用未支持关键字时必须在注册阶段失败，不能静默忽略约束。

### 通关标准

你能解释为什么工具级 `approved=True` 不安全，并能证明审批只对精确调用生效、拒绝或重放时 handler 一次也没有执行。

## 8. 跟练四：把失败定位到正确层

依次运行三个故障场景并填写记录：

| 场景 | 预期错误层 | 主要证据 | 不应该先做什么 |
| --- | --- | --- | --- |
| 调用不存在的工具 | 工具注册/选择 | `unknown_tool`、`tool.failed` | 调整数据库或前端样式 |
| runner 抛出异常 | 运行器 | `exception.<类型>`、状态 `failed` | 把异常静默吞掉 |
| 评测答案不符合预期 | 行为回归 | `answer_contains` 失败项 | 只看 HTTP 200 |

每个场景记录：`run_id`、终态、错误类别、最小复现命令、根因、修复后测试证据。

## 9. 自动化验证

完整后端回归：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

前后端与 MCP 构建：

```powershell
cd frontend
npm.cmd run build
cd ..\mcp-servers\knowledge-server
npm.cmd run build
```

通过标准：

- 所有测试通过，默认过程不访问真实模型网络。
- 默认评测 `pass_rate` 为 `1.0`。
- 越权与缺少审批均返回结构化拒绝，handler 未执行。
- 截止时间只接受 100～120000 ms；取消发生在工具开始前时，不执行副作用 handler。
- 只有 `RetryableModelError` 会在固定次数内重试，普通程序错误不会盲目重放。
- 日志中搜索不到测试使用的私密输入。

## 10. 常见错误与排查

| 现象 | 常见原因 | 排查顺序 |
| --- | --- | --- |
| 有运行结果但无观测记录 | 绕过了 `InMemoryRunService.create_run()` | 检查入口是否经过 observer，再查 sink |
| 评测偶发失败 | 依赖真实网络、真实时间或非固定模型 | 先替换为 Mock 和注入时钟，再检查断言 |
| 高风险工具直接执行 | 风险元数据缺失或授权不在注册表边界 | 检查 `approval_required` 与 `_authorize()` |
| 参数能改变角色 | 把模型参数与可信上下文合并 | 分离 `arguments` 与 `ToolExecutionContext` |
| 同一审批可换参数或重放 | 只按工具名审批 | 绑定调用 ID、参数摘要并原子消费 |
| 匿名 session ID 可被别人使用 | 所有匿名请求共用同一主体 | 每会话独立 capability，三个运行入口都校验摘要 |
| 点击“停止”后工具仍完成 | 同步 handler 已进入执行 | 在执行前检查取消；生产中改用可取消 I/O 或隔离任务 |
| 日志出现用户原文 | 直接序列化消息、工具参数或异常文本 | 改用字段白名单，只记录错误类别 |
| HTTP 200 但行为错误 | 只做接口测试，没有行为评测 | 检查工具选择、事件与业务断言 |

## 11. 一页速查

```text
观测：发生了什么？       run_id + 模型/工具耗时 + usage + 事件 + 错误分类
测试：代码边界对不对？   确定性输入、确定性断言、无隐藏网络
评测：Agent 行为好不好？ 答案依据 + 工具选择 + 事件 + 阈值
授权：这个主体能不能做？ 服务端身份 + 角色策略
审批：这一次是否允许做？ 主体 + call id + 工具 + 参数摘要 + 单次消费

安全顺序：存在 -> 授权 -> 审批 -> 校验 -> 执行
排错顺序：输入 -> 模型决策 -> 工具 -> 状态/事件 -> API/SSE -> UI
```

## 12. 自测题

### 概念题

1. 为什么生产日志不能直接保存完整 Prompt 和工具参数？
2. 单元测试、离线评测、生产观测各自回答什么问题？
3. 为什么工具审批不能由模型生成一个 `approved=true` 参数？
4. Mock 模式没有 Token 数据时，为什么不能记录为零？
5. 为什么 UUID session ID 不能代替匿名会话 capability token？

### 实操题

1. 新增一个失败评测用例，并从报告定位具体断言。
2. 为高风险工具补角色、审批、Schema 和 handler 未执行测试。
3. 构造包含敏感文本的异常，证明默认 JSON 日志不会输出原文。

### 工作场景题

一个客服 Agent 被检索文档中的恶意文字诱导，准备调用“退款”工具。请说明 Prompt、防注入标记、RBAC、审批、幂等和审计分别在哪一层生效，哪些层不能互相替代。

## 13. 费曼复述

请用“公司门禁”的类比，在三分钟内解释：

1. `run_id` 为什么像访客单号。
2. RBAC 为什么像员工权限，而审批为什么像本次临时放行。
3. 评测为什么像消防演练，而日志为什么像门禁记录。
4. 为什么访客自己写一张“我是管理员”的纸条不能获得权限。

复述必须包含一个失败案例和一个“不应该记录的敏感字段”。

## 14. 阶段验收清单

- [ ] 能创建一次运行并用相同 `run_id` 查到观测摘要。
- [ ] 能解释总耗时、事件计数和错误分类的含义与局限。
- [ ] 能区分模型耗时、工具耗时和 `usage=null`，不把未知成本当零。
- [ ] 能运行默认离线评测并解释每个检查项。
- [ ] 能让一个评测稳定失败，再恢复并通过。
- [ ] 能演示角色拒绝、审批拒绝和审批后执行。
- [ ] 能证明参数无法提升角色或伪造审批。
- [ ] 能证明更换参数和重放都无法复用一次审批。
- [ ] 能演示截止时间校验、有限重试和工具执行前取消。
- [ ] 能证明匿名会话缺少、换用或伪造 capability token 时无法创建、流式执行或读取运行。
- [ ] 能证明恶意文本无法绕过程序化工具权限。
- [ ] 能证明默认 JSON 日志不含 Prompt、回答或原始异常文本。
- [ ] 能运行完整后端回归并保留测试证据。
- [ ] 能说清静态 Token、协作式取消、真实 Token/成本和分布式 Trace 的生产化缺口。

完成以上内容后，继续 [Docker 构建与最小部署](05-docker-deployment.md)。
