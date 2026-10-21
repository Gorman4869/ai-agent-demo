# M14-T6 生产级作品集缺口审计

## 审计目标与边界

本审计以实际代码和可复现验证为真相源，盘点 M12–M14 是否已经满足 M14-T6 的九类交付物：
真实业务场景、架构图、在线或可复现部署、演示脚本、评测报告、成本、威胁模型、故障复盘和迁移
说明，并单独核对“至少 3 个真实工具，其中至少 1 个有副作用且具备审批和幂等”。

本轮只读代码和既有证据，不运行 Provider、Docker 或浏览器，不读取 Key，不安装依赖，也不把历史
验证冒充本轮新证据。评级含义：

- `complete`：已有当前实现与可复现证据，可直接进入最终作品集整合。
- `partial`：已有可复用基础，但缺 M14 业务纵切或材料已经漂移。
- `missing`：验收要求尚无对应实现或证据。

## 结论摘要

M14-T6 不能直接进入最终文档润色。当前最大缺口不是单个 Browser 或 Vision adapter，而是缺少一个
真正进入 durable Run 的“多源证据审查”业务纵切：图片观察、知识检索、受控网页读取和发布动作
还没有作为同一场景的真实工具协作，前端、部署和演示也没有展示这条链。

已有材料中，固定评测可以直接复用；部署、成本、威胁、故障和迁移材料可以作为底座，但必须针对
M14 场景重新整合。旧 `capstone-architecture.md` 与 `capstone-demo-script.md` 仍描述 M0–M7/M6
时期的进程内现状，不能作为当前 M12–M14 实现的最终答辩证据。

## 交付缺口矩阵

| 验收项 | 评级 | 已有证据 | 缺口与不得扩张的结论 |
| --- | --- | --- | --- |
| 真实业务场景与目标用户 | partial | `stages/14-advanced-capstone.md` 定义“多源证据审查”场景 | 只有课程叙述；Backend API、Vue 和 durable Run 均未接入 Vision/Browser，不能称为可运行作品集 |
| 当前架构图 | partial | `capstone-architecture.md` 有 Mermaid、数据责任和威胁模型；M12–M14 ADR 完整 | 图仍称 Run/审批/记忆为进程内，未体现 PostgreSQL durable Run、Nginx、pgvector、Browser/Vision 与执行档位，属于稳定文档漂移 |
| 在线或可复现部署 | partial | `deploy/compose.deployment.yaml`、`m13-deployment.md` 与 `V-20260831-003` 已证明单机 PostgreSQL/Nginx/durable SSE/restart | backend 镜像只有 Python，没有 Node/Chromium；部署固定 manual/mock/offline，未包含 M14 多源审查链；不能称 M14 作品集已部署 |
| 演示视频脚本 | partial | `capstone-demo-script.md` 有 12–15 分钟流程和失败路径 | 内容仍引用 M6 与旧架构，没有 M14-T4/T5、同 Run 多源证据、当前部署命令或 20 分钟答辩结构；仓库也没有真实视频产物 |
| 固定评测报告 | complete | `advanced-agent-eval-v1`、`m14-advanced-agent-evaluation.md`、`V-20261021-001/002` | 7 个案例和 offline/Playwright 对照可复用；只证明 fixture E3，不等同业务纵切评测或生产容量 |
| Token 与成本说明 | partial | durable usage ledger、M13 observability、M14-T4 单次 MiniMax `479/43/522` usage、M14-T5 unknown/null | 缺作品集场景的合并成本表、价格来源版本和业务量估算；M Plan usage 不能换算 PAYG 现金账单，unknown 不能写成 0 |
| 威胁模型与残余风险 | partial | `capstone-architecture.md`、ADR-0040–0043、`known-issues.md` | 缺针对“图片 + RAG + 网页 + 发布”的数据流威胁表和信任边界；现有 PNG guard 不是完整 decoder/重编码/扫描器 |
| 故障复盘与恢复过程 | partial | `m13-incident-handbook.md`、`m13-load-fault.md`、`V-20260901-001` | 有通用故障手册和真实数据库演练，但没有 M14 业务纵切的注入故障、时间线、根因、修复和复验记录 |
| 迁移说明 | partial | `m12-api-migration.md` 固定 legacy → durable 迁移；架构文档有演进路线 | 缺把当前研究助手迁移成多源审查助手的接口、数据、工具、权限、部署和回滚清单 |
| 至少 3 个真实工具 + 1 个审批幂等副作用 | missing | `create_default_registry()` 有 `add_numbers`、`convert_temperature` 和模拟 `publish_report`；Vision、RAG、Browser 各自有真实领域模块 | 三个内置工具是教学/模拟工具，不能满足业务作品集；高级模块没有作为同一 durable Run 的工具，模拟发布也不能冒充真实业务副作用闭环 |

## 可直接复用的工程资产

| 资产 | 复用方式 | 证据边界 |
| --- | --- | --- |
| durable Run/Event/SSE/审批 | 作为作品集唯一运行与恢复主链 | 不回退到 legacy Run，不用第二次 `/api/research` 覆盖结果 |
| PostgreSQL ToolExecution 与幂等合同 | 承载发布动作的审批、一次消费和结果仲裁 | 外部副作用仍需明确业务幂等键与 result-unknown 处理 |
| `MultimodalVisionAgent` | 提供 PNG guard 与不可信结构化观察 | 默认离线；真实调用只能引用 M14-T4 已完成的独立单次 E4 |
| `PlaywrightBrowserDriver` | 读取 server-owned fixture 网页证据 | 不开放公网、个人 profile、下载或任意 selector |
| Knowledge/Context/RAG | 提供规则证据和 citation | 部署 pgvector seed 尚未接入默认 Context，必须如实选择内存或显式接线 |
| M14-T5 evaluator | 作为安全/失败回归基线 | 不替代作品集业务场景的端到端验收 |
| M13 deployment/load/fault | 复用单机部署、健康、SSE、重启与清理协议 | 若镜像加入 Chromium 或新运行时，必须重新做对应部署验证 |

## 建议的 M14-T6 纵切顺序

### 第一纵切：冻结作品集业务与工具合同

新增一份 accepted ADR 和版本化场景合同，明确目标用户、输入/输出、四个服务端工具及信任边界：

1. `inspect_image`：只读，返回不可信结构化视觉观察；默认离线。
2. `search_review_policy`：只读，返回带来源的规则证据。
3. `read_fixture_page`：只读，只访问受控 Browser fixture。
4. `publish_review`：有副作用，必须绑定服务端主体、审批、业务幂等键和持久 ToolExecution。

本纵切只冻结领域协议、事件/结果形状、失败码、预算和验收测试，不接公网、不改默认 Container，避免
在接口未定时同时改 API、Vue、部署和文档。

### 第二纵切：离线同 Run 真实调用链

让四个工具实际进入一个显式注入的 durable Runtime；覆盖正常审查、缺审批、审批重放、视觉注入、
RAG 无证据、页面漂移和发布结果未知。只有代码真实调用已有 Vision/RAG/Browser/ToolExecution 模块，
才算“至少 3 个真实工具”达标。

### 第三纵切：API、Vue 与可复现部署

把作品集场景暴露为独立、版本化 API/UI 入口，保持 legacy 隔离；随后评估 Chromium 是否需要进入
部署镜像。若引入 Node/Chromium 或新容器，必须单独取得依赖/镜像操作授权并重跑部署健康、SSE、
重启和精确清理。

### 第四纵切：作品集材料与演练

更新当前架构图、20 分钟演示脚本、成本表、M14 威胁模型、一次真实故障复盘和研究助手迁移说明；
所有数字引用 verification，无法验证的在线/人工/账单能力保留 unknown 或未验证。

## 下一条原子动作

执行第一纵切中的“设计与合同”部分：新增 M14-T6 ADR，冻结多源证据审查场景、四工具边界、同 Run
事件/结果、审批幂等和离线验收矩阵。该动作不安装依赖、不调用 Provider、不改 Vue/部署，也不在
合同确定前接入默认 `ApplicationContainer`。
