from __future__ import annotations

import asyncio

from fastapi import FastAPI

from backend.app.advanced.review_runtime import (
    MultisourceReviewRuntime, ReviewRunBinding, ReviewRunCatalog, ReviewRunSpec,
)
from backend.app.advanced.review_tools import AsyncReviewToolRegistry
from backend.app.advanced.review_requests import create_review_run_record
from backend.app.agent import (
    RuntimeApprovalResume, RuntimeControl, RuntimeEventSink, RuntimeOutcome,
    RuntimeRequest, RuntimeResult,
)
from backend.app.domain.run import RunFailure, RunRecord, RunStatus
from backend.app.security import StaticTokenAuthenticator
from backend.app.stores import (
    InMemoryEventStore, InMemoryRunStore, InMemoryToolExecutionStore,
)
from backend.app.stores.base import CreateRunResult


class InMemoryReviewRuns:
    """Explicit local composition; immutable per-Run specs never come from text."""

    def __init__(self, registry: AsyncReviewToolRegistry) -> None:
        self.run_store = InMemoryRunStore()
        self.event_store = InMemoryEventStore(self.run_store)
        self.tool_store = InMemoryToolExecutionStore(self.run_store)
        self._registry = registry
        self._bindings: dict[str, ReviewRunBinding] = {}
        self._lock = asyncio.Lock()

    async def create(
        self, spec: ReviewRunSpec, *, owner_id: str, idempotency_key: str,
    ) -> CreateRunResult:
        record = create_review_run_record(spec, owner_id=owner_id, idempotency_key=idempotency_key)
        async with self._lock:
            created = await self.run_store.create(record)
            self._bindings[created.record.id] = ReviewRunBinding(
                run_id=created.record.id, owner_id=owner_id, spec=spec,
            )
            return created

    async def resolve(self, run_id: str, *, owner_id: str) -> ReviewRunSpec | None:
        binding = self._bindings.get(run_id)
        return binding.spec if binding is not None and binding.owner_id == owner_id else None

    def _runtime(self, request: RuntimeRequest) -> MultisourceReviewRuntime | None:
        binding = self._bindings.get(request.run_id)
        identity = request.context_identity
        if binding is None or identity is None or binding.owner_id != identity.owner_id:
            return None
        return MultisourceReviewRuntime(
            registry=self._registry,
            run_catalog=ReviewRunCatalog({binding.run_id: binding}),
            tool_execution_store=self.tool_store,
        )

    async def run(
        self, request: RuntimeRequest, *, emit: RuntimeEventSink, control: RuntimeControl,
    ) -> RuntimeOutcome:
        runtime = self._runtime(request)
        if runtime is None:
            return _missing_binding()
        return await runtime.run(request, emit=emit, control=control)

    async def resume(
        self, request: RuntimeRequest, *, approval: RuntimeApprovalResume,
        emit: RuntimeEventSink, control: RuntimeControl,
    ) -> RuntimeOutcome:
        runtime = self._runtime(request)
        if runtime is None:
            return _missing_binding()
        return await runtime.resume(request, approval=approval, emit=emit, control=control)


def _missing_binding() -> RuntimeResult:
    return RuntimeResult(
        status=RunStatus.FAILED,
        failure=RunFailure(
            code="review_evidence_invalid", category="validation",
            public_message="Review request binding is unavailable",
        ),
    )


def create_review_app(
    *, registry: AsyncReviewToolRegistry, authenticator: StaticTokenAuthenticator,
) -> FastAPI:
    """Build an in-memory review app with explicitly supplied reviewed tools."""
    from backend.app.container import ApplicationContainer
    from backend.app.main import create_app
    from backend.app.settings import Settings

    reviews = InMemoryReviewRuns(registry)
    container = ApplicationContainer.create(
        settings=Settings.from_environment({}),
        run_store=reviews.run_store, event_store=reviews.event_store,
        runtimes={"manual": reviews}, authenticator=authenticator,
    )
    return create_app(container=container, review_runs=reviews)
