# ADR-0010：有界 Skill Runtime 上下文与权限隔离

- 状态：accepted
- 日期：2026-07-20
- 任务：`M9-T5`
- 依赖：`ADR-0003`、`ADR-0007`、`ADR-0008`

## 背景

M9-T4 已能从服务端固定目录解析只读 Skill，但尚未规定 Skill 如何进入 Manual、OpenAI Agents SDK 和 LangGraph 的模型上下文。直接把 Skill 文本拼到用户输入会改变原始请求语义，可能让 Mock 回显内部说明，也无法清楚区分任务指导与身份、审批和工具策略。

Skill 内容会增加输入开销，但默认离线评测拿不到 Provider tokenizer、usage 或价格。把字符估算写成真实 Token 或美元费用会制造错误证据。

## 决策

### 1. RuntimeRequest 使用独立提示上下文

`RuntimeRequest` 在既有位置参数之后增加可选 `prompt_context`。字段隐藏 repr、最大 32,000 UTF-8 字节，并拒绝空值和非法控制字符；原始 `input_text` 与 `ToolExecutionContext` 保持不变。

`SkillContextBuilder` 只接收 M9-T4 Resolver 的冻结结果，最多注入 4 个 Skill、24,000 UTF-8 字节。片段使用确定性 JSON，包含名称、描述、说明和内嵌 reference 内容，但把 reference 源路径替换为稳定编号。片段首部明确声明 Skill 不能改变身份、角色、审批、可用工具、工具 Schema 或系统策略。

### 2. 默认 Runtime 通过装饰器注入

`SkillAwareRuntime` 在调用具体 Runtime 前解析原始输入并生成新的冻结请求。无匹配时原请求对象原样传递；未知显式 Skill、Catalog 或上下文错误返回稳定的 `skill_context_unavailable`，不把查询、文件路径或内容暴露到失败结果。

默认 `ApplicationContainer` 包装其内建 Manual、Agents SDK 或 LangGraph Runtime。显式注入的测试或外部 Runtime 保持原对象，不被 Container 隐式改写；调用方需要 Skill 时应显式使用相同装饰器。

### 3. 三种 Runtime 保持角色分离

- Manual Loop 把 `prompt_context` 放入首条 system message，用户消息保持原文。
- LangGraph 初始 state 使用可选 system message 加原始 user message。
- OpenAI Agents SDK 的默认 agent factory 把片段加入 agent instructions，Runner input 仍是原始用户文本。

所有工具仍来自现有 Registry 快照，执行继续重复角色、审批与 Schema 校验。Skill 不能构造或修改 `ToolExecutionContext`，也不能把隐藏工具变成已授权调用。

### 4. 离线评测只报告可证明的开销

固定评测使用真实 LangGraph Runtime API 和确定性离线模型，对比一个显式触发样例与一个不触发样例。上下文成本记录 UTF-8 字节数与 `ceil(bytes / 4)` 启发式输入 Token；报告固定写明 Provider usage 不可用、美元成本为 `null`。该结果用于相对比较，不是 tokenizer、在线质量或账单证据，也不关闭 `KI-018`。

## 后果

- Skill 指导与用户输入、身份授权和工具契约有可测试的独立边界。
- 默认 Container 能让三个内建 Runtime 复用同一解析和限制逻辑。
- `RuntimeRequest` 是共享契约变化，需要覆盖旧位置参数、三 Runtime、Coordinator、Container 与工具安全回归。
- 当前评测只能证明确定性离线效果和提示开销；真实模型遵循程度、Provider Token、费用和线上质量仍未验证。

## 未采用方案

- 把 Skill 前缀拼入 `input_text`：会污染原始用户消息并混淆信任层级。
- 把 Skill 写进 `ToolExecutionContext`：会把任务指导与身份、审批错误耦合。
- 让每个 Runtime 独立解析磁盘：会重复安全逻辑并产生不同快照。
- 用 UTF-8 启发式估算美元成本：没有 Provider usage 和版本化价格，结论不可信。

## 验证依据

- `backend/tests/test_skill_context.py`
- `backend/tests/test_runtime_contract.py`
- `backend/tests/test_runtime_comparison.py`
- `backend/tests/test_openai_agents_runtime.py`
- `backend/tests/test_tool_security.py`
- `backend/tests/test_container.py`
