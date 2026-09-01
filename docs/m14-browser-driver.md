# M14-T1 受控真实 Browser Adapter

本任务让现有离线 `BrowserAgent` 真正驱动 Chromium，但默认只运行服务端提供的合成 HTTPS 页面。
它证明 planner、policy、approval 和 driver 的分层，以及真实 DOM、事件和截图链路；不代表可以
安全访问任意公网网页。

## 架构边界

```text
模型结构化动作
  -> BrowserAgent 校验/编译
  -> 页面摘要与精确单次审批
  -> PlaywrightBrowserDriver
  -> 有界 Node 子进程
  -> 全新 Chromium Context
  -> route-fulfilled BrowserFixtureSite
  -> DOM/截图 observation
```

可以把它类比为前端低代码平台：模型只提交“点击 `submit-button`”这类组件 ID，不能提交
`document.querySelector()` 或任意脚本；Policy 像页面权限配置，Driver 才是实际操作浏览器的
运行时。即使模型说“点第一个红色按钮”，服务端目录里没有对应稳定 ID，也不会执行。

## 当前动作与观察

| 能力 | 当前合同 |
| --- | --- |
| navigate | 仅精确命中 `BrowserFixtureSite` 的 HTTPS 文档 |
| read_text | 元素必须存在、可见、唯一且页面摘要未变化 |
| click/type/submit | 同样校验页面，并消费精确单次审批 |
| DOM observation | 标题、path/query、稳定元素 ID/tag/text/type 的 SHA-256 摘要 |
| screenshot | 真实 Chromium PNG；字节上限、签名和 SHA-256 均复核，内容不进入 repr |
| 浏览器上下文 | 每次全新 context，不加载用户 profile、Cookie、账号或扩展 |
| 网络 | route 拦截全部请求；未登记 origin/文档/子资源 fail closed |

DOM 动作使用观察后再执行：第一次只 navigate 得到 `page_digest`，第二次把该 digest 放进动作。
若页面结构或目标元素变化，执行返回 `browser_page_changed` 或 `browser_element_missing`，而不是
猜测 selector 继续点击。type 不把输入框当前 value 写入结构摘要，因此同一批准计划可以连续
type 和 submit；submit 改变 DOM 后，下一动作需要新观察。

## 验证命令

在仓库根目录执行离线合同测试：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_browser_agent backend.tests.test_browser_driver -v
```

再显式执行真实 Chromium 集成测试：

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.browser_driver_integration -v
```

第二条命令会启动仓库已有 Playwright Chromium，但不访问公网。它覆盖真实 DOM 读取、输入、
提交、PNG 截图，以及页面摘要不一致、元素消失、跨域、`window.open` 新窗口/弹窗和下载拒绝。
如果系统临时目录或子进程被当前沙箱阻止，应在获准的本地进程边界重跑；不要把环境拒绝记成
浏览器代码通过，也不要通过连接用户 Chrome profile 绕过。

## 稳定错误排查

| 错误 | 含义 | 首查 |
| --- | --- | --- |
| `browser_observation_required` | DOM 动作没有前次页面摘要 | 先只 navigate 获取 observation |
| `browser_page_changed` | 计划与实际 DOM 摘要不一致 | 重新观察并重新审批，不复用旧摘要 |
| `browser_element_missing` | 稳定元素 ID 不存在或不可见 | 检查 fixture 与服务端元素目录 |
| `browser_cross_origin` | 页面尝试离开 fixture origin | 检查 link/form；不要扩大 allowlist |
| `browser_popup_blocked` | 页面打开弹窗或新窗口 | 当前合同默认拒绝，不改成静默跟随 |
| `browser_download_blocked` | 页面触发下载 | 下载策略属于 M14-T2 |
| `browser_driver_unavailable` | Node/Chromium 或受控进程不可用 | 检查既有 Node 22、Playwright browser 和进程权限 |
| `browser_driver_invalid_response` | 子进程输出/JSON/截图不满足合同 | 查固定脚本与版本，不打印原始页面或异常内容 |

## 明确未完成

- 审批尚未绑定规范化完整 URL 和整个 plan digest。
- 没有 DNS 解析、私网/链路本地/云元数据判断或逐次 redirect 复核。
- 没有上传/下载许可策略、真实公网网页、真实登录态或用户 Cookie。
- 没有证明线上站点兼容、浏览器集群容量、跨平台 Chromium 或生产隔离。

这些边界由 M14-T2 继续处理，`KI-010` 仍保持 open。
