# M9-T4 交接：只读 Skill Catalog 与 Resolver

- 日期：2026-07-20，Asia/Shanghai
- 完成任务：`M9-T4`
- 完成状态：`verified`
- 下一任务：`M9-T5 / planned`
- 验证基线 HEAD：`83a5234`
- M9-T3 实现提交：`5aba130`
- M9-T4 实现提交：待本轮本地 commit 固定
- 验证记录：`V-20260720-005`
- 架构决策：无新增 ADR；严格 frontmatter 与缓存为可逆的局部实现
- 分支：`main`
- 任务等级：`B`，只读离线 Skill 纵切，时间盒 60–90 分钟
- 新增或安装依赖：无；只使用 Python 标准库
- 在线模型/付费调用：未执行，费用 0
- 远程仓库：未配置

## 本次完成

1. 新增 `backend.app.skills`，以冻结 `SkillDefinition`/`SkillReference` 表示受控内容，默认根目录固定为仓库 `skills`。
2. Catalog 严格解析 `name`/`description` 标量 frontmatter，只读取 `SKILL.md` 与显式 `references/*.md`；不加载 `agents/`、脚本、二进制或任意本地路径。
3. canonical root、逐路径组件 symlink、相对路径、扩展名和安全字符检查阻止逃逸；Skill、文件、reference、总字节、frontmatter 和查询均有上限。
4. Catalog 使用锁保护不可变缓存快照；普通 `load()` 不受磁盘后续变化影响，只有显式 `refresh()` 替换快照。
5. Resolver 支持 `$research-summary` 显式触发和 `research summary` 全名称词元自动触发；未知显式名称与非法查询返回稳定错误。
6. 10 项测试真实加载现有 `research-summary`/`output-contract.md`，并覆盖缓存、错误元数据、缺失/逃逸引用、超限、非 UTF-8、symlink 拒绝分支与无关脚本不执行。
7. 阶段 09 与后端规范增加最小命令、触发规则、安全边界和 M9-T5 承接点，没有扩写完整题库或注入 Runtime。

## 真实证据边界

- 测试读取真实仓库 Skill 和 reference；临时 Skill 使用实际文件系统验证 `../`/嵌套逃逸、大小、UTF-8 与不执行脚本。
- 当前 Windows 无法创建临时 symlink，最终测试以真实创建尝试加受控分支覆盖验证 `symlink_not_allowed`；这不是 OS 级 symlink 实证。
- 本次只证明 Catalog/Resolver 的离线应用边界；没有注入 Manual/SDK/LangGraph，也没有效果或成本评测。

## 本次修改文件

- `backend/app/skills/__init__.py`
- `backend/app/skills/catalog.py`
- `backend/app/skills/resolver.py`
- `backend/tests/test_skill_catalog.py`
- `BACKEND_CODING_STANDARDS.md`
- `docs/stages/09-mcp-client-skills.md`
- `docs/continuity/verification-log.md`
- `docs/continuity/status.md`
- `docs/continuity/handoffs/2026-07-20-m9-t4-skill-catalog-resolver.md`

## 实际验证

- M9-T3 恢复：TypeScript build、4 项 E2E 和 52 个稳定任务/57 个 Markdown 连续性检查通过。
- M9-T4 聚焦：首轮 9 通过/1 symlink 跳过；调整为能力不足时受控覆盖拒绝分支后，最终 10 项全部通过。
- 定向回归：Skill Catalog 与 Code Agent 共运行 17 项，16 项通过、1 项既有 Windows symlink 能力跳过。
- 连续性：52 个稳定任务、58 个 Markdown 文件通过；tracked diff 与新增文件尾随空白检查无错误，只有既有 LF/CRLF 提示。
- 未执行全量门：没有依赖/锁文件、公共 Runtime 契约、HTTP Schema、前端或跨模块接口变化。

## 失败尝试与修复

- 沙箱首次拒绝创建 `backend/app/skills` 目录；取得仅工作区该目录创建授权后成功，没有修改工作区外文件。
- Windows 临时 symlink 创建返回 errno 22；未把首轮 skip 当作最终分支证据。最终保留真实创建尝试，并用受控方法替换只覆盖拒绝分支，同时如实保留 OS 实证缺口。

## 警告与未验证范围

- 既有 Code Agent symlink 测试仍因 Windows 环境能力跳过；未修改操作系统策略或使用 junction 绕过。
- 严格 frontmatter 不是完整 YAML；只支持安全单行标量 `name`/`description`。新增 Skill 若需要数组或嵌套元数据，必须先扩展受控 grammar 和测试，不能直接引入任意对象反序列化。
- 没有实现文件监听、自动失效、跨进程缓存、TOCTOU 的 OS 级沙箱保证、Skill 管理写接口或 Runtime 权限提升。
- 没有读取 Key、运行在线模型、访问网络服务或产生费用。

## 未提交改动

handoff 创建时以上 M9-T4 文件均未提交；不得回滚或混入 M9-T5 实现。提交后的新 HEAD 由下一条 verification 或 handoff 记录。

## 下一条原子动作

开始 `M9-T5` 的 B 类 Skill 上下文纵切：先只读审阅实施计划 M9-T5、`RuntimeRequest`、Manual/SDK/LangGraph 模型输入组装和现有 offline eval 风格；定义有界、可追踪但不含路径的 SkillContext 片段，建立触发/不触发固定样例及效果/成本对照。不得让 Skill 绕过 ToolRegistry、身份、审批或 Schema，不提前执行 M9-T6 或 M10。

## 恢复检查

```powershell
git status --short
git log -6 --oneline
.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_skill_catalog -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-continuity.ps1
```

预期 10 项测试通过，连续性为 52 个稳定任务和 58 个 Markdown 文件。若一致，不要重做 M9-T1–M9-T4，直接进入 M9-T5 SkillContext 与固定离线评测。
