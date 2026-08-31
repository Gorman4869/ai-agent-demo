# 实施连续性与恢复入口

这是 AI Agent Demo 在断网、模型切换、上下文压缩或新会话接手后的唯一恢复入口。

## 当前计划基线

- 计划版本：2.0
- 已确认设计：`docs/superpowers/specs/2026-07-16-ai-agent-transition-completion-design.md`
- 实施范围：保留 M0–M7，新增 C0 与 M8–M14
- Git 分支：`main`
- 远程仓库：`https://github.com/Gorman4869/ai-agent-demo.git`
- 在线模型：默认关闭，付费验证必须显式授权
- 课程交付模式：课程优先、里程碑验收

## 文档职责

| 文件 | 唯一职责 | 更新方式 |
| --- | --- | --- |
| `docs/implementation-plan.md` | 稳定任务、依赖、产物和验收契约 | 任务发布后不重编号 |
| `docs/continuity/status.md` | 当前任务、状态、阻塞和下一动作 | 每次工作结束更新 |
| `docs/continuity/course-delivery-playbook.md` | 课程质量底线、任务分级、时间盒与里程碑验收规则 | 仅在用户确认交付协议变更后更新 |
| `docs/continuity/verification-log.md` | 实际命令与结果证据 | 只追加，不改写历史结果 |
| `docs/continuity/known-issues.md` | 稳定编号的缺口和风险 | 状态变化时更新 |
| `docs/continuity/decisions/ADR-*.md` | 已接受架构决策及取舍 | 新 ADR 取代旧 ADR |
| `docs/continuity/handoffs/*.md` | 某次工作的不可变交接快照 | 每次中断或结束新增 |
| `docs/progress.md` | 学习者个人训练和复盘 | 学习者完成训练后填写 |

状态值不得复制到 README、阶段文档或大纲映射中，避免多处漂移。

## 新会话恢复流程

1. 在仓库根目录运行 `git status --short` 和 `git log -3 --oneline`。
2. 阅读本文件与 `status.md`。
3. 阅读 `course-delivery-playbook.md`，确定任务等级、时间盒和本轮验证深度。
4. 在 `implementation-plan.md` 定位当前任务 ID、依赖和验收条件。
5. 阅读当前任务关联 ADR 和最新 handoff。
6. 阅读最近的关联 verification ID。
7. 检查实际文件是否与 handoff 描述一致。
8. 重跑 handoff 指定的最小验证命令。
9. 只执行 handoff 的下一条原子动作。

如果最小验证结果与记录不同，停止扩展实现，先登记 known issue 并定位漂移原因。

## 状态定义

| 状态 | 含义 |
| --- | --- |
| `planned` | 已进入稳定计划，但尚未开始 |
| `in_progress` | 当前正在修改或验证 |
| `blocked` | 有明确外部阻塞，且文档记录了解除条件 |
| `code_complete` | 代码已落盘，但测试、文档或环境验证仍未全部完成 |
| `verified` | 代码、自动测试、跟练文档和验证记录全部满足 |
| `accepted` | 用户已确认交付结果 |
| `superseded` | 被新任务或 ADR 明确取代，不删除历史 |

## 验证记录格式

每条验证使用稳定 ID `V-YYYYMMDD-NNN`，至少记录：

- 任务 ID、日期时间与时区
- 计划版本，以及验证目标 commit、worktree 或验证开始时的 base HEAD
- Python、Node、Docker 等相关环境
- offline/online 与是否产生费用
- 精确命令和退出码
- 通过数、失败数、跳过与警告
- 未验证范围和关联 known issue

## 工作结束更新顺序

```text
运行验证
  -> 追加 verification-log
  -> 新增或引用 ADR
  -> 更新 known-issues
  -> 更新 status
  -> 新建 handoff
  -> 检查并提交 Git
```

## 冲突处理

```text
实际代码和可复现测试证据
  > verification-log
  > status
  > implementation-plan
  > ADR 与阶段文档
  > README 和普通说明
```

任何人修复文档漂移时，都应保留旧验证记录，通过新记录说明变化，而不是改写历史。
