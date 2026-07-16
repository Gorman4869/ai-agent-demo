from __future__ import annotations

import asyncio
import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any

from agents import FunctionTool
from agents.tool import FunctionToolCustomDataContext
from agents.tool_context import ToolContext

from backend.app.agent.cancellation import CancellationToken
from backend.app.tools import (
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    ToolResult,
)


_MAX_TOOL_ARGUMENT_BYTES = 64_000
_MAX_TOOL_OUTPUT_BYTES = 64_000
_MAX_TOOL_SCHEMA_BYTES = 32_000
_MAX_TOOL_JSON_DEPTH = 12
_MAX_TOOL_JSON_NODES = 4_096
_TOOL_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass(frozen=True)
class OpenAIAgentsRunContext:
    """Trusted, per-Run context passed to SDK function tools."""

    run_id: str = field(repr=False)
    execution_context: ToolExecutionContext = field(repr=False, compare=False)
    cancellation_token: CancellationToken = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _required_identifier(self.run_id, "run_id", max_length=200)
        if not isinstance(self.execution_context, ToolExecutionContext):
            raise ValueError("execution_context has an invalid type")
        if not isinstance(self.cancellation_token, CancellationToken):
            raise ValueError("cancellation_token has an invalid type")


def build_sdk_tools(
    registry: ToolRegistry,
    *,
    run_context: OpenAIAgentsRunContext,
) -> tuple[FunctionTool, ...]:
    """Build one isolated set of SDK tools from the shared domain registry."""

    if not isinstance(registry, ToolRegistry):
        raise ValueError("registry has an invalid type")
    if not isinstance(run_context, OpenAIAgentsRunContext):
        raise ValueError("run_context has an invalid type")
    isolated_registry = ToolRegistry()
    definitions: list[ToolDefinition] = []
    for definition in registry.definitions(
        context=run_context.execution_context
    ):
        if definition.approval_required:
            continue
        snapshot = _snapshot_definition(definition)
        isolated_registry.register(snapshot)
        definitions.append(snapshot)
    return tuple(
        _build_sdk_tool(isolated_registry, definition, run_context)
        for definition in definitions
    )


def _snapshot_definition(definition: ToolDefinition) -> ToolDefinition:
    if _TOOL_NAME_PATTERN.fullmatch(definition.name) is None:
        raise ValueError("tool name has an invalid format")
    if (
        not isinstance(definition.description, str)
        or not definition.description.strip()
        or len(definition.description) > 2_000
        or any(not character.isprintable() for character in definition.description)
    ):
        raise ValueError("tool description has an invalid format")
    schema = copy.deepcopy(definition.input_schema)
    schema["additionalProperties"] = False
    allowed_root = {"type", "properties", "required", "additionalProperties"}
    if set(schema) - allowed_root:
        raise ValueError("Unsupported tool schema keywords")
    properties = schema.get("properties")
    if not isinstance(properties, dict) or len(properties) > 64:
        raise ValueError("tool schema has too many properties")
    if any(
        not isinstance(name, str)
        or _TOOL_NAME_PATTERN.fullmatch(name) is None
        for name in properties
    ):
        raise ValueError("tool property name has an invalid format")
    _ensure_bounded_json(
        schema,
        max_bytes=_MAX_TOOL_SCHEMA_BYTES,
        label="tool schema",
    )
    try:
        serialized_schema = json.dumps(
            schema,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeError):
        raise ValueError("tool schema must be bounded JSON") from None
    if len(serialized_schema.encode("utf-8")) > _MAX_TOOL_SCHEMA_BYTES:
        raise ValueError("tool schema exceeds the size limit")
    return ToolDefinition(
        name=definition.name,
        description=definition.description,
        input_schema=schema,
        handler=definition.handler,
        allowed_roles=definition.allowed_roles,
        risk_level=definition.risk_level,
        has_side_effects=False,
        requires_approval=False,
    )


def _build_sdk_tool(
    registry: ToolRegistry,
    definition: ToolDefinition,
    run_context: OpenAIAgentsRunContext,
) -> FunctionTool:
    schema = copy.deepcopy(definition.input_schema)
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    strict = set(required) == set(properties)

    async def invoke(tool_context: ToolContext[Any], arguments_json: str) -> str:
        if tool_context.context is not run_context:
            return _safe_tool_payload(
                ToolResult(ok=False, error_code="tool_context_mismatch")
            )
        if tool_context.tool_name != definition.name:
            return _safe_tool_payload(
                ToolResult(ok=False, error_code="tool_context_mismatch")
            )
        call_id = tool_context.tool_call_id
        try:
            _required_identifier(
                call_id,
                "tool_call_id",
                max_length=200,
            )
        except ValueError:
            return _safe_tool_payload(
                ToolResult(ok=False, error_code="tool_call_id_missing")
            )
        if run_context.cancellation_token.is_cancelled:
            return _safe_tool_payload(
                ToolResult(ok=False, error_code="run_cancelled")
            )
        arguments = _decode_arguments(arguments_json)
        if arguments is None:
            return _safe_tool_payload(
                ToolResult(ok=False, error_code="invalid_arguments")
            )
        try:
            result = await asyncio.to_thread(
                registry.execute,
                definition.name,
                arguments,
                context=run_context.execution_context,
                call_id=call_id,
            )
        except Exception:
            result = ToolResult(ok=False, error_code="tool_execution_failed")
        if run_context.cancellation_token.is_cancelled:
            return _safe_tool_payload(
                ToolResult(ok=False, error_code="run_cancelled")
            )
        return _safe_tool_payload(result)

    def extract_custom_data(
        custom_context: FunctionToolCustomDataContext,
    ) -> dict[str, object]:
        if custom_context.tool_context.context is not run_context:
            return {"ok": False, "error_code": "tool_context_mismatch"}
        return _safe_custom_data(custom_context.output)

    return FunctionTool(
        name=definition.name,
        description=definition.description,
        params_json_schema=schema,
        on_invoke_tool=invoke,
        strict_json_schema=strict,
        custom_data_extractor=extract_custom_data,
    )


def _decode_arguments(arguments_json: object) -> dict[str, Any] | None:
    if not isinstance(arguments_json, str):
        return None
    try:
        if len(arguments_json.encode("utf-8")) > _MAX_TOOL_ARGUMENT_BYTES:
            return None
        value = json.loads(arguments_json)
    except (UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _safe_tool_payload(result: ToolResult) -> str:
    if result.ok:
        try:
            value = _bounded_json_value(result.value)
        except ValueError:
            return json.dumps(
                {"ok": False, "error_code": "tool_output_invalid"},
                separators=(",", ":"),
            )
        payload: dict[str, object] = {"ok": True, "value": value}
    else:
        payload = {
            "ok": False,
            "error_code": _safe_error_code(result.error_code),
        }
    try:
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(serialized.encode("utf-8")) <= _MAX_TOOL_OUTPUT_BYTES:
            return serialized
    except (TypeError, ValueError, UnicodeError):
        pass
    return json.dumps(
        {"ok": False, "error_code": "tool_output_invalid"},
        separators=(",", ":"),
    )


def _bounded_json_value(value: object) -> object:
    nodes = [0]
    byte_count = [0]
    normalized = _normalize_json_value(
        value,
        set(),
        nodes=nodes,
        byte_count=byte_count,
    )
    return normalized


def _ensure_bounded_json(
    value: object,
    *,
    max_bytes: int,
    label: str,
) -> None:
    nodes = [0]
    byte_count = [0]
    _measure_json_value(
        value,
        set(),
        nodes=nodes,
        byte_count=byte_count,
        max_bytes=max_bytes,
        label=label,
    )


def _measure_json_value(
    value: object,
    active_ids: set[int],
    *,
    nodes: list[int],
    byte_count: list[int],
    max_bytes: int,
    label: str,
    depth: int = 0,
) -> None:
    nodes[0] += 1
    if depth > _MAX_TOOL_JSON_DEPTH or nodes[0] > _MAX_TOOL_JSON_NODES:
        raise ValueError(f"{label} exceeds structural limits")
    if value is None or isinstance(value, (bool, int, float)):
        increment = len(repr(value))
    elif isinstance(value, str):
        if len(value) > max_bytes:
            raise ValueError(f"{label} exceeds the size limit")
        try:
            increment = len(value.encode("utf-8"))
        except UnicodeError:
            raise ValueError(f"{label} contains invalid Unicode") from None
    elif isinstance(value, dict):
        container_id = id(value)
        if container_id in active_ids:
            raise ValueError(f"{label} must not be cyclic")
        active_ids.add(container_id)
        try:
            increment = 2
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError(f"{label} keys must be strings")
                try:
                    increment += len(key.encode("utf-8"))
                except UnicodeError:
                    raise ValueError(
                        f"{label} contains invalid Unicode"
                    ) from None
                _measure_json_value(
                    item,
                    active_ids,
                    nodes=nodes,
                    byte_count=byte_count,
                    max_bytes=max_bytes,
                    label=label,
                    depth=depth + 1,
                )
        finally:
            active_ids.remove(container_id)
    elif isinstance(value, (list, tuple)):
        container_id = id(value)
        if container_id in active_ids:
            raise ValueError(f"{label} must not be cyclic")
        active_ids.add(container_id)
        try:
            increment = 2
            for item in value:
                _measure_json_value(
                    item,
                    active_ids,
                    nodes=nodes,
                    byte_count=byte_count,
                    max_bytes=max_bytes,
                    label=label,
                    depth=depth + 1,
                )
        finally:
            active_ids.remove(container_id)
    else:
        raise ValueError(f"{label} must contain JSON values")
    byte_count[0] += increment
    if byte_count[0] > max_bytes:
        raise ValueError(f"{label} exceeds the size limit")


def _normalize_json_value(
    value: object,
    active_ids: set[int],
    *,
    nodes: list[int],
    byte_count: list[int],
    depth: int = 0,
) -> object:
    nodes[0] += 1
    if depth > _MAX_TOOL_JSON_DEPTH or nodes[0] > _MAX_TOOL_JSON_NODES:
        raise ValueError("tool output exceeds structural limits")
    _add_json_bytes(byte_count, 1)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        _add_json_bytes(byte_count, len(str(value)))
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("tool output contains a non-finite number")
        _add_json_bytes(byte_count, len(repr(value)))
        return value
    if isinstance(value, str):
        if len(value) > _MAX_TOOL_OUTPUT_BYTES:
            raise ValueError("tool output exceeds the size limit")
        try:
            encoded_size = len(value.encode("utf-8"))
        except UnicodeError:
            raise ValueError("tool output contains invalid Unicode") from None
        _add_json_bytes(byte_count, encoded_size)
        return value
    if isinstance(value, dict):
        container_id = id(value)
        if container_id in active_ids:
            raise ValueError("tool output must not be cyclic")
        active_ids.add(container_id)
        try:
            normalized: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("tool output keys must be strings")
                if len(key) > _MAX_TOOL_OUTPUT_BYTES:
                    raise ValueError("tool output exceeds the size limit")
                try:
                    key_size = len(key.encode("utf-8"))
                except UnicodeError:
                    raise ValueError(
                        "tool output contains invalid Unicode"
                    ) from None
                _add_json_bytes(byte_count, key_size)
                normalized[key] = _normalize_json_value(
                    item,
                    active_ids,
                    nodes=nodes,
                    byte_count=byte_count,
                    depth=depth + 1,
                )
            return normalized
        finally:
            active_ids.remove(container_id)
    if isinstance(value, (list, tuple)):
        container_id = id(value)
        if container_id in active_ids:
            raise ValueError("tool output must not be cyclic")
        active_ids.add(container_id)
        try:
            return [
                _normalize_json_value(
                    item,
                    active_ids,
                    nodes=nodes,
                    byte_count=byte_count,
                    depth=depth + 1,
                )
                for item in value
            ]
        finally:
            active_ids.remove(container_id)
    raise ValueError("tool output must contain JSON values")


def _add_json_bytes(byte_count: list[int], amount: int) -> None:
    byte_count[0] += amount
    if byte_count[0] > _MAX_TOOL_OUTPUT_BYTES:
        raise ValueError("tool output exceeds the size limit")


def _safe_custom_data(output: object) -> dict[str, object]:
    if not isinstance(output, str):
        return {"ok": False, "error_code": "tool_output_invalid"}
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {"ok": False, "error_code": "tool_output_invalid"}
    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        return {"ok": False, "error_code": "tool_output_invalid"}
    if payload["ok"]:
        return {"ok": True}
    return {
        "ok": False,
        "error_code": _safe_error_code(payload.get("error_code")),
    }


def _safe_error_code(value: object) -> str:
    if (
        isinstance(value, str)
        and value
        and value == value.strip()
        and len(value) <= 100
        and all(character.isalnum() or character == "_" for character in value)
    ):
        return value
    return "tool_execution_failed"


def _required_identifier(
    value: object,
    label: str,
    *,
    max_length: int,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > max_length
        or any(character.isspace() or not character.isprintable() for character in value)
    ):
        raise ValueError(f"{label} has an invalid format")
    return value


__all__ = ["OpenAIAgentsRunContext", "build_sdk_tools"]
