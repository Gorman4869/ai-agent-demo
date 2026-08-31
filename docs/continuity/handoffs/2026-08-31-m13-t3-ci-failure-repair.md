# M13-T3 交接：首次远程 CI 失败的本地修复

- 日期：2026-08-31，Asia/Shanghai
- 当前任务：`M13-T3 / code_complete`
- 修复基线：`77492f0`
- 验证记录：`V-20260831-001`
- 关联决策：`ADR-0036`
- 远程运行：`https://github.com/Gorman4869/ai-agent-demo/actions/runs/33362304137`
- push：用户明确要求本轮暂不 push
- 在线模型/付费调用：未执行，费用 0

## 首次远程事实

GitHub Actions run `#1` 在提交 `77492f0` 上真实执行。MCP、frontend、E2E、Docker 和
online-policy 成功；offline 与 PostgreSQL 失败。

offline job 在干净 checkout 中只安装 MCP 依赖，没有生成被 Git 忽略的 `build/index.js`，因此
catalog 文件断言失败，两个 TypeScript STDIO 测试无法启动。PostgreSQL 的 120 项中只有
graceful-close 测试失败：Run 已完成，但 100ms 测试租约在共享 runner 时序下过期，关闭后仍有
一条租约记录。

## 本地修改

- `.github/workflows/verification.yml`：offline job 在 backend discovery 前构建 TypeScript MCP。
- `backend/tests/test_verification_entrypoint.py`：锁定 offline job 内安装、构建和执行的配置。
- `backend/tests/postgres_store_integration.py`：graceful-close 恢复默认租约时长；短 TTL 故障恢复
  测试保持不变。
- `docs/continuity/README.md`、`docs/implementation-plan.md`、`docs/continuity/status.md`、
  `docs/continuity/known-issues.md`、`docs/continuity/verification-log.md`：记录远程仓库、首次失败
  与本地修复边界。
- 本 handoff。

没有修改生产 Runtime、Store、租约实现、API、前端源码、依赖/锁文件、migration、Dockerfile、
Compose 或 `docs/progress.md`。

## 验证结果

- verification entrypoint：4 项通过。
- TypeScript MCP build：通过。
- MCP：沙箱内因子进程权限 8 项报错；同一命令沙箱外 11 项通过。
- PostgreSQL graceful-close：1 项通过。
- PostgreSQL/pgvector 完整 profile：120 项通过，1 passed、6 skipped、0 failed。
- offline 完整 profile：670 项通过、1 项既有 Windows symlink skip；Code Agent 与 `pip check`
  通过，1 passed、6 skipped、0 failed。

## 未验证范围

- 修复提交尚未 push，尚无新的 GitHub-hosted runner 结果。
- run `#1` 的失败必须保留，不能用本地成功覆盖。
- online-policy 只证明无授权 skip，不是 Provider E4。
- 没有执行 M13-T4 的镜像、容器健康、migration 或 Nginx SSE。

## 下一条原子动作

本地提交后停止。只有用户新的明确授权才能 push；获批后推送当前修复提交并观察七个 CI job。
若 required jobs 全部成功且 online-policy 明确 skip，追加新 verification、把 M13-T3 标记为
`verified` 并关闭 `KI-008`；在此之前不得进入 M13-T4。

## 交接时工作区

本 handoff 创建时，本轮代码、测试与连续性文件均为待提交改动，基线 HEAD 为 `77492f0`。
提交后的新 HEAD 由下一条远程复跑 verification 或 handoff 记录。
