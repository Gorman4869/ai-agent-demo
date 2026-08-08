from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from backend.app.tools import ApprovalStore, InMemoryApprovalStore, ToolExecutionContext


AUTH_CONFIG_ENV = "AI_AGENT_DEMO_AUTH_JSON"


class AuthenticationError(ValueError):
    """Raised when a supplied bearer credential cannot be trusted."""


@dataclass(frozen=True)
class Principal:
    principal_id: str
    roles: frozenset[str] = field(default_factory=frozenset)
    approval_store: ApprovalStore | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    authenticated: bool = True

    def __post_init__(self) -> None:
        principal_id = self.principal_id.strip()
        if not principal_id:
            raise ValueError("principal_id must not be empty")
        object.__setattr__(self, "principal_id", principal_id)
        object.__setattr__(self, "roles", _normalize_names(self.roles, "role"))

    def to_tool_context(self) -> ToolExecutionContext:
        return ToolExecutionContext(
            principal_id=self.principal_id,
            roles=self.roles,
            approval_store=self.approval_store,
        )


class StaticTokenAuthenticator:
    """Resolve bearer tokens through server-owned configuration.

    This is intentionally a small teaching adapter. A production application
    should replace it with verified sessions or an OIDC/JWT adapter.
    """

    def __init__(self, principals_by_token: Mapping[str, Principal] | None = None) -> None:
        principals = dict(principals_by_token or {})
        if any(not token.strip() for token in principals):
            raise ValueError("authentication token must not be empty")
        if any(not principal.authenticated for principal in principals.values()):
            raise ValueError("configured token principal must be authenticated")
        self._principals_by_token = principals

    @classmethod
    def from_environment(
        cls,
        *,
        approval_store: ApprovalStore | None = None,
    ) -> StaticTokenAuthenticator:
        raw_config = os.getenv(AUTH_CONFIG_ENV)
        if raw_config is None or not raw_config.strip():
            return cls()
        try:
            config = json.loads(raw_config)
        except json.JSONDecodeError as error:
            raise ValueError(f"{AUTH_CONFIG_ENV} must contain valid JSON") from error
        if not isinstance(config, dict):
            raise ValueError(f"{AUTH_CONFIG_ENV} must contain a JSON object")
        return cls(
            _parse_principals(
                config,
                approval_store=(
                    approval_store
                    if approval_store is not None
                    else InMemoryApprovalStore()
                ),
            )
        )

    def authenticate(self, authorization: str | None) -> Principal:
        if authorization is None:
            return ANONYMOUS_PRINCIPAL
        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token.strip():
            raise AuthenticationError("invalid bearer credential")
        principal = self._principals_by_token.get(token.strip())
        if principal is None:
            raise AuthenticationError("invalid bearer credential")
        return principal


def _parse_principals(
    config: Mapping[str, Any],
    *,
    approval_store: ApprovalStore,
) -> dict[str, Principal]:
    principals: dict[str, Principal] = {}
    for token, raw_principal in config.items():
        if not isinstance(token, str) or not isinstance(raw_principal, dict):
            raise ValueError(f"{AUTH_CONFIG_ENV} entries must map tokens to objects")
        principal_id = raw_principal.get("principal_id")
        roles = raw_principal.get("roles", [])
        approvals = raw_principal.get("approvals", [])
        unsupported = set(raw_principal) - {"principal_id", "roles", "approvals"}
        if unsupported:
            raise ValueError(f"unsupported authentication fields: {sorted(unsupported)}")
        if not isinstance(principal_id, str):
            raise ValueError("configured principal_id must be a string")
        if not _is_string_list(roles) or not isinstance(approvals, list):
            raise ValueError("configured roles and approvals have invalid types")
        principals[token] = Principal(
            principal_id=principal_id,
            roles=frozenset(roles),
            approval_store=approval_store,
        )
        for approval in approvals:
            _grant_configured_approval(
                approval_store,
                principal_id=principal_id,
                raw_approval=approval,
            )
    return principals


def _grant_configured_approval(
    approval_store: ApprovalStore,
    *,
    principal_id: str,
    raw_approval: object,
) -> None:
    if not isinstance(raw_approval, dict):
        raise ValueError("configured approvals must be objects")
    unsupported = set(raw_approval) - {"tool_call_id", "tool_name", "arguments"}
    if unsupported:
        raise ValueError(f"unsupported approval fields: {sorted(unsupported)}")
    tool_call_id = raw_approval.get("tool_call_id")
    tool_name = raw_approval.get("tool_name")
    arguments = raw_approval.get("arguments")
    if not isinstance(tool_call_id, str) or not isinstance(tool_name, str):
        raise ValueError("approval tool_call_id and tool_name must be strings")
    if not isinstance(arguments, dict):
        raise ValueError("approval arguments must be an object")
    approval_store.grant(
        principal_id=principal_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
    )


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _normalize_names(values: frozenset[str], label: str) -> frozenset[str]:
    normalized = frozenset(value.strip() for value in values)
    if "" in normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


ANONYMOUS_PRINCIPAL = Principal(
    principal_id="anonymous",
    authenticated=False,
)
