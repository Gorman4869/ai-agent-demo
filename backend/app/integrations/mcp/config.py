from __future__ import annotations

import re
import sys
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from backend.app.tools import ToolRisk


_SERVER_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_REMOTE_TOOL_NAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_LOCAL_TOOL_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass(frozen=True)
class McpToolPolicy:
    """Trusted application policy for one discovered remote tool."""

    local_name: str
    description: str
    allowed_roles: frozenset[str] = field(default_factory=frozenset)
    risk_level: ToolRisk = ToolRisk.LOW
    has_side_effects: bool = False
    requires_approval: bool = False

    def __post_init__(self) -> None:
        roles = frozenset(role.strip() for role in self.allowed_roles)
        object.__setattr__(self, "allowed_roles", roles)
        if _LOCAL_TOOL_NAME_PATTERN.fullmatch(self.local_name) is None:
            raise ValueError("MCP local tool name has an invalid format")
        if (
            not self.description.strip()
            or self.description != self.description.strip()
            or len(self.description) > 2_000
            or any(not character.isprintable() for character in self.description)
        ):
            raise ValueError("MCP tool description has an invalid format")
        if "" in roles or any(
            len(role) > 100 or _contains_control(role) for role in roles
        ):
            raise ValueError("MCP tool role has an invalid format")
        if not isinstance(self.risk_level, ToolRisk):
            object.__setattr__(self, "risk_level", ToolRisk(self.risk_level))


@dataclass(frozen=True)
class McpServerConfig:
    """Server-owned command configuration selected only by a stable ID."""

    server_id: str
    command: str
    args: tuple[str, ...] = ()
    cwd: Path | None = None
    tool_policies: Mapping[str, McpToolPolicy] = field(
        default_factory=dict,
        repr=False,
    )

    def __post_init__(self) -> None:
        normalized_args = tuple(self.args)
        normalized_cwd = Path(self.cwd) if self.cwd is not None else None
        normalized_policies = dict(self.tool_policies)
        object.__setattr__(self, "args", normalized_args)
        object.__setattr__(self, "cwd", normalized_cwd)
        object.__setattr__(
            self,
            "tool_policies",
            MappingProxyType(normalized_policies),
        )
        if _SERVER_ID_PATTERN.fullmatch(self.server_id) is None:
            raise ValueError("MCP server_id has an invalid format")
        if (
            not self.command.strip()
            or self.command != self.command.strip()
            or _contains_control(self.command)
        ):
            raise ValueError("MCP command has an invalid format")
        if any(_contains_control(argument) for argument in normalized_args):
            raise ValueError("MCP argument has an invalid format")
        if normalized_cwd is not None and not normalized_cwd.is_absolute():
            raise ValueError("MCP cwd must be an absolute path")
        if len(normalized_policies) > 64:
            raise ValueError("MCP server allows at most 64 tools")
        if any(
            not isinstance(remote_name, str)
            or _REMOTE_TOOL_NAME_PATTERN.fullmatch(remote_name) is None
            or not isinstance(policy, McpToolPolicy)
            for remote_name, policy in normalized_policies.items()
        ):
            raise ValueError("MCP remote tool policy has an invalid format")
        local_names = [
            policy.local_name for policy in normalized_policies.values()
        ]
        if len(local_names) != len(set(local_names)):
            raise ValueError("MCP local tool names must be unique per server")


def default_mcp_server_configs() -> Mapping[str, McpServerConfig]:
    """Return the immutable server catalog available to Settings selectors."""

    project_root = Path(__file__).resolve().parents[4]
    python_knowledge = McpServerConfig(
        server_id="python-knowledge",
        command=sys.executable,
        args=("-X", "utf8", "-B", "-m", "backend.app.mcp_server"),
        cwd=project_root,
        tool_policies={
            "lookup_concept": McpToolPolicy(
                local_name="mcp_python_knowledge_lookup_concept",
                description="Look up one approved AI Agent course concept.",
            )
        },
    )
    return MappingProxyType({python_knowledge.server_id: python_knowledge})


def _contains_control(value: str) -> bool:
    return any(
        unicodedata.category(character).startswith("C") for character in value
    )
