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
    registry.register(
        ToolDefinition(
            name="convert_temperature",
            description="Convert a temperature between Celsius and Fahrenheit.",
            input_schema={
                "type": "object",
                "properties": {
                    "value": {"type": "number"},
                    "from_unit": {"type": "string"},
                    "to_unit": {"type": "string"},
                },
                "required": ["value", "from_unit", "to_unit"],
            },
            handler=_convert_temperature,
        )
    )
    return registry


def _add_numbers(arguments: dict[str, Any]) -> float | int:
    return arguments["a"] + arguments["b"]


def _publish_report(arguments: dict[str, Any]) -> dict[str, str]:
    return {"report_id": arguments["report_id"], "status": "published"}

def _convert_temperature(arguments: dict[str, Any]) -> float | int:
    value = arguments["value"]
    from_unit = arguments["from_unit"].upper()
    to_unit = arguments["to_unit"].upper()

    if from_unit not in {"C", "F"} or to_unit not in {"C", "F"}:
        raise ValueError("Unsupported temperature unit. Use 'C' or 'F'.")
    if from_unit == to_unit:
        return value
    if from_unit == "C":
        return (value * 9/5) + 32
    return (value - 32) * 5/9
