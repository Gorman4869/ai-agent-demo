from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Literal
from urllib.parse import SplitResult, urlsplit

from backend.app.advanced.harness import (
    PolicyViolation,
    SafetyBudget,
    SafetyLimits,
    content_digest,
)
from backend.app.tools.registry import ToolExecutionContext

if TYPE_CHECKING:
    from backend.app.advanced.browser_driver import BrowserDriver, BrowserDriverRun


class BrowserActionKind(str, Enum):
    NAVIGATE = "navigate"
    READ_TEXT = "read_text"
    CLICK = "click"
    TYPE = "type"
    SUBMIT = "submit"


_FORBIDDEN_ACTIONS = frozenset(
    {
        "download",
        "eval",
        "evaluate",
        "evaluate_script",
        "execute_script",
        "upload",
    }
)
_SIDE_EFFECT_ACTIONS = frozenset(
    {BrowserActionKind.CLICK, BrowserActionKind.TYPE, BrowserActionKind.SUBMIT}
)
_SENSITIVE_FIELDS = frozenset(
    {
        "authorization",
        "cookie",
        "credentials",
        "headers",
        "javascript",
        "password",
        "script",
        "secret",
        "selector",
        "token",
    }
)
_SENSITIVE_ELEMENT = re.compile(
    r"(?:auth|cookie|credit.?card|password|passwd|secret|token)",
    re.IGNORECASE,
)
_ACTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
_ELEMENT_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}")
_CONTENT_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class BrowserAction:
    id: str
    kind: BrowserActionKind
    origin: str
    url: str | None = field(default=None, repr=False)
    element_id: str | None = None
    value: str | None = field(default=None, repr=False)
    expected_page_digest: str | None = None
    page_url: str = field(default="", repr=False)

    @property
    def requires_approval(self) -> bool:
        return self.kind in _SIDE_EFFECT_ACTIONS


@dataclass(frozen=True)
class BrowserPlan:
    actions: tuple[BrowserAction, ...]
    policy_digest: str
    plan_digest: str


@dataclass(frozen=True)
class BrowserActionResult:
    action_id: str
    kind: str
    origin: str
    simulated: Literal[True]
    details: dict[str, object]


@dataclass(frozen=True)
class BrowserRun:
    actions: tuple[BrowserActionResult, ...]
    final_origin: str
    offline: Literal[True] = True


class BrowserAgent:
    """Validate and simulate browser plans without opening a browser or network."""

    def __init__(
        self,
        *,
        allowed_origins: Sequence[str],
        allowed_element_ids: Sequence[str] = (),
        max_actions: int = 12,
        max_plan_bytes: int = 100_000,
    ) -> None:
        for field_name, value in (
            ("max_actions", max_actions),
            ("max_plan_bytes", max_plan_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        origins = frozenset(_parse_allowed_origin(value) for value in allowed_origins)
        if not origins:
            raise ValueError("allowed_origins must not be empty")
        elements = frozenset(
            _validate_configured_element_id(value) for value in allowed_element_ids
        )
        self._allowed_origins = origins
        self._allowed_element_ids = elements
        self._max_actions = max_actions
        self._max_plan_bytes = max_plan_bytes
        policy_payload = json.dumps(
            {
                "origins": sorted(origins),
                "elements": sorted(elements),
                "max_actions": max_actions,
                "max_plan_bytes": max_plan_bytes,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self._policy_digest = content_digest(policy_payload)

    @property
    def offline(self) -> bool:
        return True

    def validate_plan(
        self,
        raw_actions: Sequence[Mapping[str, object]],
    ) -> BrowserPlan:
        if isinstance(raw_actions, (str, bytes)) or not isinstance(
            raw_actions, Sequence
        ):
            raise PolicyViolation(
                "invalid_browser_plan",
                "browser plan must be an action array",
            )
        if not raw_actions:
            raise PolicyViolation(
                "invalid_browser_plan",
                "browser plan must contain at least one action",
            )

        budget = SafetyBudget(
            SafetyLimits(
                max_actions=self._max_actions,
                max_input_bytes=self._max_plan_bytes,
                max_output_bytes=1,
            )
        )
        actions: list[BrowserAction] = []
        action_ids: set[str] = set()
        current_origin: str | None = None
        current_url: str | None = None
        for raw_action in raw_actions:
            encoded = _encode_raw_action(raw_action)
            budget.consume(input_bytes=len(encoded))
            action, current_origin, current_url = self._validate_action(
                raw_action,
                current_origin=current_origin,
                current_url=current_url,
            )
            if action.id in action_ids:
                raise PolicyViolation(
                    "invalid_browser_action",
                    "browser action ids must be unique",
                )
            action_ids.add(action.id)
            actions.append(action)

        frozen_actions = tuple(actions)
        return BrowserPlan(
            frozen_actions,
            self._policy_digest,
            _browser_plan_digest(frozen_actions),
        )

    def run(
        self,
        plan: BrowserPlan,
        *,
        context: ToolExecutionContext | None = None,
    ) -> BrowserRun:
        validated_plan = self._revalidate_plan(plan)
        execution_context = context or ToolExecutionContext()
        results: list[BrowserActionResult] = []
        for action in validated_plan.actions:
            if action.requires_approval:
                _consume_action_approval(
                    action,
                    plan_digest=validated_plan.plan_digest,
                    context=execution_context,
                )
            results.append(_simulate_action(action))
        return BrowserRun(
            actions=tuple(results),
            final_origin=validated_plan.actions[-1].origin,
        )

    def run_with_driver(
        self,
        plan: BrowserPlan,
        *,
        driver: BrowserDriver,
        context: ToolExecutionContext | None = None,
    ) -> BrowserDriverRun:
        """Execute a revalidated plan through an explicitly injected driver."""

        validated_plan = self._revalidate_plan(plan)
        driver.validate(validated_plan.actions)
        execution_context = context or ToolExecutionContext()
        for action in validated_plan.actions:
            if action.requires_approval:
                _consume_action_approval(
                    action,
                    plan_digest=validated_plan.plan_digest,
                    context=execution_context,
                )
        return driver.execute(validated_plan.actions)

    def _revalidate_plan(self, plan: BrowserPlan) -> BrowserPlan:
        if not isinstance(plan, BrowserPlan) or plan.policy_digest != self._policy_digest:
            raise PolicyViolation(
                "invalid_browser_plan",
                "browser plan was not validated by this policy",
            )
        if not isinstance(plan.actions, tuple) or not all(
            isinstance(action, BrowserAction) for action in plan.actions
        ):
            raise PolicyViolation(
                "invalid_browser_plan",
                "browser plan contains invalid compiled actions",
            )
        try:
            canonical_plan = self.validate_plan(
                [_raw_action_from_compiled(action) for action in plan.actions]
            )
        except (AttributeError, PolicyViolation) as error:
            raise PolicyViolation(
                "invalid_browser_plan",
                "browser plan failed execution-boundary validation",
            ) from error
        if canonical_plan != plan:
            raise PolicyViolation(
                "invalid_browser_plan",
                "browser plan does not match its canonical validation result",
            )
        return canonical_plan

    def _validate_action(
        self,
        raw_action: Mapping[str, object],
        *,
        current_origin: str | None,
        current_url: str | None,
    ) -> tuple[BrowserAction, str, str]:
        if not isinstance(raw_action, Mapping):
            raise PolicyViolation(
                "invalid_browser_action",
                "browser action must be an object",
            )
        keys = set(raw_action)
        if not all(isinstance(key, str) for key in keys):
            raise PolicyViolation(
                "invalid_browser_action",
                "browser action fields must be strings",
            )

        action_id = _required_string(raw_action.get("id"), "id")
        if _ACTION_ID.fullmatch(action_id) is None:
            raise PolicyViolation(
                "invalid_browser_action",
                "browser action id must be a stable opaque identifier",
            )
        kind_value = _required_string(raw_action.get("kind"), "kind")
        if kind_value in _FORBIDDEN_ACTIONS:
            raise PolicyViolation(
                "forbidden_browser_action",
                f"browser action is disabled: {kind_value}",
            )
        if blocked := {key for key in keys if key.lower() in _SENSITIVE_FIELDS}:
            raise PolicyViolation(
                "sensitive_browser_field",
                f"browser action contains forbidden fields: {sorted(blocked)}",
            )
        try:
            kind = BrowserActionKind(kind_value)
        except ValueError as error:
            raise PolicyViolation(
                "invalid_browser_action",
                f"unsupported browser action: {kind_value}",
            ) from error

        required_fields, allowed_fields = _action_fields(kind)
        if missing := required_fields - keys:
            raise PolicyViolation(
                "invalid_browser_action",
                f"browser action is missing fields: {sorted(missing)}",
            )
        if unexpected := keys - allowed_fields:
            raise PolicyViolation(
                "invalid_browser_action",
                f"browser action contains unexpected fields: {sorted(unexpected)}",
            )

        if kind is BrowserActionKind.NAVIGATE:
            url = canonical_browser_url(
                _required_string(raw_action.get("url"), "url")
            )
            origin = _origin_for_url(url)
            if origin not in self._allowed_origins:
                raise PolicyViolation(
                    "origin_not_allowed",
                    "browser URL origin is not allowlisted",
                )
            return (
                BrowserAction(
                    action_id,
                    kind,
                    origin,
                    url=url,
                    page_url=url,
                ),
                origin,
                url,
            )

        if current_origin is None or current_url is None:
            raise PolicyViolation(
                "navigation_required",
                "navigate to an allowlisted origin before DOM actions",
            )
        element_id = _required_string(raw_action.get("element_id"), "element_id")
        if _SENSITIVE_ELEMENT.search(element_id):
            raise PolicyViolation(
                "sensitive_browser_field",
                "sensitive browser elements are disabled",
            )
        if element_id not in self._allowed_element_ids:
            raise PolicyViolation(
                "element_not_allowed",
                "browser element id is not allowlisted",
            )
        value = None
        if kind is BrowserActionKind.TYPE:
            value = _required_string(raw_action.get("value"), "value", allow_empty=True)
        expected_page_digest = raw_action.get("expected_page_digest")
        if expected_page_digest is not None and (
            not isinstance(expected_page_digest, str)
            or _CONTENT_DIGEST.fullmatch(expected_page_digest) is None
        ):
            raise PolicyViolation(
                "invalid_browser_action",
                "expected page digest must be a lowercase SHA-256 value",
            )
        return (
            BrowserAction(
                action_id,
                kind,
                current_origin,
                element_id=element_id,
                value=value,
                expected_page_digest=expected_page_digest,
                page_url=current_url,
            ),
            current_origin,
            current_url,
        )


def browser_approval_arguments(
    action: BrowserAction,
    *,
    plan_digest: str,
) -> dict[str, object]:
    """Return the canonical, non-secret arguments for an exact approval."""

    if (
        not isinstance(plan_digest, str)
        or _CONTENT_DIGEST.fullmatch(plan_digest) is None
        or not action.page_url
    ):
        raise ValueError("browser approval requires a canonical plan and page URL")

    arguments: dict[str, object] = {
        "kind": action.kind.value,
        "origin": action.origin,
        "element_id": action.element_id or "",
        "url_sha256": content_digest(action.page_url),
        "url_bytes": len(action.page_url.encode("utf-8")),
        "plan_digest": plan_digest,
    }
    if action.value is not None:
        value_bytes = action.value.encode("utf-8")
        arguments["value_sha256"] = content_digest(value_bytes)
        arguments["value_bytes"] = len(value_bytes)
    if action.expected_page_digest is not None:
        arguments["expected_page_digest"] = action.expected_page_digest
    return arguments


def _consume_action_approval(
    action: BrowserAction,
    *,
    plan_digest: str,
    context: ToolExecutionContext,
) -> None:
    if context.approval_store is None:
        raise PolicyViolation(
            "approval_required",
            f"exact approval is missing for browser.{action.kind.value}",
        )
    decision = context.approval_store.consume(
        principal_id=context.principal_id,
        tool_call_id=action.id,
        tool_name=f"browser.{action.kind.value}",
        arguments=browser_approval_arguments(action, plan_digest=plan_digest),
    )
    if not decision.approved:
        raise PolicyViolation("approval_required", decision.reason)


def _simulate_action(action: BrowserAction) -> BrowserActionResult:
    details: dict[str, object] = {
        "page_url_sha256": content_digest(action.page_url),
    }
    if action.url is not None:
        details["url_sha256"] = content_digest(action.url)
    if action.element_id is not None:
        details["element_id"] = action.element_id
    if action.value is not None:
        value_bytes = action.value.encode("utf-8")
        details["value_sha256"] = content_digest(value_bytes)
        details["value_bytes"] = len(value_bytes)
    if action.expected_page_digest is not None:
        details["expected_page_digest"] = action.expected_page_digest
    return BrowserActionResult(
        action_id=action.id,
        kind=action.kind.value,
        origin=action.origin,
        simulated=True,
        details=details,
    )


def _raw_action_from_compiled(action: BrowserAction) -> dict[str, object]:
    if not isinstance(action.kind, BrowserActionKind):
        raise PolicyViolation(
            "invalid_browser_plan",
            "compiled browser action kind is invalid",
        )
    raw_action: dict[str, object] = {
        "id": action.id,
        "kind": action.kind.value,
    }
    if action.kind is BrowserActionKind.NAVIGATE:
        raw_action["url"] = action.url
    else:
        raw_action["element_id"] = action.element_id
        if action.kind is BrowserActionKind.TYPE:
            raw_action["value"] = action.value
        if action.expected_page_digest is not None:
            raw_action["expected_page_digest"] = action.expected_page_digest
    return raw_action


def _encode_raw_action(raw_action: object) -> bytes:
    try:
        payload = json.dumps(
            raw_action,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise PolicyViolation(
            "invalid_browser_action",
            "browser action must be JSON serializable",
        ) from error
    return payload.encode("utf-8")


def _action_fields(
    kind: BrowserActionKind,
) -> tuple[frozenset[str], frozenset[str]]:
    if kind is BrowserActionKind.NAVIGATE:
        fields = frozenset({"id", "kind", "url"})
        return fields, fields
    if kind is BrowserActionKind.TYPE:
        required = frozenset({"id", "kind", "element_id", "value"})
        return required, required | {"expected_page_digest"}
    required = frozenset({"id", "kind", "element_id"})
    return required, required | {"expected_page_digest"}


def _parse_allowed_origin(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("allowed origin must be a string")
    parts = _split_https_url(value)
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise PolicyViolation(
            "invalid_browser_origin",
            "allowlist entries must contain only an HTTPS origin",
        )
    return _canonical_origin(parts)


def canonical_browser_url(value: str) -> str:
    """Canonicalize one full HTTPS URL without resolving its hostname."""

    parts = _split_https_url(value)
    if parts.fragment:
        raise PolicyViolation(
            "browser_fragment_not_allowed",
            "browser URL fragments are disabled",
        )
    origin = _canonical_origin(parts)
    path = parts.path or "/"
    query = f"?{parts.query}" if parts.query else ""
    return f"{origin}{path}{query}"


def _origin_for_url(value: str) -> str:
    return _canonical_origin(_split_https_url(value))


def _browser_plan_digest(actions: Sequence[BrowserAction]) -> str:
    payload: list[dict[str, object]] = []
    for action in actions:
        item: dict[str, object] = {
            "id": action.id,
            "kind": action.kind.value,
            "origin": action.origin,
            "page_url": action.page_url,
        }
        if action.url is not None:
            item["url"] = action.url
        if action.element_id is not None:
            item["element_id"] = action.element_id
        if action.value is not None:
            encoded_value = action.value.encode("utf-8")
            item["value_sha256"] = content_digest(encoded_value)
            item["value_bytes"] = len(encoded_value)
        if action.expected_page_digest is not None:
            item["expected_page_digest"] = action.expected_page_digest
        payload.append(item)
    return content_digest(
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )


def _split_https_url(value: str) -> SplitResult:
    if not isinstance(value, str) or not value or value != value.strip():
        raise PolicyViolation("invalid_browser_url", "browser URL is invalid")
    if "\\" in value or any(ord(character) < 32 for character in value):
        raise PolicyViolation("invalid_browser_url", "browser URL is invalid")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as error:
        raise PolicyViolation("invalid_browser_url", "browser URL is invalid") from error
    if parts.scheme.lower() != "https":
        raise PolicyViolation(
            "browser_scheme_not_allowed",
            "only HTTPS browser URLs are allowed",
        )
    if parts.username is not None or parts.password is not None:
        raise PolicyViolation(
            "browser_credentials_not_allowed",
            "credentials in browser URLs are disabled",
        )
    if parts.hostname is None or parts.netloc.endswith(":"):
        raise PolicyViolation("invalid_browser_url", "browser URL is invalid")
    return parts


def _canonical_origin(parts: SplitResult) -> str:
    host = parts.hostname
    if host is None:
        raise PolicyViolation("invalid_browser_url", "browser URL has no host")
    if host.endswith("."):
        raise PolicyViolation("invalid_browser_url", "trailing-dot hosts are disabled")
    try:
        canonical_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise PolicyViolation("invalid_browser_url", "browser host is invalid") from error
    if canonical_host == "localhost" or canonical_host.endswith(".localhost"):
        raise PolicyViolation(
            "browser_localhost_not_allowed",
            "localhost browser URLs are disabled",
        )
    try:
        address = ipaddress.ip_address(canonical_host)
    except ValueError:
        address = None
    if address is not None and address.is_loopback:
        raise PolicyViolation(
            "browser_localhost_not_allowed",
            "loopback browser URLs are disabled",
        )
    port = parts.port
    rendered_host = f"[{canonical_host}]" if ":" in canonical_host else canonical_host
    return f"https://{rendered_host}" if port in (None, 443) else f"https://{rendered_host}:{port}"


def _validate_configured_element_id(value: str) -> str:
    if not isinstance(value, str) or _ELEMENT_ID.fullmatch(value) is None:
        raise ValueError("allowed element ids must use stable opaque identifiers")
    if _SENSITIVE_ELEMENT.search(value):
        raise ValueError("sensitive element ids cannot be allowlisted")
    return value


def _required_string(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise PolicyViolation(
            "invalid_browser_action",
            f"browser action field must be a string: {field_name}",
        )
    if len(value.encode("utf-8")) > 16_384:
        raise PolicyViolation(
            "invalid_browser_action",
            f"browser action field is too large: {field_name}",
        )
    return value
