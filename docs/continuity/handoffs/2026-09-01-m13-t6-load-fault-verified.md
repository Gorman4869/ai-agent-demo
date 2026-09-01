# M13-T6 交接：基础压测与故障演练验证通过

- 日期：2026-09-01，Asia/Shanghai
- 完成任务：`M13-T6 / verified`
- 验证基线：`b87ecda741e1ec12aa23f6216f452936398f1435`
- 验证记录：`V-20260901-001`
- 关联决策：`ADR-0039`
- 在线模型/付费调用：未执行，费用 0

## 本轮结果

新增标准库负载/故障测量核心和 CLI，离线覆盖并发内存 Run、慢 SSE 客户端和确定性模型限流；
localhost 部署覆盖 Nginx/FastAPI/PostgreSQL durable HTTP 并发。部署 verifier 新增唯一 project 内的
PostgreSQL stop/start、恢复 Run、backend restart 和四阶段 `docker stats` 点快照。

相同负载/故障逻辑连续三次通过：16 Runs、并发度 4 均为 0% 错误；部署吞吐为 17.333/s、
11.557/s、6.639/s，p95 为 498.490ms、708.766ms、1,542.506ms。数据库停机均返回 5xx；恢复
窗口分别出现 3、2、3 个明确终态失败 Run，随后新 Run 成功，backend restart 后旧 completed
Run 仍可读。三个随机 project 的容器、网络和卷全部清理；最后一轮还确认 skip 标签没有冒充
本轮数据库回归通过。

## 修改文件

- 测量/CLI：`backend/app/evals/load_fault.py`、`backend/app/load_fault_probe.py`、eval 导出。
- 脚本：`scripts/verify-load-fault.ps1`、`scripts/verify-deployment.ps1`。
- 测试：`backend/tests/test_load_fault_eval.py`、`backend/tests/test_load_fault_script.py`。
- 决策/说明/规约：`ADR-0039`、`docs/m13-load-fault.md`、`BACKEND_CODING_STANDARDS.md`。
- 连续性：实施计划、verification、known issues、status 和本 handoff。
- 未修改 `docs/progress.md`，学习者个人进度保持不变。

## 验证摘要

| 范围 | 结果 |
| --- | --- |
| 相关自动化回归 | 77 项最终通过；一次既有 10ms 调度边界失败，单项和整组复跑通过 |
| Python / PowerShell 静态检查 | 4 个 Python 文件 AST 通过；两个脚本 Parser 通过；diff check 无错误 |
| 第一次最终 Docker 演练 | project `ai-agent-demo-m13-load-27004-965dc5b6`，完整退出 0 并清理 |
| 用户要求的独立复跑 | project `ai-agent-demo-m13-load-24680-5bfa353e`，完整退出 0 并清理 |
| 最终标签修正后复跑 | project `ai-agent-demo-m13-load-9868-044f0484`，完整退出 0 并清理 |
| Provider/Secret | 未读用户 `.env`/Key，未调用在线模型；临时 DB secret 只在 verifier 生命周期使用 |

## 保留的失败与修复

1. 预检在 verifier secret 生命周期外调用 Compose，缺少 DSN file；把负载故障入口收进原 verifier。
2. 重复执行 M13-T4 数据库全回归命中既有 `pool-255` 非确定性 timeout；只允许 LoadFault 显式
   跳过该重复层，其他部署验证保持。
3. 空 stderr 调用 `Trim()`、安全报告解析顺序和 `Start-Process.ExitCode` 分别导致误判；改为安全
   读取、先解析报告和同步 `$LASTEXITCODE`。
4. Windows curl JSON quoting 使 outage 请求在数据库前返回 422；改用 `Invoke-RestMethod`，只接受
   无响应或 5xx。
5. 恢复初期已提交 Run 的重放不再下发 capability；verifier 允许 null，但拒绝不匹配值。
6. 重放 Run 已明确 failed 时继续同键无法恢复；最终合同只在明确终态后换键，最多 8 次并记录
   次数。最终三轮分别记录 3、2、3 次后恢复。

## 未验证与保留边界

- 16/4 是本机三次短样本的工作点，不是生产最大容量或 SLA；吞吐/p95 波动显著。
- `docker stats --no-stream` 是点快照；Probe RSS 是 Windows 客户端进程，不是服务端峰值。
- 限流由 Fake Model 确定性注入；没有线上 Provider、Token、usage、费用或 transport 取消证据。
- `KI-015` 仍缺多进程终态竞争/跨域一致性；`KI-016` 仍缺进行中 durable Run 的 backend
  hard-kill；`KI-018` 的逐调用 usage、版本化价格与硬成本门仍未关闭。

## 下一条原子动作

恢复 M13-T7，只做 M13 跟练与验收交付：读取 playbook、现有阶段文档结构和 M13-T1–T6 证据，
再编写 `docs/stages/13-production-engineering.md`、故障手册、观测速查、考核和费曼任务。未经新授权
不运行在线 Provider、不读取 Key/用户 `.env`、不 push。

## 交接时工作区

本 handoff 创建时 M13-T6 实现与连续性文件尚未提交；`main` 基线为 `b87ecda`，相对
`origin/main` ahead 5。结束前只提交 M13-T6 文件，不 push；实现提交由下一条 verification/status
锚点记录。
