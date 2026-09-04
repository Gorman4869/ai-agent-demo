# M14-T3 视觉输入适配与不可信观察交接

- 日期：2026-09-02，Asia/Shanghai
- 当前分支：`main`
- 验证基线：`e165646`
- 本轮提交：尚未创建；本 handoff 覆盖当前 M14-T3 worktree，下一恢复记录补记新 HEAD
- 当前状态：`M14-T3 / verified`
- 下一任务：`M14-T4 / planned`
- 验证记录：`V-20260902-001`
- 关联决策：`ADR-0042`
- 远程状态：未 push；`main` 在本轮前已领先 `origin/main` 10 个提交

## 本轮交付

M14-T3 在不执行在线 Provider 的前提下完成真实视觉 adapter：

1. 复用现有 `Settings` provider/model/key/timeout/output token 配置，并增加调用点单次
   `online_authorized` 门；缺任一门都选择 `OfflineVisionModel`，client 不创建。
2. `MultimodalVisionAgent` 先执行现有 PNG/MIME/字节/尺寸/像素校验，再生成固定
   `VisionRequest`；坏 MIME、损坏 IHDR 和超限图片在模型前拒绝。
3. `OpenAIVisionModel` 通过 `responses.parse` 发送 Base64 `input_image`，固定 `detail=low`、
   `store=false`、无 tools、显式 model/timeout/output tokens 和 `max_retries=0`。
4. `StructuredVisionObservation` 把 summary、visible text、uncertainties 全部标记为
   `untrusted_visual_data` 和 `can_authorize_actions=False`；repr/event 不记录原文。
5. timeout、无效结构、观察超限和 Provider 故障返回稳定 `RunFailure + png_metadata` fallback，
   不伪造视觉结论/usage；取消继续传播。
6. 真实 `openai==2.45.0` 经 `offline.invalid` MockTransport 走完 `/v1/responses`、Pydantic 结构化
   解析和 usage 映射。该证据为 E2/E3，不是线上 E4。

## 修改文件

- `backend/app/advanced/multimodal.py`
- `backend/app/advanced/__init__.py`
- `backend/tests/test_multimodal_agent.py`
- `docs/m14-vision-input.md`
- `docs/implementation-plan.md`
- `docs/continuity/decisions/ADR-0042-vision-input-and-untrusted-observation.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/known-issues.md`
- `docs/continuity/status.md`
- 本 handoff

`docs/progress.md` 未修改。没有依赖、锁文件、Settings schema、Container、HTTP API、数据库、Vue
产品代码或部署变更。

## 验证快照

- Multimodal 最终 13 项通过。
- Multimodal + Advanced Harness + Settings + OpenAI Runtime 合并 74 项通过。
- 真实 OpenAI SDK + 本地 MockTransport 单项通过；没有网络或真实 Key。
- 完整默认离线门最终通过：backend 729 项（1 项既有 Windows symlink 条件 skip）、Code Agent
  Demo、`pip check`、MCP TypeScript build/STDIO 11 项、Vue 12 项和 production build；汇总
  3 passed、4 skipped、0 failed。
- 连续性检查 52 个稳定任务、171 个 Markdown 文件通过；`git diff --check` 退出 0。

失败事实保留：

- 首轮定向 fixture 把 Run timeout 设为 1s，却保留默认 2s model retry max delay，Settings 正确
  fail closed；fixture 改为 3s 后通过，未改生产合同。
- 完整门受限沙箱首轮因 Windows Temp ACL 出现 59 个 errors 和 2 个派生 MCP failures。
- 沙箱外首次只剩 1 个 TypeScript MCP `startup_timeout`；该 MCP 套件随后 4/4 通过，第二次完整门
  全绿。没有为抖动修改 timeout 或 MCP 代码。

## 不可越界的结论

- 没有执行真实 Provider、读取 Key/`.env`、发送真实图片或产生费用。
- 当前只接受 PNG；guard 不是完整 decoder、安全重编码器、metadata 剥离器或恶意图片扫描器。
- `detail=low` 只代表 server-owned 成本边界，不证明 OCR/细节质量。
- 视觉内容只能作为数据。后续综合 Run 即使使用这些字段，角色、工具 Schema、审批和副作用策略仍
  必须来自应用控制面。
- M14-T4 的在线证据必须重新取得用户单次授权，不能从旧 DashScope/OpenAI 授权或本任务测试推断。

## 下一条原子动作

开始 M14-T4 前按 AGENTS 顺序恢复，读取本 handoff、`V-20260902-001`、`ADR-0042`、
`docs/m14-vision-input.md`、实施计划 M14-T4、`backend/app/online_smoke.py` 和当前 multimodal tests。
先离线冻结：

1. 独立 M14 视觉 smoke CLI 的 `--authorized`/双重配置门；
2. server-owned 小型无个人数据 PNG fixture、单请求/零重试/timeout/Token/费用上限；
3. 接受条件：真实 structured observation、usage、费用来源和 Prompt Injection 仍无权限；
4. 内容无关 stdout/stderr 与失败退出码；失败不能输出图片/OCR/Provider raw payload。

离线 harness 和测试完成后，再向用户请求本次真实视觉 Provider 单次授权。没有新授权时不要读取
Key/用户 `.env`、不要运行 Provider；不升级依赖、不修改 `docs/progress.md`、不 push。
