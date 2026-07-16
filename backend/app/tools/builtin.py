from __future__ import annotations

from typing import Any

from backend.app.tools import ToolDefinition, ToolRegistry, ToolRisk


def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="add_numbers",
            description="Add two numbers and return the sum.",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
            handler=_add_numbers,
        )
    )
    registry.register(
        ToolDefinition(
            name="publish_report",
            description="Publish one report by id. This teaching tool simulates a side effect.",
            input_schema={
                "type": "object",
                "properties": {"report_id": {"type": "string"}},
                "required": ["report_id"],
            },
            handler=_publish_report,
            allowed_roles=frozenset({"editor"}),
            risk_level=ToolRisk.HIGH,
            has_side_effects=True,
        )
    )
    return registry


def _add_numbers(arguments: dict[str, Any]) -> float | int:
    return arguments["a"] + arguments["b"]


def _publish_report(arguments: dict[str, Any]) -> dict[str, str]:
    return {"report_id": arguments["report_id"], "status": "published"}
