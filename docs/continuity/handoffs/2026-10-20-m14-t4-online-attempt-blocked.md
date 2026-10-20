# M14-T4 首次在线视觉尝试阻断交接

- 日期：2026-10-20，Asia/Shanghai
- 当前分支：`main`
- 验证基线：`e6ed850`（`feat: add guarded vision smoke runner`）
- 本轮提交：尚未创建；本 handoff 覆盖 SOCKS fail-fast 修复 worktree，下一恢复记录补记新 HEAD
- 当前状态：`M14-T4 / code_complete`
- 验证记录：`V-20261020-002`
- 关联决策：`ADR-0042`
- 在线状态：首次单次授权已经消耗；真实 E4 未完成，费用 `unknown`

## 实际在线尝试

1. 按 OpenAI 官方模型与定价页选择 `gpt-5.4-mini`，标准费率为 input `US$0.75`、output
   `US$4.50` / 1M Token。
2. 固定上限为 2000 input、256 output、一次 model call、零重试，操作者费率最坏估算为
   `US$0.002652`，低于本地 `US$0.05` 门。
3. 用户明确授权后只执行了一次 `scripts/verify-online.ps1 -Authorized -Suite M14`。命令返回
   `provider_unavailable`，没有 observation、usage 或 Provider 状态码；失败后未重试。
4. 只读环境诊断确认 HTTP/HTTPS proxy 为 HTTP，而 `ALL_PROXY` 为 SOCKS5，虚拟环境未安装
   `socksio`。dummy Key 离线构造也在 `AsyncOpenAI` 初始化阶段抛出 `ImportError`，因此现有证据
   表明请求在 Provider 之前被阻断。
5. 没有 Provider usage 或账单回执，实际费用记录为 `unknown`，不得写成确定的 0。

## 本轮修复

- `backend/app/vision_online_smoke.py` 在读取完既有显式授权/模型/预算配置后、SDK 构造前检查
  HTTP/HTTPS/ALL proxy 的 scheme。
- 如果存在 SOCKS proxy 且当前环境缺少 `socksio`，以内容无关配置错误 65 fail closed；不输出
  proxy 地址，不创建 SDK client，也不触发部分初始化对象的清理 stderr。
- `backend/tests/test_vision_online_smoke.py` 新增 SOCKS 缺依赖提前失败和普通 HTTP proxy 不受影响
  两项回归；视觉 smoke、M8 smoke、Multimodal 定向集共 37 项通过。
- 未安装依赖，未修改用户或系统代理，未修改 Key、数据库、HTTP API、前端、默认离线验证路径或
  `docs/progress.md`。

## 失败边界

- 这次结果不是 OpenAI 模型不支持图片的证据，也不是 Provider 拒绝；现有失败点在本机 SDK HTTP
  client 构造阶段。
- M14-T4 仍为 `code_complete`，不是 `verified`。真实图片输入、OCR、structured observation、
  usage 和费用仍缺 E4。
- 当前视觉实现仍是 OpenAI Responses API 的 `responses.parse` 适配器。MiniMax 的
  OpenAI-compatible multimodal 文档使用 Chat Completions；若切换 Provider，需要独立适配与离线
  合同测试，不能只替换 Key/Base URL，也不能复用本次已消耗的授权。

## 下一条原子动作

先提交本轮 SOCKS fail-fast 修复。之后只有取得用户新的明确单次授权，才允许再发一次真实请求：

1. 继续 OpenAI 时，仅在该临时子进程移除 `ALL_PROXY/all_proxy`，保留 HTTP/HTTPS proxy；沿用
   `gpt-5.4-mini`、`0.75/4.50`、一次请求和零重试。
2. 若改用 MiniMax，先确认中国平台还是国际平台、具体视觉模型与官方费率，再新增独立 adapter、
   配置门和离线测试；Key 只通过本机环境变量提供，不写入聊天、源码、文档、日志或 Git。

不得自动重试、不得安装依赖、不得改全局代理、不得 push、不得提前进入 M14-T5。
