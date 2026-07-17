from __future__ import annotations

import re
import sys
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType


_SERVER_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


@dataclass(frozen=True)
class McpServerConfig:
    """Server-owned command configuration selected only by a stable ID."""

    server_id: str
    command: str
    args: tuple[str, ...] = ()
    cwd: Path | None = None

    def __post_init__(self) -> None:
        normalized_args = tuple(self.args)
        normalized_cwd = Path(self.cwd) if self.cwd is not None else None
        object.__setattr__(self, "args", normalized_args)
        object.__setattr__(self, "cwd", normalized_cwd)
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


def default_mcp_server_configs() -> Mapping[str, McpServerConfig]:
    """Return the immutable server catalog available to Settings selectors."""

    project_root = Path(__file__).resolve().parents[4]
    python_knowledge = McpServerConfig(
        server_id="python-knowledge",
        command=sys.executable,
        args=("-X", "utf8", "-B", "-m", "backend.app.mcp_server"),
        cwd=project_root,
    )
    return MappingProxyType({python_knowledge.server_id: python_knowledge})


def _contains_control(value: str) -> bool:
    return any(
        unicodedata.category(character).startswith("C") for character in value
    )
