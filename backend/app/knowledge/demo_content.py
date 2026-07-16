from backend.app.knowledge.rag import Document


DEMO_COURSE_DOCUMENT = Document(
    id="agent-course",
    title="Agent 课程基础",
    source="course/agent-foundations.md",
    content=(
        "Agent 由模型、工具与循环控制组成。程序负责校验工具参数、执行工具并把结果返回模型。"
        "MCP 使用统一协议连接 Agent 客户端与工具和资源。"
        "RAG 先检索证据，再基于证据生成带引用的回答。"
    ),
)
