from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from backend.app.knowledge import KnowledgeBase

THRESHOLD = 0.3

class ResearchWorkflowState(TypedDict):
    question: str
    evidence: list[dict[str, object]]
    draft: str
    critique: str
    approved: bool
    answer: str


def create_research_workflow(knowledge_base: KnowledgeBase):
    graph = StateGraph(ResearchWorkflowState)
    threshold = THRESHOLD

    def retrieve(state: ResearchWorkflowState) -> dict[str, list[dict[str, object]]]:
        evidence = [
            {
                "score": result.score,
                "title": result.citation.title,
                "source": result.citation.source,
                "excerpt": result.citation.excerpt,
            }
            for result in knowledge_base.search(state["question"], limit=3)
        ]
        return {"evidence": evidence}

    def draft(state: ResearchWorkflowState) -> dict[str, str]:
        if not state["evidence"]:
            return {"draft": "没有检索到足够证据，暂不回答。"}
        excerpts = "；".join(str(item["excerpt"]) for item in state["evidence"])
        return {"draft": f"根据课程资料：{excerpts}"}

    def review(state: ResearchWorkflowState) -> dict[str, object]:
        # 这是给审核节点增加“绝对相关性”条件，不是筛掉全部低分候选，也不是要求所有 evidence 都达标
        if not state["evidence"]:
            return {"approved": False, "critique": "缺少可核验依据"}
        max_score = max(item["score"] for item in state["evidence"])
        approved = bool(state["evidence"]) and max_score >= threshold and "根据课程资料" in state["draft"]
        return {
            "approved": approved,
            "critique": "证据和引用完整" if approved else "缺少可核验依据",
        }

    def finalize(state: ResearchWorkflowState) -> dict[str, str]:
        return {"answer": state["draft"] if state["approved"] else state["critique"]}

    graph.add_node("researcher", retrieve)
    graph.add_node("writer", draft)
    graph.add_node("reviewer", review)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "researcher")
    graph.add_edge("researcher", "writer")
    graph.add_edge("writer", "reviewer")
    graph.add_edge("reviewer", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()
