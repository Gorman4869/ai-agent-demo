from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Protocol

from backend.app.agent.runtime import (
    AgentRuntime,
    RuntimeControl,
    RuntimeContextIdentity,
    RuntimeEventSink,
    RuntimeOutcome,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.context.assembler import (
    ContextAssembler,
    ContextAssembly,
    ContextAssemblyError,
)
from backend.app.context.collector import (
    ContextCollectionError,
    ContextCollectionInput,
    ContextSourceCollector,
    ContextSystemConstraint,
)
from backend.app.domain.run import RunFailure, RunStatus


class ContextRuntimePreparationError(ValueError):
    """Stable Runtime preparation failure without private context data."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RuntimeContextBinding:
    """Trusted application binding for one context collection request."""

    owner_id: str = field(repr=False)
    session_id: str = field(repr=False)
    system_constraints: tuple[ContextSystemConstraint, ...] = ()

    def __post_init__(self) -> None:
        validated = ContextCollectionInput(
            owner_id=self.owner_id,
            session_id=self.session_id,
            query="",
            system_constraints=self.system_constraints,
        )
        object.__setattr__(
            self,
            "system_constraints",
            validated.system_constraints,
        )


class RuntimeContextBindingFactory(Protocol):
    def __call__(self, request: RuntimeRequest) -> RuntimeContextBinding: ...


@dataclass(frozen=True)
class RuntimeIdentityBindingFactory:
    """Map a coordinator-owned Runtime identity into context source scope."""

    system_constraints: tuple[ContextSystemConstraint, ...] = ()

    def __post_init__(self) -> None:
        validated = RuntimeContextBinding(
            owner_id="context-binding-validation-owner",
            session_id="context-binding-validation-session",
            system_constraints=self.system_constraints,
        )
        object.__setattr__(
            self,
            "system_constraints",
            validated.system_constraints,
        )

    def __call__(self, request: RuntimeRequest) -> RuntimeContextBinding:
        identity = request.context_identity
        if identity is None:
            raise ContextRuntimePreparationError("context_identity_missing")
        if not isinstance(identity, RuntimeContextIdentity):
            raise ContextRuntimePreparationError("context_identity_invalid")
        return RuntimeContextBinding(
            owner_id=identity.owner_id,
            session_id=identity.session_id,
            system_constraints=self.system_constraints,
        )


@dataclass(frozen=True)
class PreparedContextRequest:
    request: RuntimeRequest
    assembly: ContextAssembly


def prepare_context_request(
    request: RuntimeRequest,
    *,
    binding_factory: RuntimeContextBindingFactory,
    collector: ContextSourceCollector,
    assembler: ContextAssembler,
) -> PreparedContextRequest:
    if request.prompt_context is not None:
        raise ContextRuntimePreparationError("prompt_context_already_set")

    binding = binding_factory(request)
    if not isinstance(binding, RuntimeContextBinding):
        raise ContextRuntimePreparationError("context_binding_invalid")
    try:
        collection_input = ContextCollectionInput(
            owner_id=binding.owner_id,
            session_id=binding.session_id,
            query=request.input_text,
            system_constraints=binding.system_constraints,
        )
    except ValueError:
        raise ContextRuntimePreparationError(
            "context_collection_input_invalid"
        ) from None

    assembly = collector.collect(collection_input).assemble(assembler)
    if assembly.prompt_context is None:
        return PreparedContextRequest(request=request, assembly=assembly)
    return PreparedContextRequest(
        request=replace(request, prompt_context=assembly.prompt_context),
        assembly=assembly,
    )


class ContextAwareRuntime:
    """Collect bounded application context before delegating to a Runtime."""

    def __init__(
        self,
        delegate: AgentRuntime,
        *,
        binding_factory: RuntimeContextBindingFactory,
        collector: ContextSourceCollector,
        assembler: ContextAssembler | None = None,
    ) -> None:
        if assembler is not None and not isinstance(assembler, ContextAssembler):
            raise ValueError("context assembler has an invalid format")
        self._delegate = delegate
        self._binding_factory = binding_factory
        self._collector = collector
        self._assembler = (
            ContextAssembler() if assembler is None else assembler
        )

    @property
    def delegate(self) -> AgentRuntime:
        return self._delegate

    async def run(
        self,
        request: RuntimeRequest,
        *,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ) -> RuntimeOutcome:
        try:
            prepared = prepare_context_request(
                request,
                binding_factory=self._binding_factory,
                collector=self._collector,
                assembler=self._assembler,
            )
        except (
            ContextRuntimePreparationError,
            ContextCollectionError,
            ContextAssemblyError,
        ):
            return RuntimeResult(
                status=RunStatus.FAILED,
                failure=RunFailure(
                    code="context_unavailable",
                    category="runtime",
                    public_message="Context is unavailable",
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
    "ContextAwareRuntime",
    "ContextRuntimePreparationError",
    "PreparedContextRequest",
    "RuntimeContextBinding",
    "RuntimeContextBindingFactory",
    "RuntimeIdentityBindingFactory",
    "prepare_context_request",
]
