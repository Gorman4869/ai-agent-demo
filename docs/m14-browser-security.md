# M14-T2 Browser 完整审批与 SSRF 防护

M14-T2 把 Browser Agent 从“只允许某个站点”收紧为“审批精确绑定某个页面和整份操作计划，并在
执行前验证每个网络目标”。它仍然是本地 fixture-only E3，不会访问公网或你的 Chrome 登录态。

## 前端业务类比

把 `origin` 想成前端路由的域名权限：允许 `https://ops.example.test`，不代表该域名下所有页面
都能执行同一操作。`/orders/123/refund` 与 `/users/123/delete` 必须是不同审批。`plan_digest` 类似
一次发布单的整体构建摘要：即使最后的“点击提交”动作没变，只要前面新增、删除或调整一步，旧
审批也不能继续使用。

SSRF 则像后端代理请求：页面 URL 看起来是公网域名，但 DNS 可能解析到内网，或先返回公网地址，
随后在 redirect/执行时换成 `169.254.169.254`。因此不能只看字符串域名，必须在每次边界检查
解析后的所有 IP。

## 四层边界

```text
BrowserAgent
  规范化完整 URL -> 冻结 page_url -> 计算整个 plan_digest
        |
Approval
  principal + tool call + action + URL digest + plan digest + 参数摘要
        |
BrowserNetworkPolicy
  初始 URL -> DNS/IP -> 每次 redirect -> 最终 URL -> 执行入口再验证
        |
PlaywrightBrowserDriver
  只导航已验证的最终 fixture；跨域/弹窗/上传/下载全部拒绝
```

## 当前合同

| 范围 | 规则 |
| --- | --- |
| URL | 只接受 HTTPS；规范化 host/default port/空 path，保留 path/query，拒绝 fragment/凭据/localhost |
| 审批 | 副作用动作绑定完整 URL 摘要和整份计划摘要；原文不进入 repr；单次消费 |
| DNS | 每次解析、不跨边界缓存；全部回答都必须是合法公网 IP，数量最多 16 |
| 地址 | loopback/private/link-local/shared/reserved/multicast/unspecified/metadata 全拒绝 |
| redirect | 仅服务端登记，最多 5 跳；逐跳重新解析，拒绝跨域、循环、超限和不安全目标 |
| 上传下载 | 模型动作和真实页面事件都默认拒绝，没有隐式许可 |
| 浏览器 | fresh Chromium context、fixture-only route、无个人 profile/Cookie/公网 |

`BrowserAgent` 编译的 DOM 动作记录原计划页面 URL。若一次 navigate 经过 redirect，当前 driver
不会让后续副作用沿用起始 URL 的审批；应先观察最终 URL，再针对最终页面生成并审批新计划。这是
fail-closed 行为，不会把起始页面的授权扩展到重定向后的页面。

## 验证命令

纯计划与网络策略：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_browser_agent backend.tests.test_browser_network -v
```

Driver 合同：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_browser_driver -v
```

真实 Chromium fixture：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.browser_driver_integration -v
```

最后一条会启动已有 Playwright Chromium，但不会访问公网。它验证正常 DOM/截图、预验证安全
redirect，以及跨域、popup、download 和 file chooser 拒绝。

## 常见错误

| 错误 | 含义 | 正确处理 |
| --- | --- | --- |
| `exact_call_approval_missing` | URL、参数或整份计划与旧审批不一致 | 展示新计划并重新审批，不改宽匹配 |
| `browser_address_not_allowed` | 目标解析到至少一个非公网 IP | 拒绝；检查 DNS/redirect，不加入例外绕过 |
| `browser_dns_unavailable` | 主机无法解析 | fail closed；不降级为直接访问 |
| `browser_dns_invalid_response` | resolver 返回空、超量或非法地址 | 修复 resolver，不忽略坏记录 |
| `browser_redirect_loop` / `browser_redirect_limit` | 跳转循环或超过上限 | 修复服务端 redirect 目录 |
| `browser_redirect_unplanned` | 页面运行时触发未预验证跳转 | 重新进入服务端规划/验证流程 |
| `browser_upload_blocked` / `browser_download_blocked` | 页面请求文件传输 | 当前策略禁止；不能静默允许 |

## 证据范围

本任务证明的是策略 E3 和真实本地 Chromium fixture：没有在线模型、Key、费用、真实公网 DNS、
远端 HTTP redirect、TLS/代理行为、个人账号或生产网络隔离证据。`SystemBrowserAddressResolver` 已
提供可替换 seam，但在开放任意公网前还需要独立任务验证 transport 与 policy 看到的是同一解析
结果，并设计 egress 隔离。
