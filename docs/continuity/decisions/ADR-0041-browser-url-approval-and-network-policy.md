# ADR-0041：浏览器完整 URL 审批与网络策略

- 状态：accepted
- 日期：2026-09-01
- 任务：`M14-T2`
- 依赖：`ADR-0040`

## 背景

M14-T1 已让受控 Browser Agent 通过真实 Chromium 执行 fixture 页面，但审批只绑定 origin、动作、
元素、输入摘要和页面摘要。同一 origin 的不同 path/query 可能复用审批，整个计划被增删动作时也
没有独立绑定。Driver 也没有 DNS 解析后地址分类、逐次 redirect 复核或 DNS rebinding 防护，因此
不能把 fixture-only 证据描述为任意公网 URL 的安全边界。

M14-T2 必须补齐这些合同，同时保持默认离线、无个人登录态、无公网和无新增依赖。

## 决策

### 1. 审批绑定规范化完整 URL 与整个计划

每个 navigate 先规范化为 HTTPS 完整 URL：scheme/hostname 使用规范形式、默认 443 端口省略、空
path 变成 `/`，path 与 query 保留，fragment、凭据、localhost 和 loopback 在计划层拒绝。每个
后续 DOM 动作冻结它所属的 `page_url`。

`BrowserPlan.plan_digest` 对全部冻结动作的 ID、kind、origin、完整 page URL、元素、输入值摘要/
字节数和页面摘要做 canonical JSON SHA-256。副作用审批参数加入规范化完整 URL 的 SHA-256/字节数
和整个 `plan_digest`；URL 与输入原文不进入 repr。审批仍由既有 principal、tool call ID 和 tool
name 共同限定并保持单次消费。换 path/query 或只改变计划中的其他动作都会失配。

### 2. DNS 解析后拒绝所有非公网地址

新增显式注入的 `BrowserNetworkPolicy` 和 resolver Protocol。生产候选 resolver 每次调用
`getaddrinfo()`，不跨验证边界缓存；离线 fixture 和攻击测试使用静态或序列 resolver。每个 DNS
回答都必须是合法 IP，数量有界，只要有一个回答不是公网，或属于 loopback、private、link-local、
shared、reserved、multicast、unspecified，就整体 fail closed。`169.254.169.254` 等 metadata
地址由同一非公网分类拒绝，不维护易漂移的域名黑名单。

### 3. 每个重定向目标重新规范化、解析和分类

fixture redirect 是服务端拥有的有界映射，不接受模型临时提供。Policy 从初始 URL 开始逐跳
重新解析 DNS、检查全部地址、origin、循环和最大跳数；Driver 在执行入口再次运行同一验证，避免
只依赖计划时 DNS 结果。任一跳指向私网、metadata、跨域、循环或超限即在 Chromium 启动前拒绝。

Playwright 的 [Page.route 文档](https://playwright.dev/docs/api/class-page#page-route) 说明，route
handler 对重定向响应后的请求不会按普通新请求重复调用同一处理链。
因此本地 fixture 不用合成 302 来证明网络安全：Python 先验证完整服务端 redirect 链，Node 只
导航到已验证的最终 fixture 文档；页面运行中若仍请求 redirect source，则返回
`browser_redirect_unplanned`。这只证明受控 fixture E3，不等于真实公网 redirect E4。

### 4. 上传、下载和新窗口继续默认拒绝

模型动作层明确拒绝 `upload` 与 `download`。真实页面触发 file chooser、download、popup/new window
或跨域导航时，Node bridge 返回稳定 fail-closed 错误。当前没有“允许传输”的策略分支；未来若
要开放，必须另行设计文件来源、大小、MIME、扫描、落盘目录、审批和清理合同。

## 后果

- 跨 path/query 和跨计划审批复用都有独立自动化证据，URL 原文不进入审批 repr。
- 私网、loopback、link-local、保留/组播/未指定地址、混合 DNS 回答、metadata、DNS rebinding、
  redirect loop/limit/跨域和上传下载均 fail closed。
- `SystemBrowserAddressResolver` 只是未来真实 HTTPS adapter 的安全 seam；M14-T2 的 Chromium 仍只
  执行 server-owned fixture，没有访问公网或真实 DNS，也没有加载个人 profile/Cookie。
- `KI-010` 可在本任务 E3 范围关闭，但任意公网浏览器、真实远端 redirect、代理解析一致性、
  TLS/证书策略、浏览器网络隔离和生产 egress 仍未验证。

## 未采用方案

- 只把 origin 放进审批：无法区分 `/approve` 与 `/admin/delete`，不满足完整 URL 绑定。
- 只在计划阶段解析一次 DNS：执行前地址可能变化，无法覆盖 DNS rebinding。
- DNS 有一个公网地址就放行：浏览器可能选择同组里的私网地址，必须任一不安全即整体拒绝。
- 维护 metadata hostname 黑名单：IP/redirect 变体容易绕过，解析后地址分类更稳定。
- 用 Playwright `route.fulfill({status: 302})` 模拟真实网络链：redirect 后续请求不进入预期 fixture
  handler，且会混入外部网络；改为先验证服务端链，再导航到最终 fixture。
- 连接用户 Chrome 或开放真实下载目录：会引入账号、Cookie、个人文件和不可控副作用。

## 验证依据

- `backend/tests/test_browser_agent.py`
- `backend/tests/test_browser_network.py`
- `backend/tests/test_browser_driver.py`
- `backend/tests/browser_driver_integration.py`
- `frontend/scripts/controlled-browser-driver.mjs`
- `docs/m14-browser-security.md`
- 本任务对应 verification 记录
