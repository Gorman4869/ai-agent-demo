from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum, StrEnum
from threading import Lock
from typing import Any
from uuid import uuid4


ToolHandler = Callable[[dict[str, Any]], Any]
ApprovalClock = Callable[[], datetime]


class ToolRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ToolApproval:
    id: str
    principal_id: str
    tool_call_id: str
    tool_name: str
    arguments_digest: str
    expires_at: datetime | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    reason: str


class ApprovalResponse(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ApprovalResolutionStatus(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalResolutionError(RuntimeError):
    """Stable approval failure without request or argument disclosure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ToolApprovalRequest:
    id: str
    run_id: str
    principal_id: str
    tool_call_id: str
    tool_name: str
    arguments_digest: str = field(repr=False)
    expires_at: datetime | None = None


@dataclass(frozen=True)
class ToolApprovalResolution:
    request: ToolApprovalRequest
    status: ApprovalResolutionStatus


class InMemoryApprovalStore:
    """Own exact approval requests, decisions, and single-use grants."""

    def __init__(self, *, clock: ApprovalClock | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._approvals: dict[tuple[str, str, str, str, str], ToolApproval] = {}
        self._consumed: set[str] = set()
        self._requests: dict[str, ToolApprovalRequest] = {}
        self._request_keys: dict[tuple[str, str, str, str, str], str] = {}
        self._request_arguments: dict[str, dict[str, Any]] = {}
        self._resolutions: dict[str, ToolApprovalResolution] = {}
        self._responses: dict[str, ApprovalResponse] = {}
        self._lock = Lock()

    def grant(
        self,
        *,
        principal_id: str,
        run_id: str | None = None,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        expires_at: datetime | None = None,
    ) -> ToolApproval:
        if (
            expires_at is not None
            and (expires_at.tzinfo is None or expires_at.utcoffset() is None)
        ):
            raise ValueError("approval expires_at must be timezone-aware")
        approval = ToolApproval(
            id=str(uuid4()),
            principal_id=_required_name(principal_id, "principal_id"),
            run_id=(
                _required_name(run_id, "run_id")
                if run_id is not None
                else None
            ),
            tool_call_id=_required_name(tool_call_id, "tool_call_id"),
            tool_name=_required_name(tool_name, "tool_name"),
            arguments_digest=tool_arguments_digest(arguments),
            expires_at=expires_at,
        )
        key = _approval_key(approval)
        with self._lock:
            if key in self._approvals:
                raise ValueError("an approval already exists for this exact tool call")
            self._approvals[key] = approval
        return approval

    def request(
        self,
        *,
        run_id: str,
        principal_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        expires_in: timedelta | None = None,
    ) -> ToolApprovalRequest:
        if expires_in is not None and (
            not isinstance(expires_in, timedelta)
            or expires_in <= timedelta(0)
        ):
            raise ValueError("approval expires_in must be positive")
        checked_run_id = _required_name(run_id, "run_id")
        checked_principal_id = _required_name(principal_id, "principal_id")
        checked_call_id = _required_name(tool_call_id, "tool_call_id")
        checked_tool_name = _required_name(tool_name, "tool_name")
        detached_arguments = _detached_arguments(arguments)
        arguments_digest = tool_arguments_digest(detached_arguments)
        request_key = (
            checked_run_id,
            checked_principal_id,
            checked_call_id,
            checked_tool_name,
            arguments_digest,
        )
        with self._lock:
            existing_id = self._request_keys.get(request_key)
            if existing_id is not None:
                return self._requests[existing_id]
            now = _aware_utc(self._clock())
            request = ToolApprovalRequest(
                id=str(uuid4()),
                run_id=checked_run_id,
                principal_id=checked_principal_id,
                tool_call_id=checked_call_id,
                tool_name=checked_tool_name,
                arguments_digest=arguments_digest,
                expires_at=(now + expires_in if expires_in is not None else None),
            )
            self._requests[request.id] = request
            self._request_keys[request_key] = request.id
            self._request_arguments[request.id] = detached_arguments
            return request

    def resolve(
        self,
        *,
        approval_id: str,
        run_id: str,
        principal_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments_digest: str,
        decision: ApprovalResponse | str,
    ) -> ToolApprovalResolution:
        response = _approval_response(decision)
        checked_id = _required_name(approval_id, "approval_id")
        binding = (
            _required_name(run_id, "run_id"),
            _required_name(principal_id, "principal_id"),
            _required_name(tool_call_id, "tool_call_id"),
            _required_name(tool_name, "tool_name"),
            arguments_digest,
        )
        with self._lock:
            request = self._requests.get(checked_id)
            if request is None or request.principal_id != binding[1]:
                raise ApprovalResolutionError("approval_request_not_found")
            if _request_key(request) != binding:
                raise ApprovalResolutionError("approval_binding_mismatch")
            existing = self._resolutions.get(checked_id)
            if existing is not None:
                if self._responses[checked_id] is not response:
                    raise ApprovalResolutionError("approval_decision_conflict")
                return existing

            status = (
                ApprovalResolutionStatus.EXPIRED
                if request.expires_at is not None
                and _aware_utc(self._clock()) >= request.expires_at
                else (
                    ApprovalResolutionStatus.APPROVED
                    if response is ApprovalResponse.APPROVE
                    else ApprovalResolutionStatus.REJECTED
                )
            )
            resolution = ToolApprovalResolution(request=request, status=status)
            self._resolutions[checked_id] = resolution
            self._responses[checked_id] = response
            if status is ApprovalResolutionStatus.APPROVED:
                approval = ToolApproval(
                    id=request.id,
                    principal_id=request.principal_id,
                    run_id=request.run_id,
                    tool_call_id=request.tool_call_id,
                    tool_name=request.tool_name,
                    arguments_digest=request.arguments_digest,
                    expires_at=request.expires_at,
                )
                self._approvals[_approval_key(approval)] = approval
            return resolution

    def get_resolution(
        self,
        *,
        approval_id: str,
        run_id: str,
        principal_id: str,
    ) -> ToolApprovalResolution | None:
        with self._lock:
            resolution = self._resolutions.get(approval_id)
            if (
                resolution is None
                or resolution.request.run_id != run_id
                or resolution.request.principal_id != principal_id
            ):
                return None
            return resolution

    def approved_arguments(
        self,
        resolution: ToolApprovalResolution,
    ) -> dict[str, Any]:
        if resolution.status is not ApprovalResolutionStatus.APPROVED:
            raise ApprovalResolutionError("approval_not_approved")
        with self._lock:
            stored = self._resolutions.get(resolution.request.id)
            if stored != resolution:
                raise ApprovalResolutionError("approval_resolution_mismatch")
            arguments = self._request_arguments.get(resolution.request.id)
            if arguments is None:
                raise ApprovalResolutionError("approval_arguments_unavailable")
            return _detached_arguments(arguments)

    def consume(
        self,
        *,
        principal_id: str,
        run_id: str | None = None,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> ApprovalDecision:
        key = (
            principal_id,
            run_id or "",
            tool_call_id,
            tool_name,
            tool_arguments_digest(arguments),
        )
        with self._lock:
            approval = self._approvals.get(key)
            if approval is None:
                return ApprovalDecision(False, "exact_call_approval_missing")
            if approval.id in self._consumed:
                return ApprovalDecision(False, "approval_already_consumed")
            if approval.expires_at is not None and self._clock() >= approval.expires_at:
                return ApprovalDecision(False, "approval_expired")
            self._consumed.add(approval.id)
        return ApprovalDecision(True, "approved")


@dataclass(frozen=True)
class ToolExecutionContext:
    """Trusted caller identity and approvals for one tool execution boundary.

    The application layer must build this context from authenticated state and
    approval records. Tool arguments are deliberately excluded from it.
    """

    principal_id: str = "anonymous"
    roles: frozenset[str] = field(default_factory=frozenset)
    approval_store: InMemoryApprovalStore | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    run_id: str | None = None

    def __post_init__(self) -> None:
        principal_id = self.principal_id.strip()
        if not principal_id:
            raise ValueError("principal_id must not be empty")
        object.__setattr__(self, "principal_id", principal_id)
        object.__setattr__(self, "roles", _normalize_names(self.roles, "role"))
        if self.run_id is not None:
            object.__setattr__(self, "run_id", _required_name(self.run_id, "run_id"))

    def for_run(self, run_id: str) -> ToolExecutionContext:
        checked_run_id = _required_name(run_id, "run_id")
        if self.run_id is not None and self.run_id != checked_run_id:
            raise ValueError("execution context run_id does not match")
        return ToolExecutionContext(
            principal_id=self.principal_id,
            roles=self.roles,
            run_id=checked_run_id,
            approval_store=self.approval_store,
        )


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    allowed_roles: frozenset[str] = field(default_factory=frozenset)
    risk_level: ToolRisk = ToolRisk.LOW
    has_side_effects: bool = False
    requires_approval: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "allowed_roles",
            _normalize_names(self.allowed_roles, "allowed role"),
        )
        if not isinstance(self.risk_level, ToolRisk):
            object.__setattr__(self, "risk_level", ToolRisk(self.risk_level))
        _validate_schema_definition(self.input_schema)

    @property
    def approval_required(self) -> bool:
        """Return the effective policy; mandatory controls cannot be disabled."""
        return (
            self.requires_approval
            or self.has_side_effects
            or self.risk_level is ToolRisk.HIGH
        )


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    value: Any = None
    error_code: str | None = None
    error_message: str | None = None
    error_details: dict[str, Any] | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def definitions(
        self,
        *,
        context: ToolExecutionContext | None = None,
    ) -> tuple[ToolDefinition, ...]:
        execution_context = context or ToolExecutionContext()
        return tuple(
            tool
            for tool in self._tools.values()
            if not tool.allowed_roles
            or not tool.allowed_roles.isdisjoint(execution_context.roles)
        )

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        context: ToolExecutionContext | None = None,
        call_id: str | None = None,
    ) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                ok=False,
                error_code="unknown_tool",
                error_message=f"Unknown tool: {name}",
            )

        execution_context = context or ToolExecutionContext()
        denied = _authorize(
            tool,
            execution_context,
            call_id=call_id,
            arguments=arguments,
        )
        if denied is not None:
            return denied

        validation_error = _validate_arguments(arguments, tool.input_schema)
        if validation_error:
            return ToolResult(
                ok=False,
                error_code="invalid_arguments",
                error_message=validation_error,
            )

        try:
            return ToolResult(ok=True, value=tool.handler(arguments))
        except TimeoutError:
            return ToolResult(
                ok=False,
                error_code="tool_timeout",
                error_message=f"Tool timed out: {tool.name}",
            )
        except PermissionError:
            return ToolResult(
                ok=False,
                error_code="tool_permission_error",
                error_message=f"Tool permission error: {tool.name}",
            )
        except OSError:
            return ToolResult(
                ok=False,
                error_code="tool_io_error",
                error_message=f"Tool I/O error: {tool.name}",
            )
        except (TypeError, ValueError):
            return ToolResult(
                ok=False,
                error_code="tool_execution_failed",
                error_message=f"Tool execution failed: {tool.name}",
            )


def _authorize(
    tool: ToolDefinition,
    context: ToolExecutionContext,
    *,
    call_id: str | None,
    arguments: Mapping[str, Any],
) -> ToolResult | None:
    if tool.allowed_roles and tool.allowed_roles.isdisjoint(context.roles):
        return ToolResult(
            ok=False,
            error_code="permission_denied",
            error_message=f"Permission denied for tool: {tool.name}",
            error_details={
                "reason": "role_not_allowed",
                "tool_name": tool.name,
                "principal_id": context.principal_id,
                "required_roles": sorted(tool.allowed_roles),
                "actual_roles": sorted(context.roles),
            },
        )

    if tool.approval_required:
        if call_id is None or context.approval_store is None:
            return _approval_denied(tool, context, "exact_call_approval_missing")
        try:
            decision = context.approval_store.consume(
                principal_id=context.principal_id,
                run_id=context.run_id,
                tool_call_id=call_id,
                tool_name=tool.name,
                arguments=arguments,
            )
        except ValueError:
            return _approval_denied(tool, context, "arguments_not_approvable")
        if not decision.approved:
            return _approval_denied(tool, context, decision.reason)

    return None


def _validate_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> str | None:
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for field_name in required:
        if field_name not in arguments:
            return f"Missing required argument: {field_name}"

    for field_name, value in arguments.items():
        field_schema = properties.get(field_name)
        if field_schema is None:
            return f"Unexpected argument: {field_name}"

        expected_type = field_schema.get("type")
        if expected_type == "number" and not _is_number(value):
            return f"Argument {field_name} must be a number"
        if expected_type == "integer" and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return f"Argument {field_name} must be an integer"
        if expected_type == "string" and not isinstance(value, str):
            return f"Argument {field_name} must be a string"
        if expected_type == "boolean" and not isinstance(value, bool):
            return f"Argument {field_name} must be a boolean"
        if "enum" in field_schema and value not in field_schema["enum"]:
            return f"Argument {field_name} must be one of {field_schema['enum']!r}"
        if isinstance(value, str):
            if len(value) < field_schema.get("minLength", 0):
                return f"Argument {field_name} is shorter than minLength"
            if len(value) > field_schema.get("maxLength", math.inf):
                return f"Argument {field_name} is longer than maxLength"
            pattern = field_schema.get("pattern")
            if pattern is not None and re.fullmatch(pattern, value) is None:
                return f"Argument {field_name} does not match pattern"
        if _is_number(value):
            if "minimum" in field_schema and value < field_schema["minimum"]:
                return f"Argument {field_name} is below minimum"
            if "maximum" in field_schema and value > field_schema["maximum"]:
                return f"Argument {field_name} is above maximum"

    return None


def _normalize_names(values: frozenset[str], label: str) -> frozenset[str]:
    normalized = frozenset(value.strip() for value in values)
    if "" in normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _approval_denied(
    tool: ToolDefinition,
    context: ToolExecutionContext,
    reason: str,
) -> ToolResult:
    return ToolResult(
        ok=False,
        error_code="approval_required",
        error_message=f"Explicit approval required for tool: {tool.name}",
        error_details={
            "reason": reason,
            "tool_name": tool.name,
            "principal_id": context.principal_id,
            "risk_level": tool.risk_level.value,
            "has_side_effects": tool.has_side_effects,
        },
    )


def tool_arguments_digest(arguments: Mapping[str, Any]) -> str:
    try:
        payload = json.dumps(
            dict(arguments),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("tool arguments must be JSON serializable") from error
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _approval_key(approval: ToolApproval) -> tuple[str, str, str, str, str]:
    return (
        approval.principal_id,
        approval.run_id or "",
        approval.tool_call_id,
        approval.tool_name,
        approval.arguments_digest,
    )


def _request_key(
    request: ToolApprovalRequest,
) -> tuple[str, str, str, str, str]:
    return (
        request.run_id,
        request.principal_id,
        request.tool_call_id,
        request.tool_name,
        request.arguments_digest,
    )


def _approval_response(value: ApprovalResponse | str) -> ApprovalResponse:
    if isinstance(value, bool):
        raise ValueError("approval decision must be approve or reject")
    try:
        return ApprovalResponse(value)
    except (TypeError, ValueError):
        raise ValueError("approval decision must be approve or reject") from None


def _aware_utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("approval clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


def _detached_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, Mapping):
        raise ValueError("tool arguments must be a mapping")
    try:
        payload = json.dumps(
            dict(arguments),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        detached = json.loads(payload)
    except (TypeError, ValueError) as error:
        raise ValueError("tool arguments must be JSON serializable") from error
    if not isinstance(detached, dict):
        raise ValueError("tool arguments must be an object")
    return detached


def _required_name(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _validate_schema_definition(schema: Mapping[str, Any]) -> None:
    allowed_root = {"type", "properties", "required", "additionalProperties"}
    unsupported_root = set(schema) - allowed_root
    if unsupported_root:
        raise ValueError(f"Unsupported tool schema keywords: {sorted(unsupported_root)}")
    if schema.get("type") != "object":
        raise ValueError("Tool input schema type must be object")
    properties = schema.get("properties")
    required = schema.get("required", [])
    if not isinstance(properties, dict):
        raise ValueError("Tool input schema properties must be an object")
    if not isinstance(required, list) or not all(
        isinstance(name, str) for name in required
    ):
        raise ValueError("Tool input schema required must be a string array")
    if any(name not in properties for name in required):
        raise ValueError("Tool input schema required fields must exist in properties")
    if (
        "additionalProperties" in schema
        and schema["additionalProperties"] is not False
    ):
        raise ValueError("Tool input schema does not allow additionalProperties")
    if len(required) != len(set(required)):
        raise ValueError("Tool input schema required fields must be unique")

    allowed_property = {
        "type",
        "enum",
        "minLength",
        "maxLength",
        "pattern",
        "minimum",
        "maximum",
    }
    supported_types = {"string", "number", "integer", "boolean"}
    for name, field_schema in properties.items():
        if not isinstance(name, str) or not isinstance(field_schema, dict):
            raise ValueError("Tool property schemas must be named objects")
        unsupported = set(field_schema) - allowed_property
        if unsupported:
            raise ValueError(
                f"Unsupported schema keywords for {name}: {sorted(unsupported)}"
            )
        if field_schema.get("type") not in supported_types:
            raise ValueError(f"Unsupported schema type for {name}")
        field_type = field_schema["type"]
        enum_values = field_schema.get("enum")
        if enum_values is not None:
            if not isinstance(enum_values, list) or not enum_values:
                raise ValueError(f"Schema enum for {name} must be a non-empty array")
            if any(not _matches_schema_type(value, field_type) for value in enum_values):
                raise ValueError(f"Schema enum values for {name} have invalid types")
        string_keywords = {"minLength", "maxLength", "pattern"} & set(field_schema)
        if string_keywords and field_type != "string":
            raise ValueError(f"String schema keywords require string type for {name}")
        numeric_keywords = {"minimum", "maximum"} & set(field_schema)
        if numeric_keywords and field_type not in {"number", "integer"}:
            raise ValueError(f"Numeric schema keywords require numeric type for {name}")
        if field_type == "string":
            min_length = field_schema.get("minLength", 0)
            max_length = field_schema.get("maxLength", math.inf)
            if (
                not isinstance(min_length, int)
                or isinstance(min_length, bool)
                or min_length < 0
                or (
                    "maxLength" in field_schema
                    and (
                        not isinstance(max_length, int)
                        or isinstance(max_length, bool)
                        or max_length < min_length
                    )
                )
            ):
                raise ValueError(f"Invalid string length constraints for {name}")
        if field_type in {"number", "integer"}:
            minimum = field_schema.get("minimum", -math.inf)
            maximum = field_schema.get("maximum", math.inf)
            if (
                ("minimum" in field_schema and not _is_number(minimum))
                or ("maximum" in field_schema and not _is_number(maximum))
                or minimum > maximum
            ):
                raise ValueError(f"Invalid numeric constraints for {name}")
        if "pattern" in field_schema:
            if not isinstance(field_schema["pattern"], str):
                raise ValueError(f"Invalid schema pattern for {name}")
            try:
                re.compile(field_schema["pattern"])
            except (re.error, TypeError) as error:
                raise ValueError(f"Invalid schema pattern for {name}") from error


def _matches_schema_type(value: object, schema_type: str) -> bool:
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "number":
        return _is_number(value)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    return False
