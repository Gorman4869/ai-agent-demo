"""Handbook coverage metadata; reads source files, never imports application code."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

BOOK_DIR = Path(__file__).resolve().parents[1]
ROOT = BOOK_DIR.parents[1]
BOOK_NAME = 'AI-Agent课程知识手册'
BASE = '7d0dd3b3855efc6422df3f9d8e23b031ed9f6274'
EVIDENCE_OVERRIDES = {
    3: ['V-20260808-011'],
    5: ['V-20260716-006', 'V-20260829-001'],
    6: ['V-20260716-003', 'V-20260716-005', 'V-20260808-013'],
    7: ['V-20260716-006', 'V-20260716-008'],
    8: ['V-20260717-004', 'V-20260720-001', 'V-20260720-003'],
    9: ['V-20260720-005', 'V-20260720-007', 'V-20260720-009'],
    10: ['V-20260722-001', 'V-20260722-005'],
    11: ['V-20260720-011', 'V-20260720-013', 'V-20260722-005'],
    12: ['V-20260722-003'],
    18: ['V-20260828-008', 'V-20260828-009', 'V-20260828-010'],
    19: ['V-20260828-011', 'V-20260828-012', 'V-20261029-005'],
    20: ['V-20260820-011', 'V-20260831-002', 'V-20261021-002'],
}

# Each row: title, milestones, prerequisite chapters, level, code, tests,
# historical evidence, implementation boundary, four distinct knowledge units.
ROWS = [
('Agent 与模型基础','M0/M1/M8','无','必学基础','backend/app/models/base.py;backend/app/domain/agent.py','backend/tests/test_manual_agent_loop.py','V-20260716-001;V-20260716-008','Mock 决策不证明真实模型质量','Agent、聊天与工作流;Token、上下文窗口与生成;训练、推理与模型局限;结构化输出与执行权'),
('Python 工程入门','M1/M8','1','必学基础','labs/python-basics/async_json.py;backend/app/domain/agent.py;backend/app/models/base.py','backend/tests/test_manual_agent_loop.py','V-20260716-001','Python 类型注解不自动执行运行时校验','模块、包与虚拟环境;集合、None 与 JSON;类型、dataclass 与 Protocol;异常、测试与边界校验'),
('异步与 Node.js','M1/M9/M11','2','必学基础','labs/python-basics/async_json.py;labs/node-basics/async-json.mjs;backend/app/stores/async_facade.py','backend/tests/test_postgres_async_stores.py','V-20260808-009','异步取消不是强杀线程','协程与 Promise;事件循环与阻塞 I/O;异步迭代、背压与资源关闭;取消、超时与线程桥接'),
('手写 Agent Loop','M1/M8','1,2,3','必学基础','backend/app/agent/manual_loop.py;backend/app/models/mock_model.py;backend/app/demo.py','backend/tests/test_manual_agent_loop.py','V-20260716-001','标准库手写链与 durable 主链须区分','消息、决策与工具回送;ReAct 与循环控制;停止条件和预算;Mock、事件与可观察行为'),
('Function Calling 与工具注册','M1/M5/M8','4','必学基础','backend/app/tools/registry.py;backend/app/tools/builtin.py;backend/app/agent/sdk_tools.py','backend/tests/test_tool_security.py;backend/tests/test_manual_agent_loop.py','V-20260716-007','SDK 默认桥接不开放高风险副作用工具','Schema 与结构化调用;注册、发现与统一执行;权限、校验和错误回送;只读工具与副作用工具'),
('FastAPI 与分层架构','M2/M8/M11','3,5','必学基础','backend/app/main.py;backend/app/container.py;backend/app/agent/runtime.py;backend/app/services/run_coordinator.py','backend/tests/test_container.py;backend/tests/test_runtime_contract.py','V-20260716-006;V-20260808-013','HTTP、Runtime、存储各有独立职责','HTTP、DTO 与状态码;领域、适配器与依赖注入;Runtime 与 Coordinator;配置、lifespan 与优雅停止'),
('框架对照','M2/M8','4,6','进阶理解','backend/app/agent/sdk_runtime.py;backend/app/agent/graph_runtime.py;labs/langchain-agent/demo.py','backend/tests/test_openai_agents_runtime.py;backend/tests/test_runtime_comparison.py;backend/tests/test_langchain_agent_lab.py','V-20260716-007;V-20260716-008','M8 OpenAI 在线门仍未完成','四类框架的职责与取舍;Agent、Runner 与真实调用链;事件映射和 JSON 增量;Usage、guardrail 与 SDK 清理'),
('MCP 工具协议','M2/M9','3,5,6','进阶理解','backend/app/integrations/mcp/client.py;backend/app/integrations/mcp/tools.py;mcp-servers/knowledge-server/src/index.ts','backend/tests/test_mcp_client_lifecycle.py;backend/tests/test_mcp_tool_adapter.py;backend/tests/test_mcp_client_e2e.py','V-20260720-001;V-20260720-002','仅本地 STDIO，不声称远程生产兼容','Host、Client、Server 与 STDIO;初始化、发现和调用;工具映射、命名空间与可信策略;生命周期、协议排错与 roots'),
('Skill 任务说明','M2/M9','5,8','进阶理解','backend/app/skills/catalog.py;backend/app/skills/resolver.py;backend/app/skills/runtime.py;skills/research-summary/SKILL.md','backend/tests/test_skill_catalog.py;backend/tests/test_skill_context.py','V-20260720-003;V-20260720-004','只读上下文，不能自动授予工具权限','Skill、工具与 MCP 的区别;Catalog、元数据与安全加载;触发、缓存和 Runtime 注入;效果评测与上下文开销'),
('Workflow 与任务推理','M3/M10','6,7','进阶理解','backend/app/agent/research_workflow.py;backend/app/agent/replanning_runtime.py','backend/tests/test_research_workflow.py;backend/tests/test_langgraph_replanning.py','V-20260720-005;V-20260722-001','旧研究流程有低分证据混入失败用例','State、节点、边和状态合并;顺序、条件、并行与路由;计划、诊断和有界重规划;循环检测、失败与恢复边界'),
('Checkpoint 与审批恢复','M10/M11','10','进阶理解','backend/app/agent/checkpoint_runtime.py;backend/app/agent/approval_runtime.py;backend/app/agent/runtime.py','backend/tests/test_langgraph_checkpointing.py;backend/tests/test_langgraph_approval_resume.py;backend/tests/test_langgraph_recovery_faults.py','V-20260720-005;V-20260722-003','内存 saver 跨对象不等于跨进程','Checkpoint、thread 与版本;interrupt 与 Command resume;服务端精确审批和单次消费;故障窗口与重放安全'),
('多 Agent 协同','M3/M10','5,10','进阶理解','backend/app/agent/multi_agent.py;backend/app/evals/multi_agent.py','backend/tests/test_multi_agent.py;backend/tests/test_workflow_comparison_eval.py','V-20260722-002','固定集效果不是线上泛化质量','确定性角色与独立 Agent;Manager-as-tools 与 handoff;工具隔离与角色预算;单 Agent 对照和复杂度成本'),
('RAG 原理','M3/M11','4,10','必学基础','backend/app/knowledge/rag.py;backend/app/agent/research_workflow.py;backend/app/evals/rag_retrieval.py','backend/tests/test_rag.py;backend/tests/test_research_workflow.py;backend/tests/test_rag_retrieval_eval.py','V-20260820-011;V-20260827-001','词频稀疏索引不等于生产语义模型','加载、规范化与切片;召回、排序、Top-K 与阈值;证据选择、生成与拒答;引用、重排与失败定位'),
('Embedding 与向量数据库','M3/M11','13','进阶理解','backend/app/knowledge/embeddings.py;backend/app/knowledge/pgvector.py;backend/app/knowledge/pgvector_migrations.py','backend/tests/test_embeddings.py;backend/tests/test_pgvector.py;backend/tests/test_pgvector_rag_retrieval.py','V-20260809-004;V-20260827-001','3维评测向量与64维在线冒烟属于不同实验','稀疏向量、稠密向量与相似度;模型、维度与配置指纹;批处理、缓存与有限重试;pgvector、HNSW 与索引更新'),
('上下文工程','M9/M11','9,13,14','进阶理解','backend/app/context/assembler.py;backend/app/context/collector.py;backend/app/context/async_runtime.py','backend/tests/test_context_assembler.py;backend/tests/test_context_collector.py;backend/tests/test_async_context_runtime.py','V-20260809-016;V-20260819-001','bytes/4 为估算，不是 Provider tokenizer','来源、可信度与控制面;选择顺序与展示顺序;Token 预算、摘要和裁剪报告;可信身份与异步上下文接入'),
('记忆系统','M3/M11','15','进阶理解','backend/app/memory/store.py;backend/app/memory/postgres.py;backend/app/stores/postgres.py','backend/tests/test_memory.py;backend/tests/test_memory_store_contract.py','V-20260820-003;V-20260820-010','记忆与 Run/Event 不是同一事务','消息、状态、知识与长期事实;批准记忆与 owner/session 隔离;原子回合发布与幂等重放;纠正、删除、版本和审计'),
('PostgreSQL 与可靠运行','M8/M11/M13','6,11,16','工程扩展','backend/app/stores/postgres_migrations.py;backend/app/stores/postgres.py;backend/app/stores/postgres_tool_execution.py;backend/app/services/run_recovery.py','backend/tests/test_run_store_contract.py;backend/tests/test_tool_execution_store_contract.py;backend/tests/test_run_recovery.py','V-20260808-013;V-20260901-001','跨域一致性和进行中 hard-kill 仍有未验证项','迁移、事务和约束;CAS、版本与幂等创建;ToolExecution 与结果未知;租约、恢复扫描与异步数据库'),
('持久 API 与 SSE','M4/M12','6,17','必学基础','backend/app/main.py;backend/app/api/schemas.py;backend/app/services/run_event_notifier.py;frontend/src/services/agentApi.ts','backend/tests/test_persistent_run_api.py;backend/tests/test_persistent_sse.py;backend/tests/test_durable_run_projection.py','V-20260828-009;V-20260828-010;V-20260828-011','断线不等于取消，不自动创建替代 Run','owner、capability 与持久 Run API;SSE 分帧、序号和心跳;先持久化、续传与 snapshot;同 Run 投影与兼容 API'),
('Vue 实时工作台','M4/M12/M14','18','必学基础','frontend/src/services/agentApi.ts;frontend/src/composables/useAgentDesk.ts;frontend/src/types/agent.ts;frontend/src/components/ReviewWorkspace.vue','frontend/tests/unit/agentApi.spec.ts;frontend/tests/unit/useAgentDesk.spec.ts;frontend/tests/e2e/durable-run.spec.ts','V-20260828-012;V-20260828-013;V-20261029-005','使用 sessionStorage 恢复，不把旧教程内存策略当现状','类型、请求封装和 composable;流式答案、segment 和状态机;重连、刷新、取消与审批;证据、审查投影与前端可用性'),
('测试与评测','M0/M5/M11/M13/M14','4,13,18','必学基础','backend/app/evals/offline.py;backend/app/evals/rag_retrieval.py;backend/app/evals/advanced_agent.py;scripts/verify.ps1','backend/tests/test_offline_evals.py;backend/tests/test_rag_retrieval_eval.py;backend/tests/test_verification_entrypoint.py','.github/workflows/verification.yml;V-20260831-002','预期匹配率与任务成功率必须分开','单元、契约、集成与 E2E;Mock、Fake、故障注入与证据等级;Recall@K、MRR 与依据正确率;固定数据集、阈值和分层 CI'),
('可观测性与成本','M5/M13','18,20','工程扩展','backend/app/observability/runs.py;backend/app/observability/durable.py','backend/tests/test_observability.py;backend/tests/test_durable_observability.py','V-20260828-014','没有完整 OTel 和计费前硬成本门','日志、Trace、Span 与 Metrics;事件重建和 Run 排障;Usage 快照、累计值与去重;成本、覆盖率和 unknown'),
('错误与可靠性','M5/M13','5,17,21','工程扩展','backend/app/reliability.py;backend/app/agent/cancellation.py;backend/app/services/run_coordinator.py','backend/tests/test_reliability.py;backend/tests/test_run_coordinator.py','V-20260829-001','请求超时不证明外部动作未发生','稳定错误分类与 fail closed;重试、指数退避和剩余预算;deadline、协作式取消与 drain;副作用对账和事故处理'),
('安全与权限','M5/M9/M11/M13','5,11,15','必学基础','backend/app/security/identity.py;backend/app/tools/registry.py;backend/app/skills/catalog.py','backend/tests/test_identity.py;backend/tests/test_tool_security.py;backend/tests/test_skill_catalog.py','V-20260829-001;V-20261022-001','程序权限验证不等于识别所有恶意文本','认证、授权、RBAC 与 owner;Prompt Injection 与数据/控制隔离;精确审批、幂等与审计;路径、内容边界和敏感信息'),
('部署与故障演练','M5/M7/M13','17,18,21,22','工程扩展','deploy/compose.yaml;deploy/compose.deployment.yaml;deploy/nginx.conf;scripts/verify-deployment.ps1;backend/app/evals/load_fault.py','backend/tests/test_deployment_contract.py;backend/tests/test_load_fault_eval.py','V-20260831-003;V-20260901-001','单机 Mock 工作点不是生产 SLA/HA','镜像、容器、卷和网络;配置、Secret、迁移、seed 与健康;Nginx、SPA 和 SSE 代理;负载、p95、容量、SLO 与故障恢复'),
('代码 Agent 与 Harness','M6/M13','22,23','工程扩展','backend/app/advanced/harness.py;backend/app/advanced/code_agent.py;backend/app/advanced/process_runner.py','backend/tests/test_advanced_harness.py;backend/tests/test_code_agent.py;backend/tests/test_code_agent_process.py','V-20260831-005','应用级采样 Harness 不是 cgroup/seccomp/VM','Harness、动作和字节预算;固定工作区与精确写入;命令白名单和结构化执行;输出、进程树和资源边界'),
('浏览器与多模态 Agent','M6/M14','23,25','工程扩展','backend/app/advanced/browser_agent.py;backend/app/advanced/browser_driver.py;backend/app/advanced/browser_network.py;backend/app/advanced/multimodal.py','backend/tests/test_browser_network.py;backend/tests/test_browser_driver.py;backend/tests/test_multimodal_agent.py','V-20260901-004;V-20260901-005;V-20260902-001;V-20261020-005','真实 Chromium 仅受控 fixture；MiniMax E4 不证明 OpenAI E4','Planner、Policy、Driver 与观察;origin、SSRF、DNS 与重定向;PNG guard、视觉理解与不可信文字;离线回退、单次在线证据和评测'),
('综合作品集与业务迁移','M0/M7/M14','12,16,19,20,24,26','工程扩展','backend/app/advanced/review_runtime.py;backend/app/advanced/review_tools.py;backend/app/advanced/postgres_review_requests.py;backend/app/advanced/postgres_review_publication.py;backend/app/review_demo.py','backend/tests/test_review_runtime.py;backend/tests/test_review_application.py;backend/tests/test_review_publication.py;frontend/tests/e2e/review-postgres.spec.ts','V-20261023-001;V-20261029-008','M14-T6 工程通过不替代 T7/T8 或个人答辩','同 Run 三源证据与四工具;私有请求、精确审批和发布事务;威胁模型、演示与故障复盘;业务迁移、系统设计和学习闭环'),
]

def chapters():
    result = []
    for number, row in enumerate(ROWS, 1):
        title, stages, prereq, level, code, tests, evidence, limit, units = row
        topics = [{'id': f'K{(number-1)*4+i:03}', 'title': t} for i,t in enumerate(units.split(';'),1)]
        result.append(dict(number=number,title=title,stages=stages,prereq=prereq,level=level,code=code.split(';'),tests=tests.split(';'),evidence=EVIDENCE_OVERRIDES.get(number,evidence.split(';')),limit=limit,topics=topics))
    return result

def source_snapshot():
    candidates = [ROOT/'README.md',ROOT/'AGENTS.md',ROOT/'BACKEND_CODING_STANDARDS.md']
    for folder,patterns in [('docs',['*.md']),('backend/app',['*.py','*.json']),('backend/tests',['*.py']),('labs',['*.py','*.mjs','*.md']),('skills',['*.md']),('frontend/src',['*.ts','*.vue']),('frontend/tests',['*.ts']),('mcp-servers/knowledge-server/src',['*.ts']),('deploy',['*.yaml','*.conf','*.Dockerfile']),('scripts',['*.ps1']),('.github/workflows',['*.yml'])]:
        for pattern in patterns:
            candidates += list((ROOT/folder).rglob(pattern))
    candidates += [ROOT/'backend/requirements-m2.txt',ROOT/'frontend/package.json',ROOT/'frontend/package-lock.json',ROOT/'mcp-servers/knowledge-server/package-lock.json']
    records=[]
    for path in sorted(set(candidates)):
        if BOOK_DIR in path.parents or not path.is_file(): continue
        raw=path.read_bytes(); item={'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(raw).hexdigest(),'lines':len(raw.splitlines())}
        if path.suffix=='.py':
            tree=ast.parse(raw.decode('utf-8-sig'))
            item['symbols']=[{'name':n.name,'line':n.lineno} for n in ast.walk(tree) if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef))]
        records.append(item)
    return records

def make_inventory():
    out=['# 全课程知识点清单','',f'盘点基线：2026-10-30，Asia/Shanghai；base HEAD `{BASE}`。本文件是资料覆盖清单，不改写课程工程状态。','',
    '本清单先于正文建立：27 章、108 个独立知识单元。每个编号在正文、自测答案和覆盖检查中保持一致。前置列为章节编号；同章按编号递进。代码链接旁列出可供搜索的符号索引，详细定位见 `tools/source-snapshot.json`。验证列为历史记录入口，具体范围必须查原记录，不能仅凭编号推定通过。','',
    '| 编号 | 知识点 / 正文 | 层级 / 前置章 | 原课程 | 代码 / 测试 | 历史依据 / 当前限制 |','| --- | --- | --- | --- | --- | --- |']
    for c in chapters():
        refs='<br>'.join(f'[{p.split("/")[-1]}](../../{p})' for p in c['code']+c['tests'])
        for t in c['topics']:
            out.append(f'| {t["id"]} | [{t["title"]}]({BOOK_NAME}.md#{t["id"].lower()}) | {c["level"]}；{c["prereq"]} | {c["stages"]} | {refs} | {"、".join(c["evidence"])}；{c["limit"]} |')
    out += ['', '## 来源清单与维护', '', '课程入口、15 份阶段教程、专题、ADR、代码与测试文件的路径和内容摘要保存在 [来源快照](tools/source-snapshot.json)。该快照表示盘点范围与可定位符号，不等于每一行都已人工审阅或每个测试本轮都已执行。正文重点机制按代码与测试核对，实际执行见 [检查报告](quality-report.md)。', '', '运行 `python docs/course-handbook/tools/catalog.py` 可重建本清单；它不会改动正文或课程源文件。新增知识点时同时更新本表元数据、正文及对应答案，保持编号稳定。', '']
    BOOK_DIR.mkdir(parents=True,exist_ok=True)
    (BOOK_DIR/'knowledge-inventory.md').write_text('\n'.join(out),encoding='utf-8')
    (BOOK_DIR/'tools/source-snapshot.json').write_text(json.dumps({'base_head':BASE,'files':source_snapshot()},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Inventory created: 27 chapters / 108 knowledge units')

if __name__=='__main__': make_inventory()
