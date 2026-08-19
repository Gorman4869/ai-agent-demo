from __future__ import annotations

from dataclasses import replace

from backend.app.agent.runtime import (
    AgentRuntime,
    RuntimeControl,
    RuntimeEventSink,
    RuntimeOutcome,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.domain.run import RunFailure, RunStatus

from .assembler import ContextAssembler, ContextAssemblyError
from .async_collector import AsyncMemoryContextSourceCollector
from .collector import ContextCollectionError, ContextCollectionInput
from .runtime import (
    ContextRuntimePreparationError,
    PreparedContextRequest,
    RuntimeContextBinding,
    RuntimeContextBindingFactory,
)


async def prepare_async_context_request(
    request: RuntimeRequest,
    *,
    binding_factory: RuntimeContextBindingFactory,
    collector: AsyncMemoryContextSourceCollector,
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

    assembly = (await collector.collect(collection_input)).assemble(assembler)
    if assembly.prompt_context is None:
        return PreparedContextRequest(request=request, assembly=assembly)
    return PreparedContextRequest(
        request=replace(request, prompt_context=assembly.prompt_context),
        assembly=assembly,
    )


class AsyncContextAwareRuntime:
    """Collect Memory asynchronously before delegating to a Runtime."""

    def __init__(
        self,
        delegate: AgentRuntime,
        *,
        binding_factory: RuntimeContextBindingFactory,
        collector: AsyncMemoryContextSourceCollector,
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
            prepared = await prepare_async_context_request(
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
    "AsyncContextAwareRuntime",
    "prepare_async_context_request",
]
