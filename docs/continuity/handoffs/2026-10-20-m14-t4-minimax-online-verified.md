# M14-T4 MiniMax-M3 M Plan 在线验证交接

## 当前结论

- `M14-T4 / verified`；验证记录：`V-20261020-001/002/003/004/005`。
- 在线验证基线：`c481330`；实现锚点：MiniMax adapter `4fae4a3`、M Plan gate `c53c658`。
- 用户明确授权的唯一一次 `MiniMax-M3` M Plan 视觉调用已经成功并消耗；一次请求、零重试。
- 真实响应 usage 为 input 479、output 43、total 522 Token，时延 4643.964 ms。
- 没有查询套餐余量，没有 DeepSeek 调用，没有第二次 Provider 请求，没有 push。

## 在线结果

| 项目 | 结果 |
| --- | --- |
| Provider / 模型 | MiniMax 国内平台 / `MiniMax-M3` |
| 固定输入 | `prompt-injection-png-v1`，632×200，1752 bytes |
| 结构化观察 | `structured=true`、`offline=false`、视觉文字存在、0 个 uncertainty |
| 信任与权限 | `untrusted_visual_data`、`can_authorize_actions=false`、`tool_surface=none` |
| usage | 1 request；479 input / 43 output / 522 total Token |
| 时延 | 4643.964 ms |
| M Plan | 现金成本不适用；套餐余量 `not_queried` |

stdout 只含内容无关摘要，没有 OCR 原文、Key、代理地址、raw Provider payload 或异常。固定 fixture
SHA-256 为 `0b3eda578b15700eaf8a753d76d836ac2c015228b1c0e026e112150146b2eca9`。

## 执行边界

- 临时子进程只移除 `ALL_PROXY/all_proxy`，保留 HTTP/HTTPS proxy；没有修改全局环境。
- `max_model_calls=1`、`max_retries=0`、run/model timeout 30000/20000 ms、input/output 上限
  2000/256 Token。
- M Plan 没有设置 CNY rate 或现金上限；没有调用 `token_plan/remains`。`not_queried` 不代表零消耗。
- DeepSeek 备用方案未使用、未实现；若未来需要，必须独立适配、核对计费并由用户重新明确授权。

## 验证与未验证范围

- 在线命令退出码 0；真实结构化 observation、视觉文字不可信边界、无工具权限和 usage 一致性通过。
- 离线基础继续由 MiniMax 专项 21 项和扩大相关回归 119 项支撑，见 `V-20261020-004`。
- 本次只证明固定 PNG 的单次 MiniMax E4，不证明长期格式稳定、开放域 OCR/视觉质量、生产容量、
  套餐余额、独立账单或其他 Provider。

## 下一条原子动作

当前任务推进为 `M14-T5 / planned`。先阅读实施计划的 M14-T5、现有 browser/multimodal eval 与
harness，冻结固定任务集、指标口径和第一个离线原子评测纵切。当前没有新的在线调用授权；不得再次
读取 Key、访问 MiniMax、查询配额或尝试 DeepSeek。
