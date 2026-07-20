from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from mcp.types import CallToolResult, TextContent, Tool

from backend.app.integrations.mcp.config import McpToolPolicy
from backend.app.tools import ToolDefinition


_MAX_SCHEMA_BYTES = 32_000
_MAX_RESULT_BYTES = 64_000
_MAX_ARGUMENT_BYTES = 64_000
_MAX_JSON_DEPTH = 12
_MAX_JSON_NODES = 4_096
_PROPERTY_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")

McpToolInvoker = Callable[[str, str, dict[str, Any]], object]


class McpToolMappingError(ValueError):
    """Stable discovery or mapping failure without untrusted metadata."""

    def __init__(self, *, server_id: str, code: str) -> None:
        self.server_id = server_id
        self.code = code
        super().__init__(f"MCP server '{server_id}' tool mapping failed with {code}")


class McpToolInvocationError(RuntimeError):
    """Stable invocation failure without remote output or exception text."""

    def __init__(self, *, server_id: str, code: str) -> None:
        self.server_id = server_id
        self.code = code
        super().__init__(f"MCP server '{server_id}' tool call failed with {code}")


def map_discovered_tools(
    *,
    server_id: str,
    discovered: Sequence[Tool],
    policies: Mapping[str, McpToolPolicy],
    invoke: McpToolInvoker,
) -> tuple[ToolDefinition, ...]:
    """Map one untrusted MCP discovery snapshot to shared tool contracts."""

    by_name: dict[str, Tool] = {}
    for tool in discovered:
        if tool.name in by_name:
            raise McpToolMappingError(
                server_id=server_id,
                code="duplicate_remote_tool",
            )
        by_name[tool.name] = tool

    definitions: list[ToolDefinition] = []
    for remote_name, policy in policies.items():
        remote_tool = by_name.get(remote_name)
        if remote_tool is None:
            raise McpToolMappingError(
                server_id=server_id,
                code="configured_tool_missing",
            )
        try:
            schema = normalize_input_schema(remote_tool.inputSchema)
        except ValueError:
            raise McpToolMappingError(
                server_id=server_id,
                code="invalid_tool_schema",
            ) from None

        def handler(
            arguments: dict[str, Any],
            *,
            selected_name: str = remote_name,
        ) -> object:
            return invoke(server_id, selected_name, arguments)

        definitions.append(
            ToolDefinition(
                name=policy.local_name,
                description=policy.description,
                input_schema=schema,
                handler=handler,
                allowed_roles=policy.allowed_roles,
                risk_level=policy.risk_level,
                has_side_effects=policy.has_side_effects,
                requires_approval=policy.requires_approval,
            )
        )
    return tuple(definitions)


def normalize_input_schema(value: object) -> dict[str, Any]:
    schema = _bounded_json_copy(
        value,
        max_bytes=_MAX_SCHEMA_BYTES,
        label="MCP tool schema",
    )
    if not isinstance(schema, dict):
        raise ValueError("MCP tool schema must be an object")
    allowed_root = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "title",
        "description",
        "$schema",
    }
    if set(schema) - allowed_root or schema.get("type") != "object":
        raise ValueError("MCP tool schema root is unsupported")
    properties = schema.get("properties")
    required = schema.get("required", [])
    if not isinstance(properties, dict) or len(properties) > 64:
        raise ValueError("MCP tool properties are invalid")
    if not isinstance(required, list):
        raise ValueError("MCP tool required fields are invalid")

    normalized_properties: dict[str, dict[str, Any]] = {}
    allowed_property = {
        "type",
        "enum",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "title",
        "description",
        "default",
        "examples",
    }
    retained_property = {
        "type",
        "enum",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
    }
    for name, property_schema in properties.items():
        if (
            not isinstance(name, str)
            or _PROPERTY_NAME_PATTERN.fullmatch(name) is None
            or not isinstance(property_schema, dict)
            or set(property_schema) - allowed_property
        ):
            raise ValueError("MCP tool property schema is unsupported")
        normalized_properties[name] = {
            key: property_schema[key]
            for key in retained_property
            if key in property_schema
        }

    return {
        "type": "object",
        "properties": normalized_properties,
        "required": list(required),
        "additionalProperties": False,
    }


def normalize_arguments(arguments: object) -> dict[str, Any]:
    normalized = _bounded_json_copy(
        arguments,
        max_bytes=_MAX_ARGUMENT_BYTES,
        label="MCP tool arguments",
    )
    if not isinstance(normalized, dict):
        raise ValueError("MCP tool arguments must be an object")
    return normalized


def normalize_call_result(
    result: CallToolResult,
    *,
    server_id: str,
) -> object:
    if result.isError:
        raise McpToolInvocationError(
            server_id=server_id,
            code="remote_tool_error",
        )
    if result.structuredContent is not None:
        return _bounded_json_copy(
            result.structuredContent,
            max_bytes=_MAX_RESULT_BYTES,
            label="MCP tool result",
        )

    content: list[dict[str, str]] = []
    for item in result.content:
        if not isinstance(item, TextContent):
            raise McpToolInvocationError(
                server_id=server_id,
                code="untrusted_tool_result",
            )
        content.append({"type": "text", "text": item.text})
    return _bounded_json_copy(
        {"content": content},
        max_bytes=_MAX_RESULT_BYTES,
        label="MCP tool result",
    )


def _bounded_json_copy(
    value: object,
    *,
    max_bytes: int,
    label: str,
) -> object:
    _validate_json_shape(value, set(), nodes=[0], depth=0, label=label)
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeError):
        raise ValueError(f"{label} must be standard JSON") from None
    if len(serialized.encode("utf-8")) > max_bytes:
        raise ValueError(f"{label} exceeds the size limit")
    return json.loads(serialized)


def _validate_json_shape(
    value: object,
    active_ids: set[int],
    *,
    nodes: list[int],
    depth: int,
    label: str,
) -> None:
    nodes[0] += 1
    if depth > _MAX_JSON_DEPTH or nodes[0] > _MAX_JSON_NODES:
        raise ValueError(f"{label} exceeds structural limits")
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if not isinstance(value, (dict, list)):
        raise ValueError(f"{label} must be standard JSON")
    object_id = id(value)
    if object_id in active_ids:
        raise ValueError(f"{label} contains a cycle")
    active_ids.add(object_id)
    try:
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError(f"{label} object keys must be strings")
            children = value.values()
        else:
            children = value
        for child in children:
            _validate_json_shape(
                child,
                active_ids,
                nodes=nodes,
                depth=depth + 1,
                label=label,
            )
    finally:
        active_ids.remove(object_id)
