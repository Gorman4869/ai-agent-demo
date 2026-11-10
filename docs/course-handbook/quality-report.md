# 制作与质量检查记录

资料日期：2026-10-30，Asia/Shanghai。基线 HEAD：`7d0dd3b3855efc6422df3f9d8e23b031ed9f6274`。

本轮为 B 类全课程资料整合，跨里程碑阅读由用户明确授权。仅新增手册目录；依照本次用户范围约束，不改 continuity、原阶段课程、测试或个人 progress。原有失败不修复、不重写为通过。

## 资料依据

依据学习计划、30项映射、15份阶段教程、专题文档、关联ADR、代码与测试；历史状态核对至 V-20261029-008。来源路径、摘要及 Python 符号行号见[来源快照](tools/source-snapshot.json)。解析快照不等于执行所有测试或逐行人工审阅全部仓库。

正文 27 章、108 个知识单元；来源和前置关系先记录于[知识清单](knowledge-inventory.md)，再编写完整正文。Markdown 是唯一正文来源；PDF由它解析构建，不另写副本。

## 发现的差异与保留范围

- 2026-10-30 制作时，`research_workflow.draft` 拼接全部候选，混合强弱证据测试失败。后续学习者在 `draft()` 中实现筛选，并报告原用例转绿（1 项）、工作流回归通过（4 项）；Markdown 的 K051 已同步。下表保留制作时的实测记录。KI-035 是独立的 legacy API 审核阈值问题，仍开放，本次文档同步未重跑该 API 用例。
- M11 阶段页若干“计划验证命令”引用不存在的 `backend.tests.integration.*` / `test_rag_evals`；手册使用实际 `postgres_store_integration`、`pgvector_integration`、`test_rag_retrieval_eval` 入口，原页未改。
- M12 阶段页的事件示意名与实际事件合同不完全一致；正文使用 `model.output.delta/model.usage/rag.citations` 等实际名称。
- M4/M5 早期 UI 描述为内存 capability 与 legacy POST 流；当前主链为 durable create/GET SSE/snapshot，当前标签页 sessionStorage 恢复；手册区分年代与实现。
- M8 OpenAI 在线门、M11-T8、M14-T7/T8 及 KI-037 未被本次整理推进；图像完整解码、生产身份、硬成本门、HA和进行中hard-kill等未验证项按正文附录H保留。

## 实际验证

以下为本轮实际结果；历史V编号只在正文说明对应历史环境，不参与本轮通过数。

| 检查 | 实际命令 / 方法 | 结果 |
| --- | --- | --- |
| 手册结构、来源和链接 | bundled Python `tools/check.py --examples --pdf` | 27章、108知识点、108题/答案、30项大纲；253个显式锚点；1,444个链接；462份来源摘要无漂移；46个历史V编号存在 |
| 可运行短例 | 同一脚本从正文提取5段Python，在项目既有.venv中执行 | JSON、RAG、批处理、MRR、退避5/5；输出与正文一致 |
| 标准库手写Loop | `.\.venv\Scripts\python.exe -X utf8 -B -S -m unittest backend.tests.test_manual_agent_loop -q` | 退出0，11/11通过 |
| 研究工作流现状 | `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_research_workflow -q` | 退出1，4项中3通过、1既有失败：test_writer_excludes_low_relevance_evidence_from_answer；分数0.353553/0.246183，低分内容仍拼入answer；未修改 |
| 检索/向量/上下文定向 | `.\.venv\Scripts\python.exe -X utf8 -B -m unittest backend.tests.test_rag backend.tests.test_embeddings backend.tests.test_context_assembler -q` | 退出0，42/42通过，0.006s |
| 固定sparse评测 | `.\.venv\Scripts\python.exe -X utf8 -B -m backend.app.evals.rag_retrieval` | 退出0，m11-rag-v1，50项；Recall@3/MRR/依据正确率=1/1/1；Provider usage不可用，费用null |
| 前端单测 | `npm.cmd --prefix frontend run test:unit`，仅本次进程TEMP/TMP定向至手册.build/vitest-temp | 退出0，2文件、15/15通过，2.39s；环境变量随后恢复 |
| PDF导出 | `node docs/course-handbook/tools/build.mjs` | 从同一Markdown生成A4、86页、145条目录/书签项、1,015处链接注释；6张SVG图源 |
| PDF内容与几何 | pypdf与pdfplumber；check.py --pdf | 981段正文/表格单元/代码规范化对照，缺失0；108编号及题目存在；中文/等宽字体嵌入；无替换/空字符；无字符越安全边界 |
| PDF全页视觉 | `pdftoppm -scale-to 1100 -png`；preview.py生成10张联系表 | 全86页渲染并逐页查看缩略布局；放大第35、46、64、80页检查中文、代码/续行、图和长表；无缺字、重叠、裁切；长表续页重复表头 |
| 原文档链接 | `.\scripts\check-continuity.ps1` | 退出0，52个稳定任务、209份Markdown；只读检查，未更新原工程状态 |
| 文件范围 | git status、来源hash、空白/语法检查 | 仅新增docs/course-handbook内文件；业务、测试、原课程、progress及依赖无改动；未提交/未push |

原始机器检查摘要保存在忽略的 `.build/check.json`。正文中“五个短例通过”“Loop 11项通过”均有本轮证据。其余章节给出的命令属于可定位的跟练入口，不暗示本轮逐条执行全部命令。

## 未完成的本轮环境检查

曾尝试组合运行rag、embeddings、context_assembler、runtime_comparison和durable_run_projection；长时间未结束后中止。缩小范围仍在runtime_comparison的第一个异步测试开始时阻塞。使用35秒faulthandler看门狗复核，栈停在Windows asyncio Proactor初始化的socket._fallback_socketpair / accept，尚未进入该异步测试断言。

因此不把该组记成通过，也不据此断言课程存在新业务回归。纯同步三组已单独42/42通过；runtime对照和durable投影没有本轮完成结果，仍只引用原历史证据。本轮没有切换全局事件循环、提升权限或扩大验证到数据库/浏览器。后续若需复验，可在允许创建本机loopback socketpair的环境按原命令执行。

## 工具与制作失败

使用已有 bundled marked、Sharp、ReportLab、pypdf/pdfplumber、Poppler和Windows中文/等宽字体；没有安装或升级依赖。

prepare.py 初次执行因脚本字符串转义残留导致 SyntaxError；只修正本目录脚本，随后知识清单/导航与SVG生成成功，未触及课程代码。

PDF首次保存因marked将独立HTML锚点归类为paragraph而缺少内部跳转目标；已在导出器显式处理独立及内嵌锚点，重新导出成功。内容一致性辅助命令初次未区分表格单元与普通token而KeyError，已纳入正式check.py；最终补齐术语说明后981段核对通过。

前端首次Vitest在系统沙箱临时目录rename时报EPERM，2个suite均未进入测试；没有把它记成业务失败。仅为本次命令建立手册内临时目录后15/15通过，未修改测试/配置/锁文件。

## 未运行范围

本轮不运行在线模型、真实数据库、浏览器E2E、Docker部署或远程CI；不访问真实Key/Token/DSN。历史验证数字明确附V编号，不能视为本轮重跑。

不声称所有参考命令本次均已通过，不声称全课程accepted。M8在线、M11原课程交付、M14终审/个人训练以及附录H列出的生产边界仍是后续范围。知识覆盖检查只说明资料是否讲到及可追溯，不替代实现验收或学习者个人通关。
