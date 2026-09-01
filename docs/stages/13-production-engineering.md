# M13：生产工程、观测、测试与部署

> 工程动态状态只查看[连续性状态页](../continuity/status.md)。本章把 M13-T1 至 M13-T6 的
> 已验证能力整理为可重复跟练和验收路径；命令出现在教程中不等于本次已经执行。

## 本阶段目标

把“功能能跑”升级为“未知故障可定位、错误可安全处理、发布门禁不说谎、单实例可部署且恢复
有证据”。

- 时间预算：7 次跟练，约 22–34 小时。
- 任务：M13-T1 至 M13-T7。
- 适合对象：熟悉 Vue/HTTP，但没有 AI 生产工程经验的前端开发者。
- 工作映射：AI Copilot 上线、异步任务排障、CI 门禁、容器发布、代码执行平台和故障值班。

最终通关不是背出术语，而是拿到一次未知失败后，能从 Run ID 开始，用 Trace 缩小链路、用
日志确认离散事实、用指标判断影响范围，选择不会扩大副作用的恢复动作，并验证服务和历史数据
都已恢复。

M13 的最高证据是当前项目的单机生产基线，不包括 TLS、备份恢复、高可用、多实例、长时间
soak、公网流量、在线 Provider 容量、逐调用硬成本门或底层线程/远端请求硬取消。

## 从前端视角理解生产闭环

```text
Vue 报错或用户投诉
  -> HTTP status + Run ID
  -> Run snapshot / observability
       -> Trace：哪一层、哪一步失败
       -> Log：该次离散事实与稳定错误码
       -> Metric：多少 Run 受影响、是否持续恶化
  -> retry / fail closed / 人工处理
  -> 分层验证 -> 部署恢复 -> 新旧 Run 复核 -> 复盘
```

可以把它类比成前端线上排障：Trace 像一次请求在浏览器、网关、接口和数据库之间的调用链；
日志像某次请求的 Console/服务端事件；指标像错误率、P95 和内存曲线。三者互补，任何一个都
不能单独证明答案正确、费用真实或服务已经恢复。

## 20% 关键知识

| 类型 | 知识点 | 工作场景 | 学到什么程度 | 验证任务 |
| --- | --- | --- | --- | --- |
| 必学 | Run ID 串联 log/metric/trace | 用户只给一个失败任务 | 能定位失败层、步骤、错误和影响 | M13-T1 |
| 必学 | 稳定错误与六道重试门 | Provider、MCP、工具超时 | 能说明为何“可重试”仍可能禁止重试 | M13-T2 |
| 必学 | 分层验证和真实 skip | PR、合并、发布 | 能区分 passed、failed、skipped | M13-T3 |
| 必学 | migration、readiness、liveness | 容器发布 | 能从干净环境启动并验证依赖 | M13-T4 |
| 高频 | 结果未知与持久幂等键 | 创建 Run、提交订单类工具 | 不把超时误判成未执行 | M13-T2、T6 |
| 高频 | usage/cost 的 unknown 语义 | 预算看板 | 不把未知写成 0，不把估算写成账单 | M13-T1 |
| 高频 | 固定工作点与证据边界 | 容量评审 | 会报告参数、波动和未验证范围 | M13-T6 |
| 易错 | exporter 失败拖垮业务 | 遥测平台故障 | sink 降级不改写 Run | M13-T1 |
| 易错 | 截断输出等于内存有界 | 代码 Agent | 持续排空、硬上限、整树清理 | M13-T5 |
| 暂缓 | HA、生产认证、硬成本门 | 多实例生产系统 | 能指出缺口，不在 M13 伪装完成 | M14 或独立任务 |

## 五级能力阶梯

| 级别 | 能力 | 可观察产出 | 不通过表现 |
| --- | --- | --- | --- |
| L1 识别 | 区分日志、指标、Trace、稳定错误 | 给 5 个问题选择正确信号 | 把 Trace 当业务答案或把 unknown 当 0 |
| L2 定位 | 从 Run ID 找到最细失败层 | 一张故障链和第一证据 | 一上来重启或只看前端报错 |
| L3 决策 | 通过六道门决定重试/拒绝/人工处理 | 一份 retry 决策表 | 对副作用或结果未知自动重试 |
| L4 恢复 | 选择验证层并完成安全恢复闭环 | 新 Run、旧 Run、健康和清理证据 | 只看容器 running 就宣布恢复 |
| L5 评审 | 解释容量、CI、部署和未验证边界 | 事故复盘与发布建议 | 把本地短样本外推成 SLA |

## 跟练前规则

1. 每次先写预测：预期错误码、是否重试、需要哪种证据。
2. 先运行最小定向命令，再按任务需要进入完整 profile；失败结果不能从记录中删除。
3. Docker、在线 Provider、密钥、远程 Git 和依赖变更仍需当次明确授权。
4. 所有 PowerShell 示例从仓库根目录运行，并使用正斜杠路径。
5. 个人答案和勾选只写 `../progress.md`；工程状态和实际命令结果写连续性文档。

## 第 1 次：从 Run ID 定位失败

- 时间预算：3–4 小时。
- 新概念：log、metric、trace 的职责分工。
- 代码入口：`backend/app/observability/durable.py`、`backend/app/main.py`、
  `backend/tests/test_durable_observability.py`。
- 材料：[durable Run 可观测性合同](../m13-observability.md)和
  [一页观测速查表](../m13-observability-cheat-sheet.md)。
- 动作：为成功、模型重试、工具拒绝、RAG 失败各画一次 `run -> node/model/tool` 链；检查
  `error_code`、`attempt`、duration 和 usage/cost 的未知值。
- 命令：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_durable_observability -v
```

- 产出：一张“三种信号各回答什么”的表，以及一次从 run span 下钻到最细失败 span 的记录。
- 工作映射：前端拿到请求 ID 后联查网关、接口、数据库和监控。
- 通关：能说明 Trace 定位控制流，citation 才是回答依据；sink 失败为什么不能改写已完成 Run。
- 常见错误：记录 prompt/工具参数；把 Run 总耗时冒充模型耗时；把费用 unknown 显示成 0。

## 第 2 次：决定是否重试

- 时间预算：3–4 小时。
- 新概念：`retryable` 是错误分类，不是执行许可。
- 代码入口：`backend/app/reliability.py`、各 Runtime、`ToolRegistry` 和 MCP adapter。
- 材料：[稳定错误、重试、超时与取消](../m13-reliability.md)。
- 动作：分别处理 Provider 429、Provider 401、只读 MCP timeout、副作用工具 timeout、Store
  result-unknown 和用户取消；逐项走完六道门。
- 命令：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_reliability backend.tests.test_mcp_tool_adapter -v
```

- 产出：一张包含稳定错误码、次数、deadline、side effect、幂等键和结果未知的决策表。
- 工作映射：GET 查询重试、表单重复提交、支付结果未知和用户主动取消。
- 通关：能解释人工审批不等于持久幂等；为什么 Store mutation 和整个 Runtime 不套通用重试。
- 常见错误：HTTP timeout 就换新 key；认证失败退避重试；取消获胜后仍开始下一次调用。

## 第 3 次：设计不会说谎的质量门

- 时间预算：2–3 小时。
- 新概念：测试层与证据等级。
- 材料：[分层验证与 CI](../m13-verification-ci.md)和
  `scripts/verify.ps1`。
- 动作：为 PR、合并、发布列出 profile；模拟 required 前置条件缺失和 online 未授权，比较
  `FAILED` 与 `SKIPPED`。
- 命令：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_verification_entrypoint -v
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify.ps1 -Profile mcp
```

- 产出：offline、MCP、PostgreSQL、frontend、E2E、Docker、online 七层门禁矩阵。
- 工作映射：前端 unit/build/E2E 分层、CI required check 和发布审批。
- 通关：能说明“online 被明确跳过的默认 CI 全绿”不等于线上模型通过；required layer 缺工具
  为什么必须失败。
- 常见错误：把没选中的层算通过；首层失败后仍打印“全部通过”；让普通 CI 自动使用密钥。

## 第 4 次：验证单实例部署

- 时间预算：3–5 小时。
- 新概念：liveness、readiness、migration/seed 和反向代理共同构成部署证据。
- 材料：[Docker、pgvector 与 Nginx 实际部署](../m13-deployment.md)、
  `deploy/compose.deployment.yaml` 和 `scripts/verify-deployment.ps1`。
- 动作：先画启动依赖图；再在获得当次 Docker 授权后，让唯一 Compose project 完成 build、
  health、migration、seed、数据库测试、Nginx SSE、backend restart 和精确清理。
- 命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify.ps1 -Profile docker
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify-deployment.ps1
```

- 产出：一份“配置可展开/镜像可构建/服务 ready/纵切可用/重启可恢复”的证据分级表。
- 工作映射：Vue 静态资源 + Nginx + API + PostgreSQL 的单机交付。
- 通关：知道 Compose config 通过和容器 running 都不是服务可用；secret 路径不进入仓库和日志。
- 常见错误：隐式 seed；只检查 liveness；全局 `docker compose down`；把本机 HTTP 写成生产部署。

## 第 5 次：约束代码 Agent 进程

- 时间预算：3–4 小时。
- 新概念：输出有界、资源有界和进程树生命周期是三件事。
- 代码入口：`backend/app/advanced/process_runner.py`、
  `backend/app/advanced/code_agent.py`。
- 动作：分析无限 stdout/stderr、timeout、取消、嵌套子进程、CPU/内存/进程数超限和路径逃逸；
  说明 Windows Job 与 Linux process group 的职责。
- 命令：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_code_agent_process backend.tests.test_code_agent -v
```

- 产出：一张“拒绝执行/开始执行/终止整树/安全审计”的状态表。
- 工作映射：在线 IDE、构建任务、文件转换和插件执行平台。
- 通关：能解释“先读完整 PIPE 再截断”仍可能耗尽内存；内容不能进入默认审计。
- 常见错误：只 kill 父进程；把 10ms 采样描述为 OS 强隔离；允许客户端选择 executable。

## 第 6 次：解释固定负载与故障证据

- 时间预算：3–5 小时。
- 新概念：工作点不是容量上限，故障恢复必须区分结果未知和明确终态。
- 材料：[基础压测与故障演练](../m13-load-fault.md)、
  `backend/app/evals/load_fault.py` 和 `scripts/verify-load-fault.ps1`。
- 动作：先运行离线评测合同；获得当次 Docker 授权后，再执行并发 Run、慢 SSE、Fake 限流、
  PostgreSQL stop/start 和 backend restart。
- 命令：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_load_fault_eval backend.tests.test_load_fault_script -v
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify-load-fault.ps1
```

- 产出：固定参数、三轮延迟/吞吐/错误率、资源快照、波动解释和未验证范围。
- 工作映射：上线前基线、故障演练、容量沟通和事故恢复。
- 通关：能说明响应未知时为何复用同一幂等键；只有明确 `failed/cancelled` 后才能用新 key。
- 常见错误：单轮 P95 当 SLA；点式 RSS 当峰值；Fake 429 当真实 Provider 限流证据。

## 第 7 次：未知故障综合演练与里程碑验收

- 时间预算：5–7 小时。
- 材料：[M13 故障响应手册](../m13-incident-handbook.md)、本章题库和速查表。
- 情景：用户只提供“Agent 一直失败”和一个 Run ID；故障类型预先未知。
- 动作：
  1. 记录症状、时间、HTTP status、Run ID 和影响范围，不先猜根因。
  2. 用 snapshot/observability 找到最细失败层和稳定错误。
  3. 用指标判断单 Run 还是系统性故障，用安全日志确认离散事实。
  4. 通过六道门决定重试、fail closed 或人工恢复。
  5. 选择最小 verification profile；需要部署恢复时验证 migration、readiness 和代理链。
  6. 同时证明新 Run 成功、故障前已完成 Run 可读、没有静默内存回退、临时资源已清理。
  7. 写下仍未验证的生产边界，再完成概念、实操和场景题。
- 里程碑命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/check-continuity.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/verify.ps1
```

- 通关：不看答案也能按固定顺序完成定位、决策、恢复和证据记录；总分至少 80，且不触发红线。

## 生产故障最小算法

```text
保护现场 -> 确认 owner/Run -> 看 run span -> 下钻最细失败层
  -> 读取稳定错误 -> 看影响指标 -> 判断结果是否未知
  -> 过六道重试门 -> 执行最小恢复 -> 跑匹配验证层
  -> 新 Run + 旧 Run + 资源清理 -> 记录未验证范围
```

完整故障卡、证据模板和恢复检查见 [M13 故障响应手册](../m13-incident-handbook.md)。

## 证据等级与边界

| 证据 | 最高等级 | 能证明 | 不能证明 |
| --- | --- | --- | --- |
| 静态配置、单元测试 | E1/E2 | 契约、错误和失败分支 | 真进程、真数据库、真浏览器 |
| 本地真实进程/浏览器/数据库 | E3 | 当次协议和进程边界 | 公网、跨主机、Provider 行为 |
| Docker 单机纵切 | E3/C | 镜像、健康、migration、Nginx、重启 | TLS、HA、备份、生产容量 |
| GitHub-hosted 七层 CI | E3/C | 干净 runner 的分层门禁 | 生产部署和线上模型 |
| 授权在线 Provider | E4 | 当次模型/Embedding 请求结果 | 长期可用性、质量、账单或 SLA |

M13-T6 的三轮 `16 Runs / concurrency 4`、0% 错误只是在一台 Windows Docker Desktop、
Mock Runtime、单 backend 和本地 PostgreSQL 上的可重复工作点。最保守一轮约 6.6 Run/s、
P95 约 1.55s；不能外推为生产容量。

## 自测题库

### 概念题（6 题，共 24 分）

1. log、metric、trace 分别回答什么问题？为什么还需要 Run snapshot 和 citation？
2. `retryable=true` 后还要通过哪六道门？
3. 结果未知和明确 `failed/cancelled` 对幂等键选择有什么不同？
4. required profile 缺少前置条件与 online 未授权分别应是 `FAILED` 还是 `SKIPPED`？
5. liveness、readiness、migration/seed 和业务纵切分别证明什么？
6. 为什么输出被截断仍不等于内存、CPU 和进程树有界？

评分：每题 4 分；定义或流程 2 分，边界或反例 2 分。

### 实操题（4 题，共 40 分）

1. 从一个预置失败 Run 的 observability 响应中写出失败层、步骤、稳定错误码、重试次数、
   usage/cost 状态和下一证据。
2. 为 429、401、只读 MCP timeout、副作用工具 timeout 和 Store result-unknown 完成重试决策表。
3. 设计 PR、main、release 三组验证门；必须显示七层状态，且 online 不读取 CI secret。
4. 执行一次受控故障恢复，提交新 Run、旧 completed Run、health/readiness、EventStore 终态和
   精确资源清理五类证据。

评分：每题 10 分；可复现证据 4 分，决策链 3 分，安全与边界 3 分。

### 工作场景题（3 题，共 36 分）

1. 客服说“同一个创建请求超时后出现两个任务”。给出止损、幂等仲裁、Trace/日志/指标检查、
   恢复和长期修复建议。
2. 部署页面显示容器 running，但用户收不到实时输出。按 Nginx、readiness、SSE、EventStore、
   snapshot 的顺序定位，并说明何时可以回滚。
3. 代码 Agent 执行第三方项目时无限输出，取消后仍有孙进程。设计应用级修复和更强隔离边界，
   说明哪些结论不能只靠本项目测试证明。

评分：每题 12 分；止损/定位 4 分，安全恢复 4 分，权衡和未验证范围 4 分。

总分至少 80 分通关。出现任一红线即不通过：记录 Key/prompt/完整参数或 raw exception；把
unknown cost 写成 0；自动重试副作用或结果未知 mutation；把 skipped 写成 passed；只看容器
running 就宣布恢复；用全局 Docker 清理；把本地短样本写成生产 SLA；把 Fake 限流写成在线
Provider 证据。

## 一页速查表

工作排障时打开 [M13 一页观测速查表](../m13-observability-cheat-sheet.md)。先凭记忆写出三种
信号、六道重试门和恢复五证，再用速查表纠正。

## 费曼复述任务

不查资料，向一名只做 Vue CRUD 的同事讲 8 分钟：

1. 用“医院病例、生命体征、检查链”解释日志、指标和 Trace。
2. 用户给一个 Run ID 后，为什么先看 run span，再下钻 node/model/tool？
3. 用“表单重复提交”解释结果未知、持久幂等键和副作用禁重试。
4. 为什么 CI 的 skip 不能伪装 pass，在线未授权为何又允许明确 skip？
5. 为什么容器 running、health 200、migration 完成和真实 SSE 是不同证据？
6. 为什么代码输出截断、父进程退出和真正的整树清理不是一回事？
7. 为什么三轮 16/4 无错误仍不是生产 SLA？
8. 任选一次故障，说出止损、定位、恢复、验证和未验证范围。

复述合格标准：不用术语堆砌，至少有两个前端业务类比；能画故障闭环；能说出一个禁止重试
场景、一个敏感信息边界、一个证据降级和三个 M13 未验证范围。把 Trace 当答案证据、审批当
幂等键、skip 当 pass 或工作点当 SLA 时必须重述。

## 与 30 项大纲映射

完整目标见 [30 个主题映射](../syllabus-map.md)。M13 直接验收 13、23、24、25、26、27，并为
17、19、20、22、30 提供生产闭环证据：

| 编号 | 主题 | M13 产物 | 证据边界 |
| --- | --- | --- | --- |
| 13 | Agent Harness | timeout、取消、资源与进程树预算 | 应用级 Harness，不是 VM/cgroup |
| 17 | 记忆系统 | PostgreSQL 故障和 restart 后历史读取 | 不证明跨 Store 共同事务 |
| 19 | Agent UI | Nginx SSE 与故障中的 snapshot 恢复 | 未验证公网和多实例通知 |
| 20 | 后端 API | owner-scoped observability、health/readiness | 单实例，不是生产认证 |
| 22 | 流式输出 | 慢客户端和 Nginx buffering 验证 | 单客户端短暂停，不是公网长连接 |
| 23 | 可观测性 | EventStore Trace/Metrics、usage ledger | 无 vendor exporter 和逐调用成本 |
| 24 | 自动化测试 | 七层 profile 与 GitHub Actions | online-policy skip 不是 E4 |
| 25 | 工程化部署 | secret、migration、seed、health、Nginx、故障演练 | 无 TLS、备份、HA |
| 26 | 安全治理 | 稳定错误、重试门、脱敏和副作用边界 | 同步线程/远端请求无硬撤销 |
| 27 | 代码 Agent | 有界排空、资源预算、整树清理 | 不执行任意恶意代码隔离证明 |
| 30 | 系统设计 | 事故手册、容量边界和恢复证据 | 最终作品集答辩仍由 M14 完成 |

## 最终验收清单

- [ ] 能用一句话区分 log、metric、trace、snapshot 和 citation。
- [ ] 能从 Run ID 定位最细失败层、稳定错误码、attempt 和可信 duration。
- [ ] 能走完六道重试门，并拒绝副作用和结果未知的危险重放。
- [ ] 能设计七层门禁，正确报告 passed、failed 和 skipped。
- [ ] 能证明 migration、readiness、Nginx SSE 和 restart recovery，而不只看容器 running。
- [ ] 能解释有界输出、资源预算、整树清理和 OS 强隔离的差异。
- [ ] 能报告固定负载参数、波动、错误率、资源采样和未验证范围。
- [ ] 能按故障手册完成止损、定位、恢复、新旧 Run 验证和资源清理。
- [ ] 概念、实操、场景题至少 80 分，且没有触发红线。
- [ ] 能完成费曼复述，并把个人答卷和复盘只记录到 `docs/progress.md`。
