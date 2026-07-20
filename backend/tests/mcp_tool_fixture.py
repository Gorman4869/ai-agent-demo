from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("m9-tool-fixture")


@mcp.tool()
def role_echo(value: str) -> str:
    """Return one value for role-filter tests."""
    return value


@mcp.tool()
async def slow_echo(value: str) -> str:
    """Return one value after the client request timeout."""
    await asyncio.sleep(2)
    return value


@mcp.tool()
def fail_tool(value: str) -> str:
    """Raise a remote failure containing data the client must not expose."""
    raise ValueError(f"remote-secret:{value}")


@mcp.tool()
def oversized_result() -> str:
    """Return a valid MCP result above the application output bound."""
    return "x" * 70_000


@mcp.tool()
def unlisted_tool(value: str) -> str:
    """Remain unexposed because application policy does not allow it."""
    return value


if __name__ == "__main__":
    mcp.run()
