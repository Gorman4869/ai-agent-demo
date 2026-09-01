# M14-T2 交接：Browser 完整审批与 SSRF 防护

- 日期：2026-09-01，Asia/Shanghai
- 当前任务：`M14-T2 / verified`
- 下一任务：`M14-T3 / planned`
- 验证基线：`4ddfd68`
- 验证记录：`V-20260901-005`
- 关联决策：`ADR-0041`
- 任务等级：A 类浏览器安全/审批公共合同 + C 类本地真实 Chromium
- 证据等级：fixture-only 离线 E3
- 在线模型/费用：未调用，费用 0
- 远程 Git：未 push

## 本次结果

`BrowserAgent` 现在把每个 URL 规范化为完整 page URL，并对所有冻结动作计算 plan digest。副作用
审批同时绑定完整 URL 的摘要/字节数和整个 plan digest，仍由 principal、tool call ID、tool name、
动作、元素、参数摘要和页面摘要共同限定且单次消费。跨 path/query、相同动作但其他计划步骤变化、
伪造 digest 都无法复用旧审批，URL 和 typed value 原文不进入 repr。

新增显式 `BrowserAddressResolver`/`BrowserNetworkPolicy`。初始 URL、每个服务端 redirect 和最终
URL 都重新解析并检查全部地址；任一 loopback/private/link-local/shared/reserved/multicast/
unspecified/metadata/非法回答即整体拒绝。Driver validate 与 execute 边界会再次解析，DNS
rebinding 在 Node/Chromium 进程启动前 fail closed；redirect 循环、跳数超限和跨域同样拒绝。

fixture redirect 由 Python 完整预验证后，Node 直接导航最终登记文档。页面运行时请求 redirect
source 会以 `browser_redirect_unplanned` 拒绝。模型 `upload`/`download` 动作继续禁止，真实
file chooser/download/popup/new window/cross-origin 事件也默认拒绝。没有新增依赖或公网入口。

## 修改文件

- `backend/app/advanced/browser_agent.py`
- `backend/app/advanced/browser_network.py`
- `backend/app/advanced/browser_driver.py`
- `backend/app/advanced/__init__.py`
- `frontend/scripts/controlled-browser-driver.mjs`
- `backend/tests/test_browser_agent.py`
- `backend/tests/test_browser_network.py`
- `backend/tests/test_browser_driver.py`
- `backend/tests/browser_driver_integration.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/m14-browser-security.md`
- `docs/stages/14-advanced-capstone.md`
- `docs/implementation-plan.md`
- `docs/continuity/decisions/ADR-0041-browser-url-approval-and-network-policy.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- 本 handoff

依赖、锁文件、HTTP API、Vue 产品代码、数据库、部署、已接受 ADR、用户 `.env` 和
`docs/progress.md` 未修改。Node 保持 22.16.0，不需要 nvm 切换。

## 验证与失败尝试

- `node --check frontend/scripts/controlled-browser-driver.mjs` 退出 0。
- 最终纯 Browser plan/network 策略 19 项通过。
- Driver 受限沙箱首轮 3 项通过、5 项因 Python 系统临时目录 `WinError 5` 在业务断言前 error；
  同一 8 项在获批沙箱外全部通过。
- 地址分类首轮发现 `224.0.0.1` 不能只依赖当前 Python `is_global`；补显式 multicast/reserved/
  unspecified 拒绝后矩阵通过。
- 合成 302 的真实 Chromium redirect 首轮 timeout；三个最小无公网探针复现。按 Playwright route
  redirect 边界改为“Python 逐跳预验证 + Chromium 最终 fixture”，最终真实 Chromium 4 项通过，
  8.728s。
- 最终 Browser Agent/Network/Driver/Chromium 合并 31 项全部通过，8.597s。
- Advanced Harness、Browser、Code Agent Process、Multimodal 相关回归 52 项通过、1 项既有
  Windows symlink 能力条件跳过，4.289s。
- 两次沙箱外 `git add -- <18 个任务文件>` 都在进程创建前因自动权限审查超时而未执行；仓库
  沙箱内尝试以 `.git/index.lock: Permission denied` 退出。只读复核确认没有 staged 文件、没有
  残留 lock，修改完整保留。用户随后明确授权同一 18 文件暂存/本地提交，重试成功并以
  `feat: harden browser URL policy` 收口；未 push。
- 没有运行完整 703+ offline、MCP、Vue build、Docker/PostgreSQL 或 online profile；本任务没有
  改依赖/锁文件、HTTP API、产品前端、数据库或部署，相关安全回归和真实 Chromium 覆盖修改面。

## 已固定安全边界

- 完整 canonical page URL + 整份 plan digest 精确单次审批；
- 每次 resolver 调用无跨边界缓存，全部解析地址必须为公网；
- 初始 URL、每个 redirect、最终 URL 和 driver 执行入口重复验证；
- DNS rebinding、混合 DNS、metadata、loop/limit/跨域在浏览器进程前拒绝；
- upload/download/popup/new window 和页面运行时未规划 redirect 默认拒绝；
- fresh Chromium context、fixture-only route、无公网、Key、个人 profile/Cookie；
- URL、DOM、输入值、截图、resolver 回答和原始异常不进入稳定错误或公开 repr。

## 残余边界

`KI-010` 在 M14-T2 的 fixture-only E3 范围关闭，不代表已经开放任意公网浏览器。没有验证真实
公网 DNS/远端 HTTP redirect、transport 与 policy 的 DNS pinning、TLS/证书、系统/浏览器代理、
生产 egress、Linux/macOS Chromium、浏览器集群容量或个人登录态。`SystemBrowserAddressResolver`
只提供后续 adapter seam；当前 driver 必须继续使用 server-owned fixture。

上传下载只有“拒绝”策略，没有安全许可分支。未来开放文件传输必须新设计来源、MIME、大小、扫描、
隔离目录、审批、幂等和清理，不能把本次事件拒绝改成静默允许。

## 下一条原子动作

开始 M14-T3 前按 AGENTS 顺序恢复，读取本 handoff、`V-20260901-005`、`ADR-0041`、
`docs/m14-browser-security.md`、实施计划 M14-T3、M8 统一模型 adapter 和当前
`backend/app/advanced/multimodal.py`/测试。先只读冻结：

1. 离线 Fake Vision 与真实视觉 adapter 的共同结构化观察；
2. OCR/视觉文字始终是 untrusted data，不能提升权限或直接触发工具；
3. 图片 MIME/格式/字节/尺寸/像素预算和稳定失败；
4. 无在线授权时的确定性回退与 T4 单次在线授权边界。

不要在 M14-T3 执行在线视觉调用，不读取 Key/用户 `.env`，不访问个人账号，不安装依赖、不修改
`docs/progress.md`、不 push。
