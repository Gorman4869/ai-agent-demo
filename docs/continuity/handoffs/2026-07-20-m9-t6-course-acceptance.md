# M9-T6 交接：MCP Client 与 Skill 课程验收

- 日期：2026-07-20，Asia/Shanghai
- 完成任务：`M9-T6`
- 完成状态：`verified`
- 下一任务：`M10-T1 / planned`
- 验证基线 HEAD：`19b5596`
- M9-T5 实现提交：`a6ff518`
- M9-T6 课程提交：`fdeb9b5`
- 验证记录：`V-20260720-009`、`V-20260720-010`
- 关联决策：`ADR-0009`、`ADR-0010`
- 分支：`main`
- 任务等级：B 类里程碑课程验收，时间盒 60-90 分钟
- 新增或安装依赖：无
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 把 M9-T1 至 M9-T5 串成四次、共 8-12 小时的完整跟练，逐次给出目标、命令、产物、工作映射、通关标准和常见边界。
2. 增加由 Python Client 从服务端目录真实拉起 TypeScript Server，并分别完成 initialize/list_tools 与 call_tool 的独立训练路径；明确不能用 import 或单独启动文件代替协议证据。
3. 补齐 MCP、Function Calling 与 Skill 的职责、执行所有者、信任数据、安全控制和不负责范围对照。
4. 增加 roots 专节，明确本仓库当前未协商 roots，且 roots 不能替代 OS 权限、容器/沙箱、服务端 allowlist、canonical path 或 symlink 校验。
5. 新增 M9 一页速查表，包含协议/Skill 双主链、选择规则、信任边界、E1-E4、稳定错误、精确命令和自检问题。
6. 增加 5 道概念题、4 道实操题、4 道工作场景题、100 分评分标准、80 分通关线和安全红线。
7. 补齐故障注入、固定排查顺序、费曼复述、最终验收清单，以及 30 项大纲 02/06/07/08/13/24 的证据映射；全局主题 07/08 已引用 M9-T6。
8. 没有修改 Runtime、MCP/Skill 代码、测试、依赖或公共契约，也没有进入 M10。

## 本次修改文件

- `docs/stages/09-mcp-client-skills.md`
- `docs/m9-mcp-skill-cheat-sheet.md`
- `docs/syllabus-map.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- `docs/continuity/handoffs/2026-07-20-m9-t6-course-acceptance.md`

## 实际验证

- handoff 恢复：10 项 SkillContext、固定评测 2/2 和 52 个稳定任务/60 个 Markdown 连续性检查通过，代码与记录一致。
- M9 聚焦：TypeScript build 通过；生命周期、工具适配、TypeScript E2E、Skill Catalog 和 SkillContext 共 40 项全部通过，无 ResourceWarning。
- 固定评测：LangGraph 离线 fixture 再次 2/2；触发上下文 3153 字节/启发式 789 Token，不触发为 0，Provider usage 不可用、费用 `null`。
- 课程检查：对照、roots、四次跟练、三类题库、速查、费曼、30 项映射和最终清单均被静态检查命中；相对链接和大纲映射通过连续性检查。
- 全量首轮：后端 294 项中 293 项通过、1 项既有 Windows symlink 能力跳过；Code Agent Demo 和 `pip check` 通过，Vue 因沙箱 `EPERM` 无法写 `tsbuildinfo`，脚本退出 1。
- 全量授权重跑：同一完整脚本在沙箱外退出 0；后端结果一致，Vue、MCP TypeScript 与 Compose 配置门全部通过。
- 内容与 diff：本 handoff 落盘后 52 个稳定任务、62 个 Markdown 文件通过；tracked 文件无空白错误，仅有既有 LF/CRLF 转换提示，占位符和安装指令扫描无匹配。

## 失败尝试与漂移修复

- ADR-0010 首次使用了摘要中的猜测文件名，列目录后按实际文件名读取；ADR-0009 首次使用默认编码输出失真，改用 UTF-8 后正常。两次读取问题均未修改文件。
- `status.md` 的未验证列表保留一条 M9-T4 时期“尚未注入 Runtime”的旧句，与 M9-T5 代码和 verification 冲突；先在 `V-20260720-009` 登记，再按真实证据删除。
- 全量首轮因沙箱写 Vue build info 失败；没有改代码、依赖或系统策略，经批准在沙箱外重跑同一脚本通过。

## 警告与未验证范围

- 全量仍跳过 1 项既有 Code Agent Windows symlink 能力测试；M9 Skill 的 symlink 拒绝是受控分支证据，不是当前 OS 真实 symlink 实测。
- Starlette/httpx 弃用提示、预期 notifier warning 和 Windows asyncio debug 诊断不影响退出码；没有按提示安装或升级依赖。
- 本地 Python/Node STDIO 最高为 E3；没有远程 transport、跨平台、重连、调用幂等、副作用恢复或生产容量证据。
- Compose 只完成配置展开，没有启动 Docker Engine、镜像或容器。
- roots 当前未实现；课程只要求解释它不是 OS 安全边界。
- Skill 评测使用确定性离线 fixture，不是 Provider 指令遵循、tokenizer、usage 或账单证据；`KI-018` 保持 open。
- 学习者个人题库、速查和费曼完成情况只写 `docs/progress.md`，工程验收不会代填。

## 未提交改动

M9-T6 阶段文档、速查表、静态映射和首轮连续性记录已提交为 `fdeb9b5`。提交后只修改本 handoff、status 与 verification log 以固定课程提交和恢复证据；这些记录由后续本地文档提交闭环，工作区没有任务外改动。

## 下一条原子动作

开始 `M10-T1` 前，只读审阅实施计划 M10-T1、阶段 10、现有 `LangGraphRuntime`、Runtime/Coordinator 契约和已安装 LangGraph checkpointer 公开 API。先固定 graph state、thread ID、状态版本、迁移边界及“共享内存只在进程内持久”的验收设计；不要提前实现 M10-T2 interrupt/resume，也不要把内存 checkpointer 描述成进程重启持久化。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
npm.cmd run build --prefix mcp-servers/knowledge-server
.\.venv\Scripts\python.exe -X utf8 -B -W always::ResourceWarning -m unittest backend.tests.test_mcp_client_lifecycle backend.tests.test_mcp_tool_adapter backend.tests.test_mcp_client_e2e backend.tests.test_skill_catalog backend.tests.test_skill_context -q
.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.skill_context
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 M9 聚焦 40 项通过，固定评测 2/2 且为 3153 字节/启发式 789 Token，连续性为 52 个稳定任务和 62 个 Markdown 文件。若一致，不要重做 M9，直接进入 M10-T1 只读设计核对。没有用户新的单次授权，不得读取 Key 或执行真实模型。
