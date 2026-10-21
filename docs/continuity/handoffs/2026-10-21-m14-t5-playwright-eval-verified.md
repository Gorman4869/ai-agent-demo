# M14-T5 受控 Playwright 固定评测交接

## 当前状态

- M14-T5 已达到 `verified`；验证记录为 `V-20261021-002`。
- 验证基线 `896f754`；实现提交 `3b556b9`。
- 当前任务推进到 `M14-T6 / planned`。
- 没有读取 Key、访问 Provider/公网、加载个人浏览器数据、安装依赖或 push。

## 本轮修改

| 文件 | 作用 |
| --- | --- |
| `backend/app/evals/advanced_agent.py` | 保留默认离线档位，新增显式 `playwright_fixture` driver、执行档位报告与浏览器漂移修复码 |
| `backend/tests/test_advanced_agent_eval.py` | 固定 driver 注入、执行档位、page drift/element missing 和默认离线边界 |
| `backend/tests/advanced_agent_browser_integration.py` | 让固定评测 Browser 正常案例实际进入仓库既有 Playwright Chromium |
| `docs/m14-advanced-agent-evaluation.md` | 补显式命令、档位差异、前置观察和证据边界 |
| `BACKEND_CODING_STANDARDS.md` | 固定真实 Browser 评测的 profile、fixture 和失败处理规则 |
| 连续性文档 | 登记验证、状态、已知问题证据、实施计划和恢复入口 |

## 复现命令

```powershell
.\.venv\Scripts\python.exe -B -m backend.app.evals.advanced_agent
.\.venv\Scripts\python.exe -B -m backend.app.evals.advanced_agent --browser-driver playwright-fixture
.\.venv\Scripts\python.exe -B -m unittest backend.tests.test_advanced_agent_eval backend.tests.test_browser_agent backend.tests.test_browser_network backend.tests.test_browser_driver backend.tests.browser_driver_integration backend.tests.advanced_agent_browser_integration backend.tests.test_multimodal_agent backend.tests.test_advanced_harness -v
```

第二、三条需要本地进程/Chromium 权限；都只使用 server-owned fixture，不访问公网。受限 Windows
sandbox 可能在 Python asyncio socketpair 或子进程处阻塞，应在获准的本地进程边界重跑，不能改成
跳过测试或连接用户 Chrome profile。

## 已验证事实

- 两种档位复用相同 dataset version、digest、7 个 case ID、阈值和指标定义。
- 两种 CLI 均为 7/7 expectation、3/7 completed、4/4 safety、1/7 approval fixture、9 steps。
- 显式档位的 Browser 正常案例通过 `BrowserAgent.run_with_driver()` 执行真实 DOM 读取；审批缺失和
  越权 origin 仍拒绝。
- 页面漂移和元素消失以稳定码进入报告，并建议重新观察/重规划；不自动重试或扩大权限。
- Provider usage、Token、费用和币种保持 `null`；历史 MiniMax E4 没有混入本次报告。
- 评测单元 11 项、显式评测 Chromium 1 项、相关合并 59 项通过。

## 失败尝试

- 受限沙箱中的单测再次停在 `IsolatedAsyncioTestCase` 本地 socketpair；执行器结束后无残留 Python
  进程。相同命令在获准边界 11/11 通过。
- 首次合并回归把模块名误写为 `backend.tests.test_multimodal`，46 个实际用例通过但 import error
  令命令退出 1；改为 `backend.tests.test_multimodal_agent` 后 59/59 通过。

## 未验证范围

- Chromium 仍只访问 route-fulfilled fixture，不证明公网、真实 DNS/TLS/redirect、个人登录态、
  跨平台浏览器或生产 egress。
- Vision 仍为确定性离线模型；在线质量只引用 M14-T4 独立的一次 MiniMax E4。
- human-intervention rate 是需要精确审批的 fixture 比例，不是观察到的人员操作或工时。
- 本地 wall-clock 不是 Provider latency、生产 SLA 或容量；usage/cost unknown/null 不是零成本声明。

## 下一条原子动作

进入 M14-T6 前先做只读缺口审计：盘点 M12–M14 已有业务场景、架构图、部署、演示脚本、评测、
成本、威胁模型、故障复盘和迁移说明，输出一张缺口矩阵并确定最小第一纵切。此动作不修改运行时代码，
不触发在线模型、远程部署、视频上传或付费调用；若后续需要这些能力，必须另取用户明确授权。
