from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from backend.app.advanced.postgres_review_requests import PostgresReviewRequestStore
from backend.app.advanced.review_application import _missing_binding
from backend.app.advanced.review_runtime import MultisourceReviewRuntime, ReviewRunBinding, ReviewRunCatalog
from backend.app.advanced.review_tools import AsyncReviewToolRegistry
from backend.app.agent import RuntimeApprovalResume, RuntimeControl, RuntimeEventSink, RuntimeOutcome, RuntimeRequest
from backend.app.security import StaticTokenAuthenticator
from backend.app.settings import Settings
from backend.app.stores.postgres import PostgresPersistence


ReviewRegistryFactory = Callable[[PostgresPersistence], AsyncReviewToolRegistry]


class PostgresReviewRuns(PostgresReviewRequestStore):
    """Resolve each invocation from its durable private request and owned pools."""

    def __init__(self, persistence: PostgresPersistence, registry: AsyncReviewToolRegistry) -> None:
        super().__init__(persistence.run_store)
        self._persistence = persistence
        self._registry = registry.with_policy_runner(persistence.sync_store_bridge.run)

    async def _runtime(self, request: RuntimeRequest) -> MultisourceReviewRuntime | None:
        identity = request.context_identity
        if identity is None:
            return None
        spec = await self.resolve(request.run_id, owner_id=identity.owner_id)
        if spec is None:
            return None
        return MultisourceReviewRuntime(
            registry=self._registry,
            run_catalog=ReviewRunCatalog({request.run_id: ReviewRunBinding(request.run_id, identity.owner_id, spec)}),
            tool_execution_store=self._persistence.tool_execution_store,
            async_approval_store=self._persistence.async_approval_store,
        )

    async def run(self, request: RuntimeRequest, *, emit: RuntimeEventSink, control: RuntimeControl) -> RuntimeOutcome:
        runtime = await self._runtime(request)
        if runtime is None:
            return _missing_binding()
        return await runtime.run(request, emit=emit, control=control)

    async def resume(self, request: RuntimeRequest, *, approval: RuntimeApprovalResume, emit: RuntimeEventSink, control: RuntimeControl) -> RuntimeOutcome:
        runtime = await self._runtime(request)
        if runtime is None:
            return _missing_binding()
        return await runtime.resume(request, approval=approval, emit=emit, control=control)


def create_postgres_review_app(
    *, settings: Settings, registry_factory: ReviewRegistryFactory,
    authenticator: StaticTokenAuthenticator,
) -> FastAPI:
    from backend.app.main import create_app

    if settings.persistence.backend != "postgres":
        raise ValueError("PostgreSQL review app requires postgres persistence")
    return create_app(settings=settings, authenticator=authenticator, review_registry_factory=registry_factory)
