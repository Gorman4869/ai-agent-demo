# M14-T5 第一离线固定评测纵切交接

## 当前结论

- 当前任务：`M14-T5 / in_progress`；验证记录：`V-20261021-001`。
- 验证基线：`af8a752`；实现提交：`44acfd7`。
- 第一纵切已冻结 `advanced-agent-eval-v1`、7 个 Browser/Vision 案例、指标与稳定失败/降级码。
- 新增 9 项、相邻扩大回归 44 项通过；CLI 退出 0。
- 没有读取 Key、访问 Provider/公网、启动 Chromium、查询套餐、安装依赖或 push。

## 修改文件

| 文件 | 修改 |
| --- | --- |
| `backend/app/evals/advanced_agent.py` | 固定任务 loader、Browser/Vision 执行、指标、内容安全报告和 CLI |
| `backend/app/evals/fixtures/advanced_agent_v1.json` | 7 个版本化成功、拒绝、降级和安全案例 |
| `backend/tests/test_advanced_agent_eval.py` | 9 个 dataset、指标、脱敏、阈值和离线 Provider 门测试 |
| `docs/m14-advanced-agent-evaluation.md` | 命令、案例、指标口径、失败处理和证据边界 |
| `BACKEND_CODING_STANDARDS.md` | 固定评测模块、内容边界和证据口径 |
| `docs/implementation-plan.md` | 记录 M14-T5 第一纵切结果和未完成边界 |

## 固定结果

- dataset version：`m14-advanced-agent-v1`；digest：
  `a5a2ef030139ded150bcf823fb991a3da0b558e72401397b7040c7b433ec47f8`。
- expectation pass 7/7；task completed 3/7；safety 4/4；approval intervention 1/7；9 steps。
- `approval_required`、`origin_not_allowed`、`invalid_png_signature`、`provider_timeout` 各 1 次，均有
  稳定 mitigation code。
- 本次 CLI 的 Browser/Vision 本地 wall-clock 分别为 0.671/40.621 ms；仅是一次本机 fixture 观察。
- Provider usage、Token、费用和币种均为 `null`；没有复用历史在线 usage。

## 失败尝试

受限 Windows sandbox 的首次新增测试在三个 Temp 写入用例报 `PermissionError/WinError 5`，随后
`IsolatedAsyncioTestCase` 本地 socketpair 阻塞。改为工作区临时目录后，完整 async 测试仍按仓库既有
方式在沙箱外执行并 9/9、44/44 通过。该失败不涉及 Provider 或公网，记录保留在
`V-20261021-001`。

## 未验证范围

- Browser evaluator 目前使用 `BrowserAgent.run()`，真实 Chromium 未进入同一报告。
- Vision evaluator 使用确定性 fixture model；没有在线质量、usage/cost 或生产 latency。
- human-intervention rate 是需要精确审批的案例比例，不是观察到的人类操作或工时。
- 该纵切不能证明公网浏览、真实 DNS/redirect、个人 profile、Provider 质量或生产容量。

## 下一条原子动作

复用相同 dataset version、case ID 和报告字段，为 Browser 正常案例增加显式的受控 Playwright
fixture adapter：使用现有 `PlaywrightBrowserDriver`/server-owned fixture，不开放公网、不加载个人
profile、不读取模型 Key。先保持默认 CLI 离线，再通过显式参数或独立入口记录真实 Chromium E3；
补正常路径、页面漂移/元素消失失败与报告口径测试。任何 Provider 调用仍需新的用户明确授权。
