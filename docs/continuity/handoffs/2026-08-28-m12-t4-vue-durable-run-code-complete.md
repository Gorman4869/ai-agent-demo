# M12-T4 交接：Vue durable Run 状态机与刷新恢复

- 日期：2026-08-28，Asia/Shanghai
- 当前任务：`M12-T4 / code_complete`
- 下一任务：`M12-T5 / planned`
- 验证基线：`9ef3eb6`
- 验证记录：`V-20260828-011`
- 关联决策：`ADR-0029`、`ADR-0030`、`ADR-0031`、`ADR-0032`
- 任务等级：A 类（capability、状态恢复与公开流协议）
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置，未 push

## 本次结果

Vue 已删除 `createSession -> legacy streamRun -> research` 双链，只调用 durable
create/snapshot/SSE/cancel/approval。最终 answer、citations、usage 与 error 来自同一
Run snapshot，SSE 负责已持久化的实时进度；页面显示 Run ID、最后 sequence、工具
时间线、待审批操作、引用、token usage 和 unknown cost。

`AgentEvent` 是已评审事件的判别联合。parser 校验 SSE ID 与 payload sequence、Run
envelope、关键字段和 usage；状态机只应用当前 Run 的严格递增 sequence，重复帧不重复
生效，缺口停止应用。有界重连每次先查 snapshot，再从最后 sequence 续传；组件卸载
仅 abort 订阅，用户停止才调用 durable cancel。

匿名 capability、Run/Session ID、sequence、服务端 status 和最小审批标识保存到当前
标签页的版本化 `sessionStorage`。没有使用 localStorage、URL 或 UI 展示 capability；
该教学取舍仍受同源 XSS 影响，生产认证留给 M13。

## 修改文件

- `frontend/src/types/agent.ts`
- `frontend/src/services/agentApi.ts`
- `frontend/src/composables/useAgentDesk.ts`
- `frontend/src/components/RunTimeline.vue`
- `frontend/src/App.vue`
- `frontend/src/styles/main.css`
- `docs/项目编码规约 v1.0.md`
- `docs/continuity/decisions/ADR-0032-vue-durable-run-recovery-state.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- 本 handoff

## 验证与失败尝试

- `npm.cmd run build` 最终通过：`vue-tsc -b` 与 Vite production build 均成功，19
  modules transformed。
- durable API/SSE/snapshot 后端直接回归 19 项通过。
- 首次 build 发现 `run.failed | run.cancelled` 共用返回分支不能满足判别联合的字面量
  收窄；已拆为两个分支并重跑通过。
- legacy session/stream、独立 Research API 和 localStorage 的前端源码检查均无命中；
  `git diff --check` 通过。
- 未执行 M12-T5 单元测试或真实浏览器 E2E，所以本任务保持 `code_complete`。

## 下一条原子动作

M12-T5 开始前先向用户列出并取得新测试依赖与浏览器下载许可。建议最小集合：

- `vitest`：SSE parser 和状态机测试运行器；
- `@vue/test-utils` + `happy-dom`：挂载 composable 页面壳并控制 sessionStorage/fetch；
- `@playwright/test` 及 Chromium：真实浏览器会话、断线续传、刷新恢复和审批 E2E。

获批后先做 parser/状态机单测，再做真实浏览器 E2E；不得把静态 build 记作刷新恢复
通过，也不要提前进入 M12-T6、Nginx 或生产认证。
