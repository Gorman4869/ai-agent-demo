from __future__ import annotations

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("ai-agent-learning-knowledge")

KNOWLEDGE = {
    "agent": "Agent 是由模型、工具与循环控制组成的程序。",
    "mcp": "MCP 用统一协议连接 Agent 客户端与外部工具、资源和提示。",
    "rag": "RAG 先检索证据，再把证据加入模型上下文生成回答。",
}


@mcp.tool()
def lookup_concept(name: str) -> str:
    """Look up one AI Agent course concept by its lowercase name."""
    return KNOWLEDGE.get(name.strip().lower(), "未找到该概念")


if __name__ == "__main__":
    mcp.run()
