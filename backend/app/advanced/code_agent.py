from __future__ import annotations

import math
import os
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from backend.app.advanced.harness import (
    PolicyViolation,
    SafetyBudget,
    SafetyLimits,
    content_digest,
)
from backend.app.advanced.process_runner import (
    CancellationSignal,
    ProcessResourceLimits,
    ProcessStartError,
    run_bounded_process,
)


@dataclass(frozen=True)
class ReadAction:
    """Read one UTF-8 text file through the controlled workspace boundary."""

    path: str

    def __post_init__(self) -> None:
        _validate_name(self.path, "read path")


@dataclass(frozen=True)
class WriteAction:
    """Write UTF-8 text to one exactly approved workspace path."""

    path: str
    content: str = field(repr=False)

    def __post_init__(self) -> None:
        _validate_name(self.path, "write path")
        if not isinstance(self.content, str):
            raise TypeError("write content must be a string")


@dataclass(frozen=True)
class CheckAction:
    """Run one server-registered check without caller-controlled arguments."""

    command_name: str

    def __post_init__(self) -> None:
        _validate_name(self.command_name, "command name")


CodeAction = ReadAction | WriteAction | CheckAction


@dataclass(frozen=True)
class CommandSpec:
    """A server-owned command definition; an action can select only its name."""

    name: str
    argv: tuple[str, ...]
    timeout_seconds: float = 5.0
    max_output_bytes: int = 16_384
    environment: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    resources: ProcessResourceLimits = field(default_factory=ProcessResourceLimits)

    def __post_init__(self) -> None:
        _validate_name(self.name, "command name")
        argv = tuple(self.argv)
        if not argv or any(
            not isinstance(value, str) or not value or "\x00" in value
            for value in argv
        ):
            raise ValueError("command argv must contain non-empty strings")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("command timeout_seconds must be positive and finite")
        if (
            isinstance(self.max_output_bytes, bool)
            or not isinstance(self.max_output_bytes, int)
            or self.max_output_bytes < 1
        ):
            raise ValueError("command max_output_bytes must be positive")
        environment = tuple(self.environment)
        environment_names: set[str] = set()
        for item in environment:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError("command environment must contain key/value pairs")
            key, value = item
            if (
                not isinstance(key, str)
                or not key
                or "=" in key
                or "\x00" in key
                or not isinstance(value, str)
                or "\x00" in value
            ):
                raise ValueError("command environment contains an invalid key/value")
            normalized_key = key.casefold() if os.name == "nt" else key
            if normalized_key in environment_names:
                raise ValueError("command environment keys must be unique")
            environment_names.add(normalized_key)
        if not isinstance(self.resources, ProcessResourceLimits):
            raise ValueError("command resources have an invalid type")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "environment", environment)


@dataclass(frozen=True)
class CodeExecutionContext:
    """Trusted server context containing canonical, exact write approvals."""

    principal_id: str
    approved_write_paths: frozenset[Path] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        _validate_name(self.principal_id, "principal id")
        paths = frozenset(Path(path) for path in self.approved_write_paths)
        object.__setattr__(self, "approved_write_paths", paths)


@dataclass(frozen=True)
class ActionOutcome:
    action_type: str
    target: str
    status: str
    digest: str | None = None
    byte_count: int = 0
    content: str | None = field(default=None, repr=False)
    stdout: str | None = field(default=None, repr=False)
    stderr: str | None = field(default=None, repr=False)
    return_code: int | None = None
    truncated: bool = False
    error_code: str | None = None
    observed_output_bytes: int = 0
    termination_reason: str | None = None
    resource_limit: str | None = None
    process_scope: str | None = None
    process_tree_cleaned: bool | None = None


@dataclass(frozen=True)
class AuditEntry:
    """Content-free audit metadata for one attempted action."""

    sequence: int
    action_type: str
    target: str
    status: str
    digest: str | None
    byte_count: int
    error_code: str | None = None
    observed_output_bytes: int = 0
    termination_reason: str | None = None
    resource_limit: str | None = None
    process_scope: str | None = None
    process_tree_cleaned: bool | None = None


@dataclass(frozen=True)
class CodeRunResult:
    outcomes: tuple[ActionOutcome, ...]
    audit: tuple[AuditEntry, ...]
    actions_used: int
    written_bytes: int
    read_bytes: int
    output_bytes: int

    @property
    def ok(self) -> bool:
        return all(outcome.status == "succeeded" for outcome in self.outcomes)


class ControlledCodeAgent:
    """Execute a small structured plan inside one fixed workspace.

    The runner intentionally has no delete action and no arbitrary-shell action.
    Check commands are immutable server definitions and always run with
    ``shell=False`` and the workspace root as their current directory.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        command_specs: Iterable[CommandSpec] = (),
        limits: SafetyLimits | None = None,
    ) -> None:
        root = Path(workspace_root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("workspace_root must be an existing directory")
        commands: dict[str, CommandSpec] = {}
        for spec in command_specs:
            if spec.name in commands:
                raise ValueError(f"duplicate command spec: {spec.name}")
            commands[spec.name] = spec
        self._workspace_root = root
        self._commands = commands
        self._limits = limits or SafetyLimits()

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    def create_execution_context(
        self,
        *,
        principal_id: str,
        approved_write_paths: Iterable[str] = (),
    ) -> CodeExecutionContext:
        """Build the trusted context at the server boundary, not from an action."""
        approved = frozenset(
            self._resolve_workspace_path(path) for path in approved_write_paths
        )
        return CodeExecutionContext(
            principal_id=principal_id,
            approved_write_paths=approved,
        )

    def run(
        self,
        actions: Sequence[CodeAction],
        *,
        context: CodeExecutionContext,
        cancellation: CancellationSignal | None = None,
    ) -> CodeRunResult:
        """Run actions in order and stop at the first rejected or failed action."""
        self._validate_context(context)
        budget = SafetyBudget(self._limits)
        outcomes: list[ActionOutcome] = []
        audit: list[AuditEntry] = []

        for sequence, action in enumerate(actions, start=1):
            if cancellation is not None and cancellation.is_cancelled:
                outcome = _rejected_outcome(action, "run_cancelled")
            else:
                try:
                    outcome = self._execute(
                        action,
                        context=context,
                        budget=budget,
                        cancellation=cancellation,
                    )
                except PolicyViolation as error:
                    outcome = _rejected_outcome(action, error.code)
            outcomes.append(outcome)
            audit.append(
                AuditEntry(
                    sequence=sequence,
                    action_type=outcome.action_type,
                    target=outcome.target,
                    status=outcome.status,
                    digest=outcome.digest,
                    byte_count=outcome.byte_count,
                    error_code=outcome.error_code,
                    observed_output_bytes=outcome.observed_output_bytes,
                    termination_reason=outcome.termination_reason,
                    resource_limit=outcome.resource_limit,
                    process_scope=outcome.process_scope,
                    process_tree_cleaned=outcome.process_tree_cleaned,
                )
            )
            if outcome.status != "succeeded":
                break

        return CodeRunResult(
            outcomes=tuple(outcomes),
            audit=tuple(audit),
            actions_used=budget.actions,
            written_bytes=budget.input_bytes,
            read_bytes=sum(
                outcome.byte_count
                for outcome in outcomes
                if outcome.action_type == "read" and outcome.status == "succeeded"
            ),
            output_bytes=budget.output_bytes,
        )

    def _execute(
        self,
        action: CodeAction,
        *,
        context: CodeExecutionContext,
        budget: SafetyBudget,
        cancellation: CancellationSignal | None,
    ) -> ActionOutcome:
        if isinstance(action, ReadAction):
            return self._read(action, budget=budget)
        if isinstance(action, WriteAction):
            return self._write(action, context=context, budget=budget)
        if isinstance(action, CheckAction):
            return self._check(
                action,
                budget=budget,
                cancellation=cancellation,
            )
        raise PolicyViolation("action_not_allowed", "action type is not allowed")

    def _read(self, action: ReadAction, *, budget: SafetyBudget) -> ActionOutcome:
        target = self._resolve_workspace_path(action.path)
        relative_target = self._relative_target(target)
        try:
            with target.open("rb") as source:
                size = os.fstat(source.fileno()).st_size
                budget.consume(output_bytes=size)
                payload = source.read(size + 1)
        except FileNotFoundError as error:
            raise PolicyViolation("file_not_found", "read target was not found") from error
        except IsADirectoryError as error:
            raise PolicyViolation("path_not_file", "read target is not a file") from error
        except PermissionError as error:
            raise PolicyViolation("file_permission_denied", "read permission denied") from error
        except OSError as error:
            raise PolicyViolation("file_io_error", "read failed") from error
        if len(payload) > size:
            raise PolicyViolation(
                "file_changed_during_read",
                "file changed while it was being read",
            )
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PolicyViolation("file_not_utf8", "read target is not UTF-8 text") from error
        return ActionOutcome(
            action_type="read",
            target=relative_target,
            status="succeeded",
            digest=content_digest(payload),
            byte_count=len(payload),
            content=content,
        )

    def _write(
        self,
        action: WriteAction,
        *,
        context: CodeExecutionContext,
        budget: SafetyBudget,
    ) -> ActionOutcome:
        target = self._resolve_workspace_path(action.path)
        relative_target = self._relative_target(target)
        if target not in context.approved_write_paths:
            raise PolicyViolation(
                "write_approval_required",
                "exact write path approval is required",
            )
        payload = action.content.encode("utf-8")
        budget.consume(input_bytes=len(payload))
        if not target.parent.is_dir():
            raise PolicyViolation("parent_not_found", "write parent was not found")
        if target.exists() and not target.is_file():
            raise PolicyViolation("path_not_file", "write target is not a file")
        self._atomic_write(target, payload)
        return ActionOutcome(
            action_type="write",
            target=relative_target,
            status="succeeded",
            digest=content_digest(payload),
            byte_count=len(payload),
        )

    def _check(
        self,
        action: CheckAction,
        *,
        budget: SafetyBudget,
        cancellation: CancellationSignal | None,
    ) -> ActionOutcome:
        spec = self._commands.get(action.command_name)
        if spec is None:
            raise PolicyViolation(
                "command_not_allowed",
                "check command is not in the server allowlist",
            )
        budget.consume()
        run_output_limit = budget.remaining_output_bytes
        capture_limit = min(
            spec.max_output_bytes,
            run_output_limit,
        )
        try:
            completed = run_bounded_process(
                spec.argv,
                cwd=self._workspace_root,
                environment=dict(spec.environment),
                timeout_seconds=spec.timeout_seconds,
                max_output_bytes=capture_limit,
                resources=spec.resources,
                cancellation=cancellation,
            )
        except ProcessStartError as error:
            raise PolicyViolation(
                "command_start_failed",
                "check command could not be started",
            ) from error

        stdout_bytes, stderr_bytes, truncated = _truncate_output(
            completed.stdout,
            completed.stderr,
            capture_limit,
        )
        budget.consume(
            actions=0,
            output_bytes=len(stdout_bytes) + len(stderr_bytes),
        )
        error_code: str | None
        if not completed.process_tree_cleaned:
            status = "failed"
            error_code = "command_cleanup_failed"
        elif not completed.output_read_succeeded:
            status = "failed"
            error_code = "command_output_failed"
        elif completed.termination_reason == "cancelled":
            status = "cancelled"
            error_code = "command_cancelled"
        elif completed.termination_reason == "timeout":
            status = "failed"
            error_code = "command_timeout"
        elif completed.termination_reason == "resource_limit":
            status = "failed"
            error_code = "command_resource_exceeded"
        elif completed.termination_reason == "resource_monitor_failed":
            status = "failed"
            error_code = "command_resource_monitor_failed"
        elif (
            run_output_limit < spec.max_output_bytes
            and completed.observed_output_bytes > run_output_limit
        ):
            status = "failed"
            error_code = "output_budget_exceeded"
        elif completed.return_code != 0:
            status = "failed"
            error_code = "command_failed"
        else:
            status = "succeeded"
            error_code = None
        return ActionOutcome(
            action_type="check",
            target=spec.name,
            status=status,
            digest=content_digest(stdout_bytes + b"\x00" + stderr_bytes),
            byte_count=len(stdout_bytes) + len(stderr_bytes),
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            return_code=completed.return_code,
            truncated=truncated or completed.truncated,
            error_code=error_code,
            observed_output_bytes=completed.observed_output_bytes,
            termination_reason=completed.termination_reason,
            resource_limit=completed.resource_limit,
            process_scope=completed.process_scope,
            process_tree_cleaned=completed.process_tree_cleaned,
        )

    def _resolve_workspace_path(self, requested_path: str) -> Path:
        path = Path(requested_path)
        if path.is_absolute():
            raise PolicyViolation(
                "path_outside_workspace",
                "workspace paths must be relative",
            )
        try:
            resolved = (self._workspace_root / path).resolve(strict=False)
            resolved.relative_to(self._workspace_root)
        except (OSError, RuntimeError, ValueError) as error:
            raise PolicyViolation(
                "path_outside_workspace",
                "path resolves outside the workspace",
            ) from error
        return resolved

    @staticmethod
    def _atomic_write(target: Path, payload: bytes) -> None:
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as destination:
                destination.write(payload)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary_path, target)
            temporary_path = None
        except PermissionError as error:
            raise PolicyViolation(
                "file_permission_denied",
                "write permission denied",
            ) from error
        except OSError as error:
            raise PolicyViolation("file_io_error", "write failed") from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _relative_target(self, target: Path) -> str:
        return target.relative_to(self._workspace_root).as_posix()

    def _validate_context(self, context: CodeExecutionContext) -> None:
        for approved in context.approved_write_paths:
            try:
                canonical = approved.resolve(strict=False)
                canonical.relative_to(self._workspace_root)
            except (OSError, RuntimeError, ValueError) as error:
                raise ValueError(
                    "approved write paths must be canonical workspace paths"
                ) from error
            if not approved.is_absolute() or approved != canonical:
                raise ValueError(
                    "approved write paths must be canonical workspace paths"
                )


def _rejected_outcome(action: object, error_code: str) -> ActionOutcome:
    if isinstance(action, ReadAction):
        action_type = "read"
        target = action.path
        digest = None
        byte_count = 0
    elif isinstance(action, WriteAction):
        action_type = "write"
        target = action.path
        digest = content_digest(action.content)
        byte_count = len(action.content.encode("utf-8"))
    elif isinstance(action, CheckAction):
        action_type = "check"
        target = action.command_name
        digest = None
        byte_count = 0
    else:
        action_type = "unknown"
        target = type(action).__name__
        digest = None
        byte_count = 0
    return ActionOutcome(
        action_type=action_type,
        target=target,
        status="rejected",
        digest=digest,
        byte_count=byte_count,
        error_code=error_code,
    )


def _truncate_output(
    stdout: bytes,
    stderr: bytes,
    limit: int,
) -> tuple[bytes, bytes, bool]:
    if len(stdout) + len(stderr) <= limit:
        return stdout, stderr, False
    kept_stdout = stdout[:limit]
    remaining = limit - len(kept_stdout)
    kept_stderr = stderr[:remaining]
    return kept_stdout, kept_stderr, True


def _validate_name(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{label} must be a non-empty string")
