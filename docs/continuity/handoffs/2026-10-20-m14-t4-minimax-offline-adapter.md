# M14-T4 MiniMax 国内视觉离线适配交接

## 当前结论

- 当前任务仍是 `M14-T4 / code_complete`，验证记录为 `V-20261020-001/002/003`。
- 本轮验证基线为 `8f5c528`；该提交已包含 OpenAI 视觉 smoke 的 SOCKS fail-fast 修复。
- MiniMax 国内备用 adapter、独立人民币低预算 CLI、PowerShell 路由、ADR、说明和测试已完成。
- 用户说明国内平台 Key 已配置，但没有授权本轮真实调用；没有读取 Key、访问 MiniMax、发送图片或
  产生费用，E4 仍未完成。

## 本轮修改

| 文件 | 作用 |
| --- | --- |
| `backend/app/advanced/multimodal.py` | 增加固定 `MiniMax-M3` 的无工具 Chat Completions 视觉 adapter、客户端工厂和 usage 映射 |
| `backend/app/advanced/__init__.py` | 导出 MiniMax adapter 与工厂 |
| `backend/app/minimax_vision_smoke.py` | 独立授权/模型/代理/Token/CNY 成本门和内容无关证据 CLI |
| `backend/tests/test_minimax_vision_smoke.py` | 16 项 MiniMax 门禁、真实 SDK MockTransport、严格 JSON、usage/费用和脚本测试 |
| `scripts/verify-online.ps1` | M14 增加显式 `OpenAI`/`MiniMax` Provider 路由；M8/既有 OpenAI 兼容不变 |
| `docs/continuity/decisions/ADR-0043-minimax-cn-vision-adapter.md` | 固定端点、模型、本地结构化解析、Key 和币种边界 |
| `docs/m14-minimax-vision-smoke.md` | 执行门、官方费率、唯一入口和证据边界 |
| `docs/implementation-plan.md`、连续性文档 | 更新当前任务、`KI-033`、`V-20261020-003` 与恢复入口 |

## 冻结合同

- Base URL 固定 `https://api.minimax.cn/v1`，模型固定 `MiniMax-M3`；不允许环境覆盖发送目标。
- 使用 `/v1/chat/completions`、Base64 PNG、`detail=low`、`thinking=disabled`、`temperature=0`、
  `max_completion_tokens<=256`、一次请求、零重试、无 tools。
- MiniMax 文档没有声明 `response_format/json_schema`。adapter 用固定 JSON prompt 与本地 Pydantic
  `extra=forbid` 严格解析；fence、额外文字、截断、非 stop、字段或 usage 异常均 fail closed。
- 默认离线路径、统一 Settings、主 Runtime、HTTP API、数据库、前端和 OpenAI Responses adapter
  均未迁移到 MiniMax。
- MiniMax CLI 只在显式授权后读取 `MINIMAX_API_KEY`，要求 `MINIMAX_MODEL=MiniMax-M3` 和
  `AI_AGENT_ONLINE_ENABLED=true`；Key 使用 `SecretStr`，不出现在 stdout、repr、错误或文档。

## 费用与 Key 类型

- 普通按量 `MiniMax-M3` 标准层、输入不超过 512k 的核对费率：input `2.10`、output `8.40 CNY /
  1M Token`。
- 2000 input + 256 output 的声明上界为 `0.00635040 CNY`，本地费用门为 `0.05 CNY`。
- 费用是操作者费率乘 Provider 返回 usage 的估算，不是账单或 Provider 侧硬停止。
- 执行前必须由用户确认 Key 是普通按量还是 M Plan/Token Plan。订阅 Key 应记录套餐额度/usage，
  不能把上述按量费率写成实际现金支出。

## 已执行验证

| 命令 | 结果 |
| --- | --- |
| `./.venv/Scripts/python.exe -B -m unittest backend.tests.test_minimax_vision_smoke -v` | 16 项通过 |
| MiniMax + OpenAI 视觉 + M8 smoke + Multimodal 合并回归 | 53 项通过 |
| 再加入 Settings、OpenAI Runtime、Advanced Harness 的扩大回归 | 114 项通过，2.356s |
| 修改 Python 文件 `compileall -q` | 通过 |
| `scripts/check-continuity.ps1` | 52 个稳定任务、177 个 Markdown 文件通过 |
| `git diff --check` | 通过，只有 LF/CRLF 工作树提示 |

真实 SDK 纵切使用 `httpx.MockTransport` 截获 `/v1/chat/completions`，没有公网流量或真实 Key。一次
asyncio debug slow-task 提示不影响测试结论。完整命令和边界见 `V-20261020-003`。

## 失败尝试与未验证范围

- OpenAI 首次授权已消耗且失败，事实保留在 `V-20261020-002`；不得复用该授权。
- MiniMax 本轮没有失败的在线尝试，因为没有取得新的单次授权，也没有读取 Key。
- 未验证真实模型是否稳定返回严格 JSON、是否识别固定图片文字、真实 usage、Provider 错误形状、
  TLS/代理链、延迟、费用或订阅额度。
- `KI-033` 保持 open；一次成功 smoke 只能补 M14-T4 E4，不能证明生产上传安全或关闭通用
  `KI-018` 硬成本缺口。

## 下一条原子动作

先询问用户：环境中的 Key 是“普通按量”还是“M Plan/Token Plan”，以及是否授权恰好一次
`MiniMax-M3` 视觉请求。只有类型和一次性授权同时明确后：

1. 不输出 Key，只预检环境变量是否存在、模型和低预算值是否正确；
2. 在唯一临时子进程移除 `ALL_PROXY/all_proxy`，保留 HTTP/HTTPS proxy，不改用户/系统环境；
3. 普通按量 Key 使用 `2.10/8.40 CNY` 当前费率；订阅 Key 先明确额度记录口径，不冒充现金账单；
4. 执行 `scripts/verify-online.ps1 -Authorized -Suite M14 -VisionProvider MiniMax`，恰好一次、零重试；
5. 将结构化 observation 是否成功、usage、费用/额度、时延和安全布尔值追加到 verification log；
6. 失败后停止，不自动重试；再次请求必须取得新的授权。

在用户只说明“Key 已配置”但未明确上述两项时，继续保持离线，不读取或调用。
