# ADR-0040：受控 Fixture 的真实浏览器 Driver

- 状态：accepted
- 日期：2026-09-01
- 任务：`M14-T1`
- 依赖：`ADR-0035`、`ADR-0038`

## 背景

仓库已有 `BrowserAgent`，但它只校验并模拟结构化动作，没有真实执行 DOM、截图、点击或输入。
直接让模型操作任意 Playwright selector、JavaScript 或公网网页，会跳过既有 Policy/Approval，并把
SSRF、登录态、下载和弹窗风险一次引入。Python 后端也没有 Playwright 依赖，而前端已经锁定
`@playwright/test`。

M14-T1 只需要证明真实浏览器 adapter 和受控动作纵切；完整 URL/计划审批、DNS/IP、重定向和
上传下载策略属于 M14-T2，不能在当前任务中用不完整实现提前关闭 `KI-010`。

## 决策

### 1. 保留 planner/policy，显式注入 driver

`BrowserAgent.validate_plan()` 继续把模型输出编译成稳定动作；原 `run()` 保留为离线安全对照。
新 `run_with_driver()` 在执行边界重新验证计划，先检查 driver 合同和全部副作用审批，再把冻结
动作交给显式注入的 `BrowserDriver`。模型不能提供 selector、脚本、命令、环境或文件路径。

### 2. Python 通过受控子进程调用仓库已有 Playwright

`PlaywrightBrowserDriver` 复用前端已锁定的 `@playwright/test`，不增加 Python/Node 依赖。Python
只把服务端构造的 versioned JSON 写入权限受限临时文件，再通过 M13 的 `run_bounded_process()`
启动固定 Node 脚本。argv、cwd、环境、wall time、输出和进程树资源均由服务端固定；Provider Key
不进入子进程，stdout/stderr 必须为空，响应大小和字段重新校验。

### 3. 真实 Chromium 只访问内存 fixture

每次执行创建全新的无持久化 BrowserContext，不加载用户 profile、Cookie 或账号。Playwright
route 拦截所有请求，只对 `BrowserFixtureSite` 中精确登记的 HTTPS URL 返回服务端 HTML；其他
origin、未知文档和子资源全部中止。因此证据是真实 Chromium DOM/事件/截图 E3，但不是公网、
DNS、重定向、真实站点兼容或个人登录态 E4。

### 4. DOM 动作绑定页面观察

页面观察包含规范化路径、标题和服务端 `data-agent-id` DOM 摘要的 SHA-256、可见元素 ID、受限
正文和 PNG 截图。URL、标题、正文和截图内容在 Python dataclass 的 `repr` 中隐藏。除 navigate
外，每个真实 DOM 动作都必须携带前次 `expected_page_digest`；元素必须存在、可见且唯一，页面
或元素漂移就 fail closed。输入值不参与结构摘要，使同一已观察表单可按已审批计划完成 type 后
submit；DOM 变化后的后续动作必须重新观察。

### 5. 高风险浏览器能力默认关闭

跨域导航、未知 fixture、弹窗/新窗口和下载统一返回稳定无内容错误。模型仍不能请求 download、
upload、任意 selector 或 JavaScript。click/type/submit 继续消费精确单次审批；当前审批绑定动作、
origin、元素、值摘要和页面摘要，但尚未绑定完整 URL 与整个计划摘要。

## 后果

- 默认测试仍离线、无 Key、无公网、无新增依赖；真实 Chromium 通过显式 integration 模块运行。
- 真实 DOM 读取、输入、提交、截图和浏览器事件进入调用链，不再用 import 或手写模拟冒充。
- Python/Node 边界只交换有界结构化数据，浏览器正文与截图不会出现在 repr、进程输出或稳定错误。
- `KI-010` 保持 open；M14-T2 必须补完整 URL/plan digest 审批和 DNS/IP/redirect 防护后才能考虑关闭。

## 未采用方案

- 在 Python 新增 Playwright：仓库已有锁定 Node 依赖，当前任务无需扩大依赖和 CI 安装面。
- 连接用户 Chrome profile：会引入真实账号、Cookie、扩展和个人数据，不符合课程受控边界。
- 用 localhost HTTP server 作为默认 fixture：会混入端口、监听和操作系统网络差异；route fulfill
  已能在真实 Chromium 中确定性执行 DOM 与浏览器事件。
- 允许模型给 CSS/XPath/JavaScript：会绕过服务端元素目录和动作语义，不予采用。
- 在 T1 开放任意公网 HTTPS：仅校验 origin 不足以处理 DNS、私网和重定向，留给 M14-T2。

## 验证依据

- `backend/tests/test_browser_agent.py`
- `backend/tests/test_browser_driver.py`
- `backend/tests/browser_driver_integration.py`
- `frontend/scripts/controlled-browser-driver.mjs`
- `docs/m14-browser-driver.md`
- 本任务对应 verification 记录
