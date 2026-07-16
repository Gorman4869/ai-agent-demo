from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from backend.app.agent import CancellationToken, ManualAgentLoop
from backend.app.domain import AgentRunResult, ModelDecision, ToolCall
from backend.app.models import MockModel
from backend.app.observability import JsonLogSink, RunObservation, RunObserver
from backend.app.tools import ToolExecutionContext
from backend.app.tools.builtin import create_default_registry


@dataclass(frozen=True)
class SessionRecord:
    id: str
    created_at: datetime
    principal_id: str
    access_token_digest: str | None = field(repr=False, compare=False)


@dataclass(frozen=True)
class CreatedSession:
    session: SessionRecord
    access_token: str | None = field(repr=False, compare=False)


@dataclass(frozen=True)
class RunRecord:
    id: str
    session_id: str
    status: str
    answer: str | None
    event_types: tuple[str, ...]
    error: str | None


class InMemoryRunService:
    """M2 storage boundary; a database adapter can replace it later."""

    def __init__(self, observer: RunObserver | None = None) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._runs: dict[str, RunRecord] = {}
        self._observations: dict[str, RunObservation] = {}
        self._observation_principals: dict[str, str] = {}
        self._log_sink = JsonLogSink()
        self._observer = observer or RunObserver(sink=self._capture_observation)

    def create_session(self, *, principal_id: str | None = None) -> CreatedSession:
        session_id = str(uuid4())
        access_token = secrets.token_urlsafe(32) if principal_id is None else None
        if principal_id is not None and not principal_id.strip():
            raise ValueError("principal_id must not be empty")
        session = SessionRecord(
            id=session_id,
            created_at=datetime.now(UTC),
            principal_id=principal_id or f"anonymous:{session_id}",
            access_token_digest=(
                _digest_access_token(access_token) if access_token is not None else None
            ),
        )
        self._sessions[session.id] = session
        return CreatedSession(session=session, access_token=access_token)

    def has_session(
        self,
        session_id: str,
        *,
        principal_id: str | None = None,
        access_token: str | None = None,
    ) -> bool:
        session = self._sessions.get(session_id)
        return session is not None and _session_access_matches(
            session,
            principal_id=principal_id,
            access_token=access_token,
        )

    def resolve_session_principal(
        self,
        session_id: str,
        *,
        access_token: str | None,
    ) -> str | None:
        session = self._sessions.get(session_id)
        if session is None or not _session_access_matches(
            session,
            principal_id=None,
            access_token=access_token,
        ):
            return None
        return session.principal_id

    def create_run(
        self,
        session_id: str,
        message: str,
        *,
        execution_context: ToolExecutionContext | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> RunRecord:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("session does not exist")
        run_id = str(uuid4())
        self._observation_principals[run_id] = session.principal_id
        observed = self._observer.observe(
            lambda: execute_agent(
                message,
                execution_context=execution_context,
                cancellation_token=cancellation_token,
            ),
            run_id=run_id,
        )
        result = observed.result
        run = RunRecord(
            id=run_id,
            session_id=session_id,
            status=result.status,
            answer=result.final_answer,
            event_types=tuple(event.type for event in result.events),
            error=result.error,
        )
        self._runs[run.id] = run
        self._observations[run.id] = observed.observation
        return run

    def get_run(
        self,
        run_id: str,
        *,
        principal_id: str | None = None,
        access_token: str | None = None,
    ) -> RunRecord | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        return (
            run
            if self.has_session(
                run.session_id,
                principal_id=principal_id,
                access_token=access_token,
            )
            else None
        )

    def observations(
        self,
        *,
        principal_id: str | None = None,
    ) -> tuple[RunObservation, ...]:
        if principal_id is None:
            return tuple(self._observations.values())
        return tuple(
            observation
            for run_id, observation in self._observations.items()
            if self._observation_principals.get(run_id) == principal_id
        )

    def _capture_observation(self, observation: RunObservation) -> None:
        self._observations[observation.run_id] = observation
        self._log_sink(observation)


def execute_agent(
    message: str,
    *,
    execution_context: ToolExecutionContext | None = None,
    cancellation_token: CancellationToken | None = None,
) -> AgentRunResult:
    """Run the deterministic learning Agent without storing API state."""
    return create_learning_agent_loop(
        message,
        execution_context=execution_context,
        cancellation_token=cancellation_token,
    ).run(message)


def create_learning_agent_loop(
    message: str,
    *,
    execution_context: ToolExecutionContext | None = None,
    cancellation_token: CancellationToken | None = None,
    max_steps: int = 8,
    max_model_retries: int = 2,
) -> ManualAgentLoop:
    """Build a fresh offline loop for one Runtime invocation."""
    return ManualAgentLoop(
        create_learning_model(message),
        create_default_registry(),
        max_steps=max_steps,
        execution_context=execution_context,
        cancellation_token=cancellation_token,
        max_model_retries=max_model_retries,
    )


def create_learning_model(message: str) -> MockModel:
    """Build one deterministic model script shared by offline Runtimes."""
    return MockModel(_script_decisions(message))


def _script_decisions(message: str) -> list[ModelDecision]:
    report_id = _extract_report_id(message)
    if report_id is not None:
        return [
            ModelDecision(
                tool_call=ToolCall(
                    id="api-publish-call",
                    name="publish_report",
                    arguments={"report_id": report_id},
                )
            ),
            ModelDecision(final_answer="发布请求已处理，请核对工具事件。"),
        ]
    numbers = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", message)]
    if len(numbers) >= 2:
        total = numbers[0] + numbers[1]
        return [
            ModelDecision(
                tool_call=ToolCall(
                    id="api-tool-call",
                    name="add_numbers",
                    arguments={"a": numbers[0], "b": numbers[1]},
                )
            ),
            ModelDecision(final_answer=f"计算结果是 {total:g}"),
        ]
    return [ModelDecision(final_answer=f"Mock Agent 收到：{message}")]


def _extract_report_id(message: str) -> str | None:
    match = re.fullmatch(
        r"\s*(?:发布报告|publish\s+report)\s+([A-Za-z0-9_-]{1,64})\s*",
        message,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match is not None else None


def _session_access_matches(
    session: SessionRecord,
    *,
    principal_id: str | None,
    access_token: str | None,
) -> bool:
    if session.access_token_digest is None:
        return principal_id is not None and session.principal_id == principal_id
    if access_token is None or not access_token.strip():
        return False
    return hmac.compare_digest(
        session.access_token_digest,
        _digest_access_token(access_token),
    )


def _digest_access_token(access_token: str) -> str:
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()
