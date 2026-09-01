# M14-T1 交接：受控真实 Browser Adapter

- 日期：2026-09-01，Asia/Shanghai
- 当前任务：`M14-T1 / verified`
- 下一任务：`M14-T2 / planned`
- 验证基线：`4df0341`
- 验证记录：`V-20260901-004`
- 关联决策：`ADR-0040`
- 任务等级：A 类浏览器安全/审批公共合同 + C 类本地真实 Chromium
- 证据等级：fixture-only 离线 E3
- 在线模型/费用：未调用，费用 0
- 远程 Git：未 push

## 本次结果

现有 `BrowserAgent.run()` 离线 planner/simulator 原样保留。新 `run_with_driver()` 在执行边界重新
验证计划、检查 driver 合同并预消费全部副作用动作的精确单次审批；真实 DOM 动作必须带前次
页面 SHA-256 摘要，摘要也进入 approval arguments。

新增 Python `PlaywrightBrowserDriver` 和固定 Node bridge。Python 通过 M13 有界进程 runner、权限
受限临时请求/响应文件和最小环境 allowlist 调用前端已有 `@playwright/test`；不传 Provider Key，
不接受模型提供 argv、env、selector、脚本或路径。返回 URL/origin、标题/正文、元素 ID、PNG 和
动作结果均重新校验，正文、URL、typed value 和截图内容在 repr 中隐藏。

每次执行启动全新无持久化 Chromium context。Playwright route 拦截所有请求，只对
`BrowserFixtureSite` 精确登记的合成 HTTPS 文档返回 HTML；没有公网、个人 profile、Cookie、账号
或扩展。真实 Chromium 已完成 DOM 读取、输入、表单提交和 PNG screenshot，并对页面摘要不一致、
元素消失、跨域、弹窗/`window.open` 新窗口和下载返回稳定 fail-closed 错误。

## 修改文件

- `backend/app/advanced/browser_agent.py`
- `backend/app/advanced/browser_driver.py`
- `backend/app/advanced/__init__.py`
- `frontend/scripts/controlled-browser-driver.mjs`
- `backend/tests/test_browser_agent.py`
- `backend/tests/test_browser_driver.py`
- `backend/tests/browser_driver_integration.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/m14-browser-driver.md`
- `docs/stages/14-advanced-capstone.md`
- `docs/implementation-plan.md`
- `docs/continuity/decisions/ADR-0040-controlled-fixture-browser-driver.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- 本 handoff

依赖、锁文件、HTTP API、Vue 产品代码、数据库、部署、accepted 历史 ADR 和 `docs/progress.md` 未
修改。Node 保持 22.16.0，不需要 nvm 切换。

## 验证与失败尝试

- `node --check frontend/scripts/controlled-browser-driver.mjs` 退出 0。
- Browser Agent/Driver 沙箱内首轮：12 项先通过、3 项因用户 Temp ACL 在业务断言前 error；把
  临时目录改到仓库后同一 ACL 仍拒绝，产生的 3 个临时目录已按精确绝对路径清理。测试恢复为
  正常系统临时目录，同一 15 项在沙箱外全部通过。
- 真实 Chromium 首轮 3 项通过，11.483s；自审加固后最终复跑 3 项通过，6.723s。
- Advanced Harness、Browser Agent/Driver、Code Agent、Multimodal 相关回归 30 项通过、1 项既有
  Windows symlink 能力条件跳过。
- 最终 Browser Agent/Driver/Chromium 合并 18 项通过，6.608s。
- 最终 `git diff --check` 通过，仅有既有 LF/CRLF 提示；连续性检查通过 52 个稳定任务、165 个
  Markdown 文件，M14-T1 verified、M14-T2 planned、V/ADR/KI 和恢复入口一致。
- 没有运行完整 703+ offline、MCP、Vue build、Docker/PostgreSQL 或 online profile；当前原子任务
  没有依赖/锁文件/构建/HTTP/前端产品接口变化，定向安全回归和真实浏览器矩阵覆盖修改面。

## 已固定安全边界

- fresh context、fixture-only route、无公网、无个人登录态；
- DOM 动作必须匹配页面摘要和唯一可见稳定 element ID；
- click/type/submit 使用精确单次审批，input value 只以摘要进入审批/audit；
- 跨域、未知文档/资源、弹窗、新窗口和下载默认拒绝；
- 子进程 stdout/stderr 必须为空，进程树、wall time、输出和资源均有界；
- Python 只接受有界、结构化、签名正确的 PNG observation。

## 残余边界

`KI-010` 保持 open。M14-T1 的 approval 仍只绑定 action、origin、element、value digest 和 page
digest，没有绑定规范化完整 URL 或整个 plan digest；也没有 DNS 解析后的 IP 分类、private/
link-local/metadata 拒绝、每次 redirect 复核、DNS rebinding 模拟或上传下载许可策略。

因此当前 driver 不能改成接受任意公网 URL，也不能接用户 Chrome profile/真实登录态。本次 E3
不证明公网兼容、生产隔离、浏览器集群容量、Linux/macOS 或真实站点安全。

## 下一条原子动作

开始 M14-T2 前按 AGENTS 顺序恢复，读取本 handoff、`V-20260901-004`、`ADR-0040`、
`docs/m14-browser-driver.md`、实施计划 M14-T2 和 `KI-010`。先只读审查当前
`browser_approval_arguments()`、URL canonicalization、fixture route 与 redirect 行为，再冻结：

1. 规范化完整 URL + plan digest 的审批参数；
2. 可注入 DNS resolver、解析后 IP 分类和 DNS rebinding 测试；
3. 每次 redirect 与最终 URL 复核；
4. 上传/下载默认拒绝和显式策略边界。

不要提前进入 M14-T3 视觉，不读取 Key/用户 `.env`，不访问真实个人账号，不安装依赖、不修改
`docs/progress.md`、不 push。
