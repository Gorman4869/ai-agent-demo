# ADR-0025：有界 ContextAssembler、来源信任与预算报告

- 状态：accepted
- 日期：2026-08-09
- 任务：`M11-T4`
- 依赖：`ADR-0010`、`ADR-0013`、`ADR-0024`

## 背景

现有 `RuntimeRequest.prompt_context` 只能保存一段有界应用上下文，M9-T5 只注入 Skill，Memory 与 RAG 也各自暴露独立数据形状。系统约束、最近消息、摘要、长期记忆、检索片段和 Skill 尚无共同来源标记、选择优先级、owner 校验或预算报告。

如果直接拼接这些文本，RAG 中的指令可能与系统策略混淆，跨用户 Memory/消息可能进入错误 Run，长对话也只能依赖不可解释的字符串截断。另一方面，默认离线路径没有 Provider tokenizer；把字符启发式描述成真实 Token、usage 或费用会制造错误证据。

M11-T4 首个纵切只固定纯领域组装合同。Store 查询、摘要生成、默认 Runtime/Container 接线、持久记忆写入与固定 RAG 评测由后续原子步骤继续，不能混入本次普通 B 类任务。

## 决策

### 1. ContextFragment 使用六种服务端来源

`backend.app.context` 定义 `system`、`recent`、`summary`、`memory`、`rag` 与 `skill` 六种来源。片段保存稳定 ID、原文、owner scope 和 ordinal；内容与 owner 隐藏 repr，单片段和总数量均有硬上限。

trust 由 source 固定映射，调用方不能自行声明：

- system：`trusted_policy`
- skill：`application_guidance`
- summary/memory：`owner_scoped_data`
- recent：`user_content`
- rag：`untrusted_evidence`

只有 `trusted_policy` 可以定义策略。其他片段即使包含指令式文本，也只是数据或有界指导，不能改变身份、角色、审批、工具、Schema 或系统约束。

### 2. Owner 校验发生在任何选择或渲染之前

recent、summary 与 memory 必须携带与本次 assembly owner 完全相同的 owner ID。system 与 skill 只能是全局应用片段，不得携带 owner；RAG 可以是全局证据，也可以显式 owner-scoped，但显式 owner 必须匹配。

任一片段 scope 不合法或 owner 不匹配时，整个 assembly 以稳定无内容错误失败，不静默丢弃错误用户片段，也不返回已选择前缀。owner ID 不进入 prompt、报告、repr 或错误。

### 3. 选择优先级与渲染顺序分离

服务端固定选择优先级：

```text
system -> memory -> recent -> summary -> skill -> rag
```

system 优先且不可丢弃；memory 先于长对话历史和外部证据，以便关键已批准事实在预算紧张时仍有稳定机会进入。recent 在同来源内从最新 ordinal 开始选择，防止旧消息挤占新消息。

最终 prompt 的渲染顺序固定为：

```text
system -> skill -> summary -> memory -> recent -> rag
```

recent 按 ordinal 正序恢复时间顺序。选择和渲染顺序都写入安全预算报告，不能依赖 Python mapping 或调用方输入顺序。

### 4. 预算只选择完整片段

默认总预算最多 8,000 个 `ceil(UTF-8 bytes / 4)` 估算单位，对应现有 `RuntimeRequest.prompt_context` 的 32,000 UTF-8 字节上限。每种来源有独立估算预算；总预算按最终完整 JSON prompt 重新计算，包含 trust/source/id/ordinal 和固定安全头部。

片段按选择优先级完整纳入或完整丢弃，不从中间截断 JSON、消息、Skill 或检索证据。超过来源预算或总预算的非 system 片段进入报告并记录稳定原因；任一 system 片段无法完整容纳时返回 `required_context_over_budget`，绝不静默删除策略。

该估算只用于离线相对预算，不是 Provider tokenizer、usage、上下文窗口确认、账单或费用。报告固定声明 `provider_usage_available=false`、`estimated_cost_usd=null`。

### 5. 渲染与报告都确定且内容隔离

非空 assembly 渲染为固定安全头部加 `context-assembly-v1` 紧凑 JSON。每条记录显式包含 source、trust、稳定 ID、ordinal 和 content；JSON 编码确保检索文本不能通过引号或括号伪造 trust/source 结构。

安全报告只包含预算、来源可用性、片段 ID、trust、估算量、是否纳入和原因，不包含片段内容或 owner。摘要等可选来源失败时由 `unavailable_sources` 显式记录，Assembler 不伪造摘要；system 来源不可用则 fail closed。空片段输入返回 `prompt_context=None` 和零成本报告。

## 首个纵切边界

- 实现纯标准库 ContextFragment、预算 Policy、Assembler、确定性 JSON 与安全报告，并导出独立 `backend.app.context` 包。
- 自动化覆盖六来源顺序与 trust、空输入、长历史裁剪、关键 Memory 保留、system 超预算/不可用、RAG JSON 逃逸、owner 隔离、摘要不可用、非法片段/Policy、128 片段上限和报告脱敏。
- 组装结果实际通过现有 `RuntimeRequest.prompt_context` 32 KB 校验，但本纵切不修改 RuntimeRequest、Runtime、Container、MemoryStore、KnowledgeBase 或 SkillBuilder。
- 不查询 Store、不生成摘要、不调用模型、不写持久记忆、不创建 M11-T6 评测集；M11-T4 保持 `in_progress`。

## 后果

- 后续 source collector 和 Runtime 接线已有单一、可解释、可 fail-closed 的输入/输出合同，不需要各 Runtime 重复拼接。
- RAG 指令、用户消息、摘要、Memory 与 Skill 不再能伪装成系统策略；结构标记是工程隔离边界，但不是“模型一定服从”的在线质量证据。
- 预算报告能解释每段为何进入或被丢弃，也能明确区分估算量与 Provider usage。
- 当前关键事实保留来自固定优先级和完整片段预算，不等于语义相关性、摘要质量或真实长上下文模型能力。

## 未采用方案

- 直接修改 `RuntimeRequest` 或默认 Container：首个领域纵切不需要共享契约变化，过早接线会扩大回归面。
- 按字符串末尾截断到 32 KB：可能截断 JSON、系统约束或多字节字符，也无法解释丢弃原因。
- 让片段自行声明 trust/priority：检索、模型或调用方文本可能提升自己的权限。
- 把 RAG 指令过滤后当可信文本：无法完整枚举提示注入写法，也会破坏证据内容；保留原文并固定为 untrusted data 更可审计。
- 摘要失败时自动拼回全部历史：可能突破预算并隐藏故障；当前只显式报告 unavailable，后续 collector 决定是否提供其他已验证来源。
- 把 `ceil(bytes / 4)` 写成真实 Token 或费用：没有 Provider tokenizer、usage 与版本化定价，结论不成立。

## 验证依据

- `backend/tests/test_context_assembler.py`
- `backend/tests/test_runtime_contract.py`
- `backend/tests/test_skill_context.py`
- `backend/tests/test_memory.py`
- `backend/tests/test_rag.py`
- `V-20260809-008`
