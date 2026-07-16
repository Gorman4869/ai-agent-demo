from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class ResearchState(TypedDict):
    question: str
    plan: list[str]
    approved: bool
    answer: str


def create_research_graph():
    graph = StateGraph(ResearchState)
    graph.add_node("plan", _plan)
    graph.add_node("review", _review)
    graph.add_node("answer", _answer)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "review")
    graph.add_conditional_edges(
        "review",
        lambda state: "answer" if state["approved"] else END,
        {"answer": "answer", END: END},
    )
    graph.add_edge("answer", END)
    return graph.compile()


def _plan(state: ResearchState) -> dict[str, list[str]]:
    return {"plan": ["明确问题", "收集证据", "组织答案"]}


def _review(state: ResearchState) -> dict[str, bool]:
    return {"approved": bool(state["question"].strip())}


def _answer(state: ResearchState) -> dict[str, str]:
    return {"answer": f"已为“{state['question']}”生成 {len(state['plan'])} 步研究计划"}
