from __future__ import annotations

from dataclasses import dataclass, replace

from backend.app.agent.runtime import (
    AgentRuntime,
    RuntimeControl,
    RuntimeEventSink,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.domain.run import RunFailure, RunStatus
from backend.app.skills.catalog import SkillCatalogError
from backend.app.skills.context import (
    SkillContext,
    SkillContextBuilder,
    SkillContextError,
)
from backend.app.skills.resolver import SkillResolverError


@dataclass(frozen=True)
class PreparedSkillRequest:
    request: RuntimeRequest
    context: SkillContext | None


def prepare_skill_request(
    request: RuntimeRequest,
    *,
    builder: SkillContextBuilder,
) -> PreparedSkillRequest:
    if request.prompt_context is not None:
        raise SkillContextError("prompt_context_already_set")
    context = builder.build(request.input_text)
    if context is None:
        return PreparedSkillRequest(request=request, context=None)
    return PreparedSkillRequest(
        request=replace(request, prompt_context=context.fragment),
        context=context,
    )


class SkillAwareRuntime:
    """Resolve application-owned Skills before delegating to a Runtime."""

    def __init__(
        self,
        delegate: AgentRuntime,
        *,
        builder: SkillContextBuilder,
    ) -> None:
        self._delegate = delegate
        self._builder = builder

    @property
    def delegate(self) -> AgentRuntime:
        return self._delegate

    async def run(
        self,
        request: RuntimeRequest,
        *,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ) -> RuntimeResult:
        try:
            prepared = prepare_skill_request(request, builder=self._builder)
        except (SkillCatalogError, SkillResolverError, SkillContextError):
            return RuntimeResult(
                status=RunStatus.FAILED,
                failure=RunFailure(
                    code="skill_context_unavailable",
                    category="runtime",
                    public_message="Skill context is unavailable",
                    step=0,
                ),
                step=0,
            )
        return await self._delegate.run(
            prepared.request,
            emit=emit,
            control=control,
        )


__all__ = [
    "PreparedSkillRequest",
    "SkillAwareRuntime",
    "prepare_skill_request",
]
