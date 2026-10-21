# M14-T6 多源证据审查合同 ADR 交接

## 当前状态

- 当前任务：`M14-T6 / in_progress`。
- 合同验证：`V-20261021-004`；验证基线：`fe3d7f7`。
- `ADR-0044` 已 accepted，场景版本固定为 `multisource-review-v1`。
- 本轮只有文档变化，没有修改运行时代码、依赖、默认 Container、API、Vue 或部署。
- 没有读取 Key、调用 Provider/公网、运行 Docker/Chromium 或 push。

## 已冻结的核心合同

1. 一个 owner-scoped durable Run 必须承载图片、规则、页面三源证据和发布结果，不允许用分离 Demo、
   Research API 或历史评测报告拼接。
2. 四个工具固定为 `inspect_image`、`search_review_policy`、`read_fixture_page`、`publish_review`；前三个
   必须真实调用现有 Vision/RAG/Browser 模块，不能返回预写常量冒充工具执行。
3. 工具只接收 server-owned 资源 ID 或有界业务字段；图片路径/URL、页面 URL/selector、owner、角色、
   Provider、发布目标和幂等键都不能由模型选择。
4. 三条 evidence 按 image/policy/page 形成 canonical bundle digest。发布必须绑定该 digest、revision、
   decision、principal、run、call 和 arguments digest，并同时使用持久 ToolExecution 与 publication
   store CAS。
5. 发布结果未知时固定 `tool_result_unknown`，禁止自动重放；只能按业务 key 对账权威 publication
   record。该合同不声称跨外部系统 exactly-once。
6. 默认视觉离线，Browser 只读 server-owned fixture；在线 Vision、公网 Browser、真实账单和生产
   容量不属于本纵切默认证据。

## 修改文件

- `docs/continuity/decisions/ADR-0044-multisource-review-portfolio-contract.md`
- `docs/implementation-plan.md`
- `docs/m14-production-portfolio-gap-audit.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/verification-log.md`
- 本 handoff

## 验证与失败尝试

- `scripts/check-continuity.ps1`：52 个稳定任务、185 个 Markdown 文件通过（新增本 handoff 前）。
- `git diff --check`：退出 0，只有既有 LF/CRLF 提示。
- 初次读取假定的 `backend/app/tools/base.py`、`backend/app/agents/multimodal_vision.py`、
  `backend/app/agents/browser.py` 以及检索不存在的 `backend/app/runtime`、`coordinator.py` 失败；随后
  使用仓库索引定位真实文件，不影响合同结论。
- 未运行 Python、Provider、Docker 或 Chromium 测试，因为本原子步骤没有代码或行为变化。

## 未验证范围

- 四工具、资源目录、作品集 registry/runtime、publication store 和新稳定失败码均尚未实现。
- 尚未证明四工具进入同一 durable Run，也未证明审批 resume、并发重放、result-unknown 对账或重启
  恢复。
- 未定义最终 HTTP/Vue 形状，未改变默认 Container，未把 Node/Chromium 加入部署镜像。
- `KI-034` 保持 open；旧 `capstone-architecture.md` 和 `capstone-demo-script.md` 仍需等真实纵切落地
  后重写。

## 下一条原子动作

按 `ADR-0044` 实现 `multisource-review-v1` 版本化领域类型、server-owned 图片/页面资源目录和独立四
工具 registry factory；先用定向测试证明：

- 工具参数 schema、角色与副作用标记准确；
- 图片/页面只能由 server-owned ID 解析，不能接受路径、URL、selector 或 bytes；
- 视觉观察保持 untrusted，RAG 最多 3 条 citation，Browser 只读 fixture；
- 发布参数必须绑定 revision/decision/evidence bundle，且没有 `reviewer` 或精确审批时 handler 不执行；
- 场景预算和公开结果不泄漏内容、Key、DSN、Cookie、原始幂等键或异常。

该代码步骤仍使用显式注入，不接默认 `ApplicationContainer`、HTTP、Vue 或部署；不安装依赖、不运行
Provider。后续同 Run 编排和持久 publication adapter 必须另以 ADR 验收矩阵完成，不能在 registry
存在后提前关闭 `KI-034`。
