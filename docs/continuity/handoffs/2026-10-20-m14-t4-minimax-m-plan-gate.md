# M14-T4 MiniMax M Plan 用量门交接

## 当前结论

- 当前任务：`M14-T4 / code_complete`；验证记录：`V-20261020-001/002/003/004`。
- 验证基线：`5accb4b`；M Plan 门实现提交：`c53c658`；此前 MiniMax adapter 实现提交：`4fae4a3`。
- 用户确认环境中的 MiniMax Key 属于 M Plan，但尚未授权真实调用。
- M Plan 离线门已完成：记录 Token usage，不估算现金成本，不查询套餐余量，不增加网络请求。
- MiniMax 专项 21 项、扩大相关回归 119 项通过；没有读取 Key、访问 Provider、发送图片或 push。

## 修改文件

| 文件 | 修改 |
| --- | --- |
| `backend/app/minimax_vision_smoke.py` | 增加显式 `payg/m_plan`、M Plan 无现金摘要与冲突配置拒绝 |
| `backend/tests/test_minimax_vision_smoke.py` | 增加 M Plan settings/CLI/summary/PowerShell 回归 |
| `scripts/verify-online.ps1` | MiniMax 路径要求显式 `Payg` 或 `MPlan` |
| `docs/m14-minimax-vision-smoke.md` | 记录 M Plan 官方口径、唯一命令和未查询余量边界 |
| `docs/implementation-plan.md`、连续性文档 | 更新 `V-20261020-004`、`KI-033`、状态与恢复入口 |

## 冻结的 M Plan 合同

- PowerShell 使用 `-MiniMaxBillingMode MPlan`；Python 内部值为 `m_plan`。
- M Plan 模式不允许 `AI_AGENT_MAX_COST_CNY`，CNY input/output 单价必须保持 0/不传。
- 成功摘要保留 Provider usage，并固定：
  - `billing_mode=m_plan`
  - `estimated_cost_cny=null`
  - `cost_source=m_plan_subscription_quota`
  - `cash_cost_status=not_applicable`
  - `quota_remaining=not_queried`
- 不调用 `token_plan/remains`。这避免用同一 Key 增加两个 quota 网络请求，并保持 M14-T4 的一次模型
  请求边界；代价是不能证明剩余额度、窗口差值或积分包扣减。
- 普通按量兼容路径继续要求 CNY 单价和现金上限，没有被删除或混入 M Plan。

## 验证

| 命令 | 结果 |
| --- | --- |
| MiniMax 专项 `unittest -v` | 21 项通过，2.071s |
| MiniMax/OpenAI/Settings/Runtime/Harness 扩大回归 | 119 项通过，3.003s |
| 修改文件 `compileall -q` | 通过 |
| `scripts/check-continuity.ps1` | 52 个稳定任务、178 个 Markdown 文件通过 |
| `git diff --check` 与密钥模式扫描 | 通过；密钥模式预期无匹配 |

所有模型调用均为 fake 或被 `httpx.MockTransport` 截获。asyncio debug slow-task 提示不影响测试结果。

## DeepSeek 备用说明

用户愿意在需要时提供 DeepSeek 按量 Key。官方当前 Vision 文档表明 `deepseek-flash` 支持 Base64 PNG
和 `detail=low`，技术上可做备用；当前优先完成已配置的 MiniMax M Plan，不新增第二个 Provider。
若 MiniMax 真实 E4 失败，先停下记录结果，再由用户决定是否扩展 DeepSeek adapter 并重新授权。

## 下一条原子动作

等待用户明确回复授权恰好一次 MiniMax M Plan 请求。授权后：

1. 只检查 Key 是否存在，不输出值或前缀；
2. 临时子进程设置 `MINIMAX_MODEL=MiniMax-M3` 与既定 Token/timeout/零重试预算；
3. 不设置 `AI_AGENT_MAX_COST_CNY`，不传 CNY 单价，不调用 quota API；
4. 只在该子进程移除 `ALL_PROXY/all_proxy`，保留 HTTP/HTTPS proxy；
5. 执行 `scripts/verify-online.ps1`，参数固定为 `-Authorized -Suite M14 -VisionProvider MiniMax`
   `-VisionModel MiniMax-M3 -MiniMaxBillingMode MPlan`；
6. 成功或失败都停止，不自动重试，并把稳定结果、usage 与套餐口径追加到验证记录。

未获得该句授权前，不读取 Key、不执行 Provider、不尝试 DeepSeek。
