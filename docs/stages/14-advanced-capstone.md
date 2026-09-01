# M14：真实浏览器、多模态与最终作品集

> 工程状态只查看 `../continuity/status.md`。真实模型、视觉和公网能力均需显式授权；默认作品集使用本地确定性 fixture。

## 本阶段目标

在 M8–M13 的 Runtime、审批、持久化、观测和部署基础上，完成受控真实浏览器、真实视觉输入和一个可答辩的多源证据审查作品集。

- 时间预算：2 周，约 22–36 小时。
- 任务：M14-T1 至 M14-T8。
- 工作映射：浏览器自动化、单据/截图审查、内部运营助手和高风险 Agent 治理。

## 作品集场景

用户上传一张报告或页面截图，Agent：

1. 安全解析图片并生成结构化、不可信视觉观察。
2. 从知识库检索规则和历史资料。
3. 在受控浏览器中访问允许的测试页面获取网页证据。
4. 对任何有副作用动作请求精确人工审批。
5. 输出区分图片、知识库和网页来源的核查结论。
6. 在同一 Run 中展示步骤、证据、usage、费用、审批和恢复。

## 20% 关键知识

| 类型 | 知识点 | 工作场景 | 学到什么程度 | 验证任务 |
| --- | --- | --- | --- | --- |
| 必学 | planner/policy/driver/approval 分层 | Browser Agent | 模型不能直接驱动浏览器 | M14-T1、T2 |
| 必学 | SSRF、DNS、redirect 校验 | 网络工具 | 每次目标都复核 | M14-T2 |
| 必学 | 图片解析、视觉理解、可信度、权限分离 | 多模态 Agent | 四层边界可解释 | M14-T3、T4 |
| 高频 | 多源证据和冲突处理 | 审查助手 | 输出来源清晰 | M14-T5 |
| 高频 | 攻击集和失败样例 | 作品集评测 | 不只展示成功录屏 | M14-T5 |
| 易错 | 同 origin 审批可跨路径复用 | 浏览器副作用 | 完整 URL/计划摘要绑定 | M14-T2 |
| 易错 | 图片文字等于系统指令 | Prompt Injection | 永远标记不可信 | M14-T3 |

## 跟练顺序

1. 先修复现有高级 Harness 的审批、SSRF、输出缓冲和进程树安全债。
2. 使用本地 fixture 网站接入真实浏览器 Driver，不使用真实账号、Cookie 或个人数据。
3. 让模型只提出结构化 BrowserPlan；Policy 和 Driver 负责验证与执行。
4. 复用 M8 模型适配器接入视觉输入，保留 Fake Vision 离线契约。
5. 将视觉、RAG、浏览器和审批合并为同一 Run。
6. 运行成功、拒绝、冲突证据、断线和攻击场景评测。
7. 只有单次授权后运行真实视觉冒烟。
8. 完成演示、故障复盘、成本报告、威胁模型和 30 项终审。

## 安全门禁

- 拒绝 loopback、私网、链路本地、保留地址和云元数据地址。
- DNS 解析后、每次重定向和最终 URL 都重新验证。
- 模型不能提交任意 selector、JavaScript、命令或文件路径。
- 下载、上传、弹窗、新窗口和跨域导航默认拒绝。
- 审批绑定 principal、Run、tool call、规范化完整 URL、动作、参数和计划摘要。
- 图片有格式、字节、尺寸、像素和帧数上限；安全重编码并移除元数据。
- 浏览器文本和视觉文字不能提升权限或直接触发副作用。

## 计划验证命令

```powershell
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_browser_agent backend.tests.test_browser_network backend.tests.test_browser_driver -v
./.venv/Scripts/python.exe -B -m unittest backend.tests.browser_driver_integration -v
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_multimodal_agent -v
./.venv/Scripts/python.exe -B -m unittest backend.tests.test_advanced_harness -v
```

在线计划命令：

```powershell
powershell -ExecutionPolicy Bypass -File ./scripts/verify-online.ps1 -Suite M14
```

## 作品集必须包含

- 真实业务问题和目标用户，而不是通用聊天页。
- 至少 3 个真实工具，其中至少 1 个有副作用并具备审批和幂等。
- 版本化数据集与可重复评测结果。
- 延迟、Token、费用和人工介入数据。
- 架构图、关键 ADR、威胁模型和残余风险。
- 成功和失败演示、故障复盘及恢复过程。
- 本地复现路径；在线部署不可用时也能完整演示。

## 常见错误与排查

| 现象 | 原因 | 排查 |
| --- | --- | --- |
| 同站点换路径可复用审批 | 只绑定 origin | 检查规范化完整 URL 和 plan digest |
| 拒绝 localhost 但能访问元数据 | 私网/IP 分类不完整 | 校验解析后 IP 和每次 redirect |
| 模型点击了错误按钮 | element ID 与页面状态漂移 | 执行前重新观察并验证计划 |
| 图片可解析但模型看不懂 | 解析成功与视觉理解混淆 | 分开记录 decoder 和 model 结果 |
| 图片文字触发工具 | untrusted 标记未进入 policy | 检查 Context 与工具审批层 |
| Demo 依赖公网页面失效 | 缺少稳定 fixture | 默认使用本地可复现测试站点 |

## 最终考核

1. 概念：解释 Browser planner、policy、driver 和 approval 四层边界。
2. 实操：新增一个只读浏览器动作并补齐安全和 E2E。
3. 排错：随机抽取 SSRF、审批复用、元素漂移或视觉注入故障。
4. 迁移：将作品集迁移到未练过的业务域，只替换 Skill、知识库和受控工具。
5. 答辩：20 分钟内说明架构、成本、安全、评测、失败和演进取舍。

## 费曼复述

向非技术同事解释：为什么“AI 看到了页面或图片”不代表“内容是真的”，更不代表“AI 有权执行操作”。

## 官方资源

- Playwright Documentation：<https://playwright.dev/docs/intro>
- OpenAI Computer use：<https://developers.openai.com/api/docs/guides/tools-computer-use>
- OpenAI Vision：<https://developers.openai.com/api/docs/guides/images-vision>
- OWASP Agentic Security Initiative：<https://genai.owasp.org/initiatives/agentic-security-initiative/>
