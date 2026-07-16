# AI Agent Demo 协作与恢复规则

本文件适用于 `ai-agent-demo` 整个仓库。任何新会话、新模型或协作者开始工作前都必须遵守。

## 1. 强制阅读顺序

1. `docs/continuity/README.md`
2. `docs/continuity/status.md`
3. `docs/implementation-plan.md` 中当前任务及其依赖
4. 当前任务关联的 `docs/continuity/decisions/ADR-*.md`
5. `docs/continuity/handoffs/` 中最新交接文件
6. `docs/continuity/verification-log.md` 中最近的关联验证
7. 后端任务读取 `BACKEND_CODING_STANDARDS.md`；前端任务读取 `docs/项目编码规约 v1.0.md`

不得只根据聊天记录或旧说明文档推断当前状态。

## 2. 真相源优先级

发生冲突时按以下顺序判断：

```text
实际代码和可复现测试证据
  > docs/continuity/verification-log.md
  > docs/continuity/status.md
  > docs/implementation-plan.md
  > ADR 与阶段文档
  > README 和普通说明
```

发现冲突时先记录到 `known-issues.md`，不得静默选择方便的一方。

## 3. 任务与状态规则

- 只处理 `status.md` 中标记的当前任务，除非用户明确改变优先级。
- 任务 ID 一经发布不得重编号；取消或替换时使用 `superseded`。
- 合法状态：`planned`、`in_progress`、`blocked`、`code_complete`、`verified`、`accepted`、`superseded`。
- `code_complete` 不等于完成；代码、测试、文档和验证证据全部满足后才能写 `verified`。
- 不得把 M0–M7 旧文档中的完成描述当成当前真实验收状态。

## 4. 修改前检查

1. 运行 `git status --short`，区分现有改动和本任务改动。
2. 阅读目标文件和相邻模块，遵循现有 dataclass、Protocol、显式 SQL、FastAPI、Vue 3、TypeScript 与 Composition API 风格。
3. 检查任务的依赖、验收命令、关联 ADR 和已知问题。
4. 如果需要新依赖，先列出用途、版本和替代方案并取得用户许可。
5. 如果需要在线模型、远程服务、付费调用或远程 Git 操作，先取得显式许可。

## 5. 实施边界

- 默认路径必须保持离线、确定性、无 API Key 可测试。
- 真实 OpenAI 调用只有同时具备显式在线开关、`OPENAI_API_KEY` 和用户授权时才运行。
- 密钥、Token、密码和真实个人数据不得写入源码、测试固定值、文档、日志或 Git。
- 不删除现有手写 Loop、Mock、安全实验或兼容 API，除非计划任务明确要求且迁移验收已通过。
- 不引入微服务、Redis、消息队列、Kubernetes、Pinia 或新 UI 库，除非新增 ADR 且用户批准。
- 有副作用的工具没有持久幂等键时不得自动重试。
- 不执行 `git push`、不配置远程仓库，直到用户提供地址并明确授权。

## 6. 验证与状态更新

每次结束前严格按以下顺序：

1. 执行当前任务要求的最小验证和相关回归。
2. 先向 `verification-log.md` 追加成功、失败、警告、跳过和未验证范围。
3. 有架构变化时新增 ADR；已接受 ADR 不直接改写结论。
4. 更新 `known-issues.md` 的状态和证据。
5. 更新 `status.md`，引用验证 ID，并记录验证目标 commit 或验证开始时的 base HEAD；不要要求文档预知尚未创建的提交 ID。
6. 创建新的 handoff，写明修改文件、命令、失败尝试、未提交改动和下一条原子动作。
7. 最后检查 `git status --short`，只提交本任务相关文件；提交后的新 HEAD 在下一条 verification 或 handoff 中记录。

没有验证记录时不得宣称任务完成。

## 7. 文档与学习交付

M8–M14 每个里程碑必须同时包含：

- 可运行代码和自动化测试
- 精确命令和实际验证证据
- 跟练步骤、真实工作映射和常见错误
- 概念题、实操题、场景题
- 一页速查表和费曼复述任务
- 与 30 项大纲的映射

学习者个人勾选只写 `docs/progress.md`；工程实施状态只写 `docs/continuity/status.md`。
