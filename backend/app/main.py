from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    status,
)
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.app.api.schemas import (
    DocumentRequest,
    DocumentResponse,
    DurableRunRequest,
    DurableRunResponse,
    DurableRunErrorResponse,
    EvidenceResponse,
    EvalReportResponse,
    HealthResponse,
    MemoryCorrectionRequest,
    MemoryFactAuditResponse,
    MemoryFactResponse,
    MemoryRequest,
    MemoryResponse,
    ModelUsageResponse,
    ResearchRequest,
    ResearchResponse,
    RunErrorResponse,
    RunObservationResponse,
    RunRequest,
    RunResponse,
    SessionResponse,
    ApprovalDecisionRequest,
)
from backend.app.agent import CancellationToken
from backend.app.agent.research_workflow import create_research_workflow
from backend.app.application_lifecycle import ApplicationNotAcceptingError
from backend.app.container import ApplicationContainer
from backend.app.domain.run import RunRecord as DurableRunRecord
from backend.app.domain.run import RunStatus, StoredRunEvent
from backend.app.evals import EvalCase, OfflineEvaluator
from backend.app.knowledge import (
    DEMO_COURSE_DOCUMENT,
    Document,
    InMemoryKnowledgeBase,
    KnowledgeBase,
)
from backend.app.memory import (
    CorrectMemoryFact,
    DeleteMemoryFact,
    MemoryFact,
    MemoryFactAuditRecord,
    MemoryFactConflictError,
    MemoryFactNotFoundError,
    MemoryScope,
    MemoryStore,
)
from backend.app.observability import RunObservation
from backend.app.security import (
    AuthenticationError,
    Principal,
    StaticTokenAuthenticator,
)
from backend.app.services import InMemoryRunService
from backend.app.services.run_service import RunRecord as LegacyRunRecord
from backend.app.services.run_service import execute_agent
from backend.app.settings import Settings
from backend.app.stores import (
    IdempotencyConflictError,
    InvalidRunTransitionError,
    RunNotFoundError,
)
from backend.app.tools import ApprovalResolutionError, ToolExecutionContext


logger = logging.getLogger("ai_agent.api")


class _ApplicationAdmissionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        application = scope.get("app")
        current = getattr(getattr(application, "state", None), "container", None)
        if not isinstance(current, ApplicationContainer):
            await JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": "Application is not ready"},
            )(scope, receive, send)
            return
        try:
            await current.admission.acquire()
        except ApplicationNotAcceptingError:
            await JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": "Application is shutting down"},
            )(scope, receive, send)
            return
        try:
            await self._app(scope, receive, send)
        finally:
            await current.admission.release()


def create_app(
    run_service: InMemoryRunService | None = None,
    knowledge_base: KnowledgeBase | None = None,
    memory: MemoryStore | None = None,
    authenticator: StaticTokenAuthenticator | None = None,
    *,
    settings: Settings | None = None,
    container: ApplicationContainer | None = None,
) -> FastAPI:
    legacy_dependencies = (
        run_service,
        knowledge_base,
        memory,
        authenticator,
    )
    resolved_settings = (
        container.settings
        if container is not None
        else (
            settings if settings is not None else Settings.from_environment()
        )
    )
    if container is not None:
        if settings is not None or any(
            dependency is not None for dependency in legacy_dependencies
        ):
            raise ValueError(
                "container cannot be combined with settings or dependency overrides"
            )
        resolved_container = container
    else:
        if resolved_settings.persistence.backend == "postgres":
            if memory is not None:
                raise ValueError(
                    "memory override cannot be combined with postgres persistence"
                )
            resolved_container = None
        else:
            resolved_container = ApplicationContainer.create(
                settings=resolved_settings,
                run_service=run_service,
                knowledge_base=knowledge_base,
                memory=memory,
                authenticator=authenticator,
            )
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        nonlocal resolved_container
        if resolved_container is None:
            assert container is None
            resolved_container = await ApplicationContainer.open(
                settings=resolved_settings,
                run_service=run_service,
                knowledge_base=knowledge_base,
                authenticator=authenticator,
            )
            _app.state.container = resolved_container
        try:
            await resolved_container.start()
            yield
        finally:
            await resolved_container.close()

    app = FastAPI(
        title="AI Agent Learning API",
        version="0.5.0",
        lifespan=lifespan,
    )
    app.add_middleware(_ApplicationAdmissionMiddleware)
    app.state.container = resolved_container

    def current_container() -> ApplicationContainer:
        current = app.state.container
        if not isinstance(current, ApplicationContainer):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Application is not ready",
            )
        return current

    def current_principal(
        authorization: str | None = Header(default=None),
    ) -> Principal:
        try:
            return current_container().authenticator.authenticate(authorization)
        except AuthenticationError as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bearer credential",
                headers={"WWW-Authenticate": "Bearer"},
            ) from error

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post(
        "/api/sessions",
        response_model=SessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_session(
        principal: Principal = Depends(current_principal),
    ) -> SessionResponse:
        service = current_container().run_service
        created = service.create_session(
            principal_id=principal.principal_id if principal.authenticated else None
        )
        return SessionResponse(
            id=created.session.id,
            created_at=created.session.created_at,
            access_token=created.access_token,
        )

    @app.post("/api/sessions/{session_id}/runs", response_model=RunResponse)
    def create_run(
        session_id: str,
        request: RunRequest,
        principal: Principal = Depends(current_principal),
        x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    ) -> RunResponse:
        service = current_container().run_service
        execution_principal = resolve_session_principal(
            session_id,
            principal=principal,
            access_token=x_session_token,
        )
        return _to_run_response(
            service.create_run(
                session_id,
                request.message,
                execution_context=execution_principal.to_tool_context(),
                cancellation_token=CancellationToken(timeout_ms=request.timeout_ms),
            )
        )

    @app.post("/api/sessions/{session_id}/runs/stream")
    async def stream_run(
        session_id: str,
        request: RunRequest,
        http_request: Request,
        principal: Principal = Depends(current_principal),
        x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    ) -> StreamingResponse:
        service = current_container().run_service
        execution_principal = resolve_session_principal(
            session_id,
            principal=principal,
            access_token=x_session_token,
        )

        async def event_stream():
            if await http_request.is_disconnected():
                return
            cancellation_token = CancellationToken(timeout_ms=request.timeout_ms)
            run_task = asyncio.create_task(
                asyncio.to_thread(
                    service.create_run,
                    session_id,
                    request.message,
                    execution_context=execution_principal.to_tool_context(),
                    cancellation_token=cancellation_token,
                )
            )
            run_task.add_done_callback(_consume_task_result)
            try:
                while not run_task.done():
                    if await http_request.is_disconnected():
                        cancellation_token.cancel("client_disconnected")
                        await _wait_for_cancelled_run(run_task)
                        return
                    await asyncio.sleep(0.02)
                run = await run_task
            finally:
                if not run_task.done():
                    cancellation_token.cancel("stream_closed")
            for index, event_type in enumerate(run.event_types):
                if await http_request.is_disconnected():
                    return
                data: dict[str, object] = {"run_id": run.id, "index": index}
                if event_type == "run.completed":
                    data["answer"] = run.answer
                if event_type == "run.failed":
                    data["error"] = run.error
                yield _format_sse(event_type, data)
                await asyncio.sleep(0.04)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/sessions/{session_id}", response_model=SessionResponse)
    def get_session(
        session_id: str,
        principal: Principal = Depends(current_principal),
        x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    ) -> SessionResponse:
        service = current_container().run_service
        session = service.get_session(
            session_id,
            principal_id=principal.principal_id if principal.authenticated else None,
            access_token=x_session_token if not principal.authenticated else None,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return SessionResponse(
            id=session.id,
            created_at=session.created_at,
        )

    @app.get("/api/runs/{run_id}", response_model=RunResponse)
    def get_run(
        run_id: str,
        principal: Principal = Depends(current_principal),
        x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    ) -> RunResponse:
        service = current_container().run_service
        run = service.get_run(
            run_id,
            principal_id=principal.principal_id if principal.authenticated else None,
            access_token=x_session_token if not principal.authenticated else None,
        )
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return _to_run_response(run)

    @app.post(
        "/api/durable/runs",
        response_model=DurableRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_durable_run(
        request: DurableRunRequest,
        principal: Principal = Depends(current_principal),
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
        ),
        x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    ) -> DurableRunResponse:
        if idempotency_key is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency-Key is required",
            )
        if not _is_valid_durable_idempotency_key(idempotency_key):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency-Key has an invalid format",
            )
        if (
            not principal.authenticated
            and x_session_token is None
            and len(idempotency_key.encode("utf-8")) < 32
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Anonymous Idempotency-Key must be at least 32 bytes",
            )
        container = current_container()
        access = await resolve_durable_access(
            request.session_id,
            principal=principal,
            capability=x_session_token,
            bootstrap_capability=idempotency_key,
            require_existing_session=request.session_id is not None,
        )
        settings = container.settings
        record = DurableRunRecord.create(
            run_id=str(uuid4()),
            session_id=access.session_id,
            owner_id=access.owner_id,
            runtime=settings.runtime,
            model_provider=settings.model_provider,
            model=(settings.openai_model or "mock"),
            input_text=request.message,
            idempotency_key=idempotency_key,
            created_at=datetime.now(UTC),
        )
        try:
            created = await container.run_store.create(record)
        except IdempotencyConflictError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency-Key conflicts with an existing Run",
            ) from error
        if created.created:
            task = asyncio.create_task(
                container.run_commands.execute(
                    created.record.id,
                    owner_id=access.owner_id,
                    execution_context=_durable_execution_context(
                        access,
                        container=container,
                    ),
                ),
                name=f"durable-run:{created.record.id}",
            )
            task.add_done_callback(_consume_durable_task_result)
        return await _to_durable_run_response(
            container,
            created.record,
            session_capability=(
                access.created_capability if created.created else None
            ),
        )

    @app.get("/api/durable/runs/{run_id}", response_model=DurableRunResponse)
    async def get_durable_run(
        run_id: str,
        principal: Principal = Depends(current_principal),
        x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    ) -> DurableRunResponse:
        container = current_container()
        access = _durable_access_for_existing_request(
            principal=principal,
            capability=x_session_token,
        )
        record = await container.run_store.get(run_id, owner_id=access.owner_id)
        if record is None:
            raise _durable_run_not_found()
        return await _to_durable_run_response(container, record)

    @app.get("/api/durable/runs/{run_id}/events")
    async def stream_durable_run_events(
        run_id: str,
        after: Annotated[int, Query(ge=0)] = 0,
        principal: Principal = Depends(current_principal),
        x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    ) -> StreamingResponse:
        container = current_container()
        access = _durable_access_for_existing_request(
            principal=principal,
            capability=x_session_token,
        )
        record = await container.run_store.get(run_id, owner_id=access.owner_id)
        if record is None:
            raise _durable_run_not_found()
        return StreamingResponse(
            _durable_event_stream(
                container,
                run_id=run_id,
                owner_id=access.owner_id,
                after_sequence=after,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get(
        "/api/durable/sessions/{session_id}/runs",
        response_model=list[DurableRunResponse],
    )
    async def list_durable_session_runs(
        session_id: str,
        principal: Principal = Depends(current_principal),
        x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    ) -> list[DurableRunResponse]:
        container = current_container()
        access = _durable_access_for_existing_request(
            principal=principal,
            capability=x_session_token,
            session_id=session_id,
        )
        records = await container.run_store.list_for_session(
            session_id,
            owner_id=access.owner_id,
        )
        if not records:
            raise _durable_session_not_found()
        return [
            await _to_durable_run_response(container, record)
            for record in records
        ]

    @app.post(
        "/api/durable/runs/{run_id}/cancel",
        response_model=DurableRunResponse,
    )
    async def cancel_durable_run(
        run_id: str,
        principal: Principal = Depends(current_principal),
        x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    ) -> DurableRunResponse:
        container = current_container()
        access = _durable_access_for_existing_request(
            principal=principal,
            capability=x_session_token,
        )
        try:
            await container.run_commands.cancel(run_id, owner_id=access.owner_id)
        except RunNotFoundError as error:
            raise _durable_run_not_found() from error
        record = await container.run_store.get(run_id, owner_id=access.owner_id)
        if record is None:
            raise _durable_run_not_found()
        return await _to_durable_run_response(container, record)

    @app.post(
        "/api/durable/runs/{run_id}/approvals/{approval_id}",
        response_model=DurableRunResponse,
    )
    async def resolve_durable_approval(
        run_id: str,
        approval_id: str,
        request: ApprovalDecisionRequest,
        principal: Principal = Depends(current_principal),
        x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    ) -> DurableRunResponse:
        container = current_container()
        access = _durable_access_for_existing_request(
            principal=principal,
            capability=x_session_token,
        )
        record = await container.run_store.get(run_id, owner_id=access.owner_id)
        if record is None:
            raise _durable_run_not_found()
        if record.status is not RunStatus.WAITING_APPROVAL:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Run is not waiting for approval",
            )
        event = await _approval_event_for_run(
            container,
            run_id=run_id,
            owner_id=access.owner_id,
            approval_id=approval_id,
        )
        if event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Approval request not found",
            )
        try:
            resolved = await container.run_commands.resume_approval(
                run_id,
                owner_id=access.owner_id,
                approval_id=approval_id,
                tool_call_id=event["tool_call_id"],
                tool_name=event["tool_name"],
                arguments_digest=event["arguments_digest"],
                decision=request.decision,
                execution_context=_durable_execution_context(
                    access,
                    container=container,
                ),
            )
        except ApprovalResolutionError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Approval decision conflicts with the stored request",
            ) from error
        except (InvalidRunTransitionError, RunNotFoundError) as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Run approval state changed",
            ) from error
        return await _to_durable_run_response(container, resolved)

    @app.get(
        "/api/observability/runs",
        response_model=list[RunObservationResponse],
    )
    def list_run_observations(
        principal: Principal = Depends(current_principal),
    ) -> list[RunObservationResponse]:
        service = current_container().run_service
        _require_role(principal, "observer")
        observations = (
            service.observations()
            if "admin" in principal.roles
            else service.observations(principal_id=principal.principal_id)
        )
        return [
            _to_observation_response(observation) for observation in observations
        ]

    @app.post("/api/evals/default", response_model=EvalReportResponse)
    def run_default_evals() -> EvalReportResponse:
        def eval_runner(message: str):
            context = (
                ToolExecutionContext(roles=frozenset({"editor"}))
                if message.startswith("发布报告")
                else None
            )
            return execute_agent(message, execution_context=context)

        report = OfflineEvaluator(eval_runner).evaluate(
            [
                EvalCase(
                    id="direct-answer",
                    input="解释 Agent",
                    answer_contains=("Mock Agent",),
                    required_event_types=("run.completed",),
                    expected_usage_available=False,
                ),
                EvalCase(
                    id="tool-selection",
                    input="20 加 22",
                    answer_contains=("42",),
                    required_event_types=("tool.completed", "run.completed"),
                    required_tool_names=("add_numbers",),
                    required_successful_tool_names=("add_numbers",),
                ),
                EvalCase(
                    id="approval-denied",
                    input="发布报告 report-eval",
                    required_event_types=("tool.failed", "run.completed"),
                    required_tool_names=("publish_report",),
                    required_error_categories=("approval_required",),
                ),
            ]
        )
        return EvalReportResponse(**report.to_record())

    @app.post(
        "/api/knowledge/demo-seed",
        response_model=DocumentResponse,
    )
    def seed_demo_document() -> DocumentResponse:
        chunk_count = current_container().knowledge_base.seed(
            DEMO_COURSE_DOCUMENT
        )
        return DocumentResponse(
            id=DEMO_COURSE_DOCUMENT.id,
            chunk_count=chunk_count,
        )

    @app.post(
        "/api/knowledge/documents",
        response_model=DocumentResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def add_document(
        request: DocumentRequest,
        principal: Principal = Depends(current_principal),
    ) -> DocumentResponse:
        knowledge = current_container().knowledge_base
        _require_role(principal, "knowledge_editor")
        if request.id == DEMO_COURSE_DOCUMENT.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Document id is reserved by the application",
            )
        chunk_count = knowledge.add(
            Document(
                id=request.id,
                title=request.title,
                content=request.content,
                source=request.source,
            )
        )
        return DocumentResponse(id=request.id, chunk_count=chunk_count)

    @app.post("/api/research", response_model=ResearchResponse)
    def research(request: ResearchRequest) -> ResearchResponse:
        knowledge = current_container().knowledge_base
        result = create_research_workflow(knowledge).invoke(
            {
                "question": request.question,
                "evidence": [],
                "draft": "",
                "critique": "",
                "approved": False,
                "answer": "",
            }
        )
        return ResearchResponse(
            approved=result["approved"],
            answer=result["answer"],
            critique=result["critique"],
            evidence=[EvidenceResponse(**item) for item in result["evidence"]],
        )

    @app.post(
        "/api/memories", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED
    )
    async def remember(
        request: MemoryRequest,
        principal: Principal = Depends(current_principal),
    ) -> MemoryResponse:
        _require_authenticated(principal)
        try:
            fact = await current_container().async_memory_store.remember(
                owner_id=principal.principal_id,
                key=request.key,
                value=request.value,
                scope=MemoryScope(request.scope),
                approved=request.approved,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return MemoryResponse(
            id=fact.id,
            owner_id=fact.owner_id,
            key=fact.key,
            value=fact.value,
            scope=fact.scope.value,
        )

    @app.get("/api/memories", response_model=list[MemoryFactResponse])
    async def list_memories(
        principal: Principal = Depends(current_principal),
    ) -> list[MemoryFactResponse]:
        _require_authenticated(principal)
        facts = await current_container().async_memory_store.facts(
            principal.principal_id
        )
        return [_to_memory_fact_response(fact) for fact in facts]

    @app.get(
        "/api/memories/{fact_id}",
        response_model=MemoryFactResponse,
    )
    async def get_memory(
        fact_id: Annotated[
            str,
            Path(min_length=1, max_length=200, pattern=r"^\S(?:.*\S)?$"),
        ],
        principal: Principal = Depends(current_principal),
    ) -> MemoryFactResponse:
        _require_authenticated(principal)
        fact = await _owned_memory_fact(
            current_container(),
            fact_id,
            owner_id=principal.principal_id,
        )
        return _to_memory_fact_response(fact)

    @app.patch(
        "/api/memories/{fact_id}",
        response_model=MemoryFactResponse,
    )
    async def correct_memory(
        fact_id: Annotated[
            str,
            Path(min_length=1, max_length=200, pattern=r"^\S(?:.*\S)?$"),
        ],
        request: MemoryCorrectionRequest,
        principal: Principal = Depends(current_principal),
    ) -> MemoryFactResponse:
        _require_authenticated(principal)
        try:
            fact = await current_container().async_memory_store.correct_fact(
                CorrectMemoryFact(
                    fact_id=fact_id,
                    owner_id=principal.principal_id,
                    expected_version=request.expected_version,
                    value=request.value,
                    approved=request.approved,
                )
            )
        except PermissionError as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Memory correction requires explicit approval",
            ) from error
        except MemoryFactNotFoundError as error:
            raise _memory_not_found() from error
        except MemoryFactConflictError as error:
            raise _memory_version_conflict() from error
        return _to_memory_fact_response(fact)

    @app.get(
        "/api/memories/{fact_id}/audit",
        response_model=list[MemoryFactAuditResponse],
    )
    async def get_memory_audit(
        fact_id: Annotated[
            str,
            Path(min_length=1, max_length=200, pattern=r"^\S(?:.*\S)?$"),
        ],
        principal: Principal = Depends(current_principal),
    ) -> list[MemoryFactAuditResponse]:
        _require_authenticated(principal)
        audit = await current_container().async_memory_store.fact_audit(
            fact_id,
            owner_id=principal.principal_id,
        )
        if not audit:
            raise _memory_not_found()
        return [_to_memory_audit_response(record) for record in audit]

    @app.delete("/api/memories/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def forget(
        fact_id: Annotated[
            str,
            Path(min_length=1, max_length=200, pattern=r"^\S(?:.*\S)?$"),
        ],
        principal: Principal = Depends(current_principal),
        expected_version: int | None = Query(default=None, ge=0),
    ) -> None:
        _require_authenticated(principal)
        if expected_version is not None:
            try:
                await current_container().async_memory_store.delete_fact(
                    DeleteMemoryFact(
                        fact_id=fact_id,
                        owner_id=principal.principal_id,
                        expected_version=expected_version,
                    )
                )
            except MemoryFactNotFoundError as error:
                raise _memory_not_found() from error
            except MemoryFactConflictError as error:
                raise _memory_version_conflict() from error
            return
        if not await current_container().async_memory_store.forget(
            fact_id,
            owner_id=principal.principal_id,
        ):
            raise _memory_not_found()

    def resolve_session_principal(
        session_id: str,
        *,
        principal: Principal,
        access_token: str | None,
    ) -> Principal:
        service = current_container().run_service
        if principal.authenticated:
            if not service.has_session(
                session_id,
                principal_id=principal.principal_id,
            ):
                raise HTTPException(status_code=404, detail="Session not found")
            return principal
        session_principal_id = service.resolve_session_principal(
            session_id,
            access_token=access_token,
        )
        if session_principal_id is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return Principal(
            principal_id=session_principal_id,
            authenticated=False,
        )

    async def resolve_durable_access(
        session_id: str | None,
        *,
        principal: Principal,
        capability: str | None,
        bootstrap_capability: str | None = None,
        require_existing_session: bool,
    ) -> _DurableAccess:
        if principal.authenticated:
            access = _DurableAccess(
                owner_id=principal.principal_id,
                session_id=(
                    session_id
                    or _initial_durable_session_id(
                        principal.principal_id,
                        bootstrap_capability or "",
                    )
                ),
                roles=principal.roles,
            )
        else:
            resolved_capability = capability or bootstrap_capability
            if resolved_capability is None or not resolved_capability.strip():
                raise _durable_session_not_found()
            owner_id = _anonymous_durable_owner_id(resolved_capability)
            access = _DurableAccess(
                owner_id=owner_id,
                session_id=(
                    session_id
                    or _initial_durable_session_id(
                        owner_id,
                        resolved_capability,
                    )
                ),
                roles=frozenset(),
                created_capability=(
                    resolved_capability if capability is None else None
                ),
            )
        if require_existing_session:
            existing = await current_container().run_store.list_for_session(
                access.session_id,
                owner_id=access.owner_id,
            )
            if not existing:
                raise _durable_session_not_found()
        return access

    def _durable_access_for_existing_request(
        *,
        principal: Principal,
        capability: str | None,
        session_id: str | None = None,
    ) -> _DurableAccess:
        if principal.authenticated:
            return _DurableAccess(
                owner_id=principal.principal_id,
                session_id=session_id or "durable-session-lookup",
                roles=principal.roles,
            )
        if capability is None or not capability.strip():
            raise _durable_session_not_found()
        return _DurableAccess(
            owner_id=_anonymous_durable_owner_id(capability),
            session_id=session_id or "durable-session-lookup",
            roles=frozenset(),
        )

    return app


def _to_run_response(run: LegacyRunRecord) -> RunResponse:
    return RunResponse(
        id=run.id,
        session_id=run.session_id,
        status=run.status,
        answer=run.answer,
        event_types=list(run.event_types),
        error=run.error,
    )


@dataclass(frozen=True)
class _DurableAccess:
    owner_id: str
    session_id: str
    roles: frozenset[str]
    created_capability: str | None = None


def _anonymous_durable_owner_id(capability: str) -> str:
    if len(capability.encode("utf-8")) < 32:
        raise _durable_session_not_found()
    digest = hashlib.sha256(capability.encode("utf-8")).hexdigest()
    return f"anonymous-capability-v1-{digest}"


def _is_valid_durable_idempotency_key(value: str) -> bool:
    return (
        bool(value)
        and value == value.strip()
        and len(value.encode("utf-8")) <= 512
        and not any(
            character.isspace() or not character.isprintable()
            for character in value
        )
    )


def _initial_durable_session_id(owner_id: str, capability: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"durable-session-v1:{owner_id}:{capability}"))


def _durable_execution_context(
    access: _DurableAccess,
    *,
    container: ApplicationContainer,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        principal_id=access.owner_id,
        roles=access.roles,
        approval_store=container.approval_store,
    )


async def _to_durable_run_response(
    container: ApplicationContainer,
    record: DurableRunRecord,
    *,
    session_capability: str | None = None,
) -> DurableRunResponse:
    events = await _durable_events_for_snapshot(container, record)
    return DurableRunResponse(
        id=record.id,
        run_id=record.id,
        session_id=record.session_id,
        status=record.status.value,
        answer=record.answer,
        citations=_durable_citations(events),
        usage=_durable_usage(events),
        error=(
            DurableRunErrorResponse(
                code=record.failure.code,
                category=record.failure.category,
                retryable=record.failure.retryable,
            )
            if record.failure is not None
            else None
        ),
        created_at=record.created_at,
        updated_at=record.updated_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        session_capability=session_capability,
    )


async def _durable_events_for_snapshot(
    container: ApplicationContainer,
    record: DurableRunRecord,
) -> tuple[StoredRunEvent, ...]:
    cursor = 0
    events: list[StoredRunEvent] = []
    while True:
        batch = await container.event_store.list_for_run(
            record.id,
            owner_id=record.owner_id,
            after_sequence=cursor,
            limit=500,
        )
        if not batch:
            return tuple(events)
        events.extend(batch)
        cursor = batch[-1].sequence
        if len(batch) < 500:
            return tuple(events)


def _durable_citations(
    events: tuple[StoredRunEvent, ...],
) -> list[EvidenceResponse]:
    citations: list[EvidenceResponse] = []
    for event in events:
        if event.type != "rag.citations":
            continue
        parsed = _citation_projection(event.data)
        if parsed is not None:
            citations = parsed
    return citations


def _citation_projection(data: dict[str, object]) -> list[EvidenceResponse] | None:
    raw_citations = data.get("citations")
    if not isinstance(raw_citations, list) or not raw_citations:
        return None
    if len(raw_citations) > 16:
        return None
    citations: list[EvidenceResponse] = []
    for raw_citation in raw_citations:
        if not isinstance(raw_citation, dict):
            return None
        title = raw_citation.get("title")
        source = raw_citation.get("source")
        excerpt = raw_citation.get("excerpt")
        score = raw_citation.get("score")
        if (
            not isinstance(title, str)
            or not title
            or not isinstance(source, str)
            or not source
            or not isinstance(excerpt, str)
            or not excerpt
            or not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(float(score))
        ):
            return None
        citations.append(
            EvidenceResponse(
                title=title,
                source=source,
                excerpt=excerpt,
                score=float(score),
            )
        )
    return citations


def _durable_usage(
    events: tuple[StoredRunEvent, ...],
) -> ModelUsageResponse | None:
    usage: ModelUsageResponse | None = None
    for event in events:
        if event.type != "model.usage":
            continue
        parsed = _usage_projection(event.data)
        if parsed is not None:
            usage = parsed
    return usage


def _usage_projection(data: dict[str, object]) -> ModelUsageResponse | None:
    if data.get("scope") != "run":
        return None
    token_values = {
        name: data.get(name)
        for name in ("input_tokens", "output_tokens", "total_tokens")
    }
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in token_values.values()
    ):
        return None
    if (
        token_values["total_tokens"] == 0
        or token_values["total_tokens"]
        != token_values["input_tokens"] + token_values["output_tokens"]
    ):
        return None
    raw_cost = data.get("estimated_cost_usd")
    cost = (
        float(raw_cost)
        if isinstance(raw_cost, (int, float))
        and not isinstance(raw_cost, bool)
        and math.isfinite(float(raw_cost))
        and raw_cost >= 0
        else None
    )
    return ModelUsageResponse(
        input_tokens=token_values["input_tokens"],
        output_tokens=token_values["output_tokens"],
        total_tokens=token_values["total_tokens"],
        estimated_cost_usd=cost,
    )


def _durable_run_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")


def _durable_session_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Session not found",
    )


async def _approval_event_for_run(
    container: ApplicationContainer,
    *,
    run_id: str,
    owner_id: str,
    approval_id: str,
) -> dict[str, str] | None:
    events = await container.event_store.list_for_run(
        run_id,
        owner_id=owner_id,
    )
    for event in reversed(events):
        if (
            event.type == "run.waiting_approval"
            and event.data.get("approval_id") == approval_id
            and all(
                isinstance(event.data.get(key), str)
                for key in ("tool_call_id", "tool_name", "arguments_digest")
            )
        ):
            return {
                "tool_call_id": event.data["tool_call_id"],
                "tool_name": event.data["tool_name"],
                "arguments_digest": event.data["arguments_digest"],
            }
    return None


def _to_memory_fact_response(fact: MemoryFact) -> MemoryFactResponse:
    return MemoryFactResponse(
        id=fact.id,
        owner_id=fact.owner_id,
        key=fact.key,
        value=fact.value,
        scope=fact.scope.value,
        version=fact.version,
    )


def _to_memory_audit_response(
    record: MemoryFactAuditRecord,
) -> MemoryFactAuditResponse:
    return MemoryFactAuditResponse(
        fact_id=record.fact_id,
        version=record.version,
        action=record.action.value,
        value_digest=record.value_digest,
    )


async def _owned_memory_fact(
    container: ApplicationContainer,
    fact_id: str,
    *,
    owner_id: str,
) -> MemoryFact:
    facts = await container.async_memory_store.facts(owner_id)
    for fact in facts:
        if fact.id == fact_id:
            return fact
    raise _memory_not_found()


def _memory_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Memory not found",
    )


def _memory_version_conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Memory version conflict",
    )


def _to_observation_response(
    observation: RunObservation,
) -> RunObservationResponse:
    return RunObservationResponse(
        run_id=observation.run_id,
        status=observation.status,
        duration_ms=observation.duration_ms,
        event_count=observation.event_count,
        event_counts=dict(observation.event_counts),
        model_duration_ms=observation.model_duration_ms,
        tool_duration_ms=observation.tool_duration_ms,
        tool_durations_ms=dict(observation.tool_durations_ms),
        usage=(
            {
                "input_tokens": observation.usage.input_tokens,
                "output_tokens": observation.usage.output_tokens,
                "total_tokens": observation.usage.total_tokens,
                "estimated_cost_usd": observation.usage.estimated_cost_usd,
            }
            if observation.usage is not None
            else None
        ),
        error_count=observation.error_count,
        errors=[
            RunErrorResponse(
                category=error.category,
                event_type=error.event_type,
                step=error.step,
            )
            for error in observation.errors
        ],
    )


def _require_authenticated(principal: Principal) -> None:
    if not principal.authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _require_role(principal: Principal, role: str) -> None:
    _require_authenticated(principal)
    if role not in principal.roles and "admin" not in principal.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role required: {role}",
        )


async def _wait_for_cancelled_run(
    run_task: asyncio.Task[LegacyRunRecord],
) -> None:
    try:
        await asyncio.wait_for(asyncio.shield(run_task), timeout=0.25)
    except TimeoutError:
        return
    except asyncio.CancelledError:
        return
    except Exception:
        return


def _consume_task_result(run_task: asyncio.Task[LegacyRunRecord]) -> None:
    try:
        run_task.result()
    except asyncio.CancelledError:
        return
    except Exception as error:
        logger.warning(
            "Background run task failed",
            extra={"error_type": type(error).__name__},
        )


def _consume_durable_task_result(
    run_task: asyncio.Task[DurableRunRecord],
) -> None:
    try:
        run_task.result()
    except asyncio.CancelledError:
        return
    except Exception as error:
        logger.warning(
            "Durable background run task failed",
            extra={"error_type": type(error).__name__},
        )


app = create_app()


def _format_sse(event_type: str, data: dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


_DURABLE_SSE_HEARTBEAT_SECONDS = 15.0
_DURABLE_SSE_STORE_RECHECK_SECONDS = 1.0


async def _durable_event_stream(
    container: ApplicationContainer,
    *,
    run_id: str,
    owner_id: str,
    after_sequence: int,
) -> AsyncIterator[str]:
    """Replay owned durable events, then await committed event notifications."""

    cursor = after_sequence
    last_heartbeat_at = time.monotonic()
    async with container.event_notifier.subscribe(run_id) as signal:
        while True:
            events = await container.event_store.list_for_run(
                run_id,
                owner_id=owner_id,
                after_sequence=cursor,
            )
            for event in events:
                cursor = event.sequence
                yield _format_durable_sse(event)
            if events:
                continue

            record = await container.run_store.get(run_id, owner_id=owner_id)
            if record is None:
                return
            if record.status.is_terminal:
                trailing_events = await container.event_store.list_for_run(
                    run_id,
                    owner_id=owner_id,
                    after_sequence=cursor,
                )
                if trailing_events:
                    continue
                return

            elapsed = time.monotonic() - last_heartbeat_at
            wait_seconds = min(
                _DURABLE_SSE_STORE_RECHECK_SECONDS,
                max(_DURABLE_SSE_HEARTBEAT_SECONDS - elapsed, 0.0),
            )
            try:
                await asyncio.wait_for(signal.wait(), timeout=wait_seconds)
            except TimeoutError:
                pass
            else:
                signal.clear()

            if time.monotonic() - last_heartbeat_at >= _DURABLE_SSE_HEARTBEAT_SECONDS:
                last_heartbeat_at = time.monotonic()
                yield ": heartbeat\n\n"


def _format_durable_sse(event: StoredRunEvent) -> str:
    data: dict[str, object] = {
        "run_id": event.run_id,
        "sequence": event.sequence,
        "step": event.step,
        "created_at": event.created_at.isoformat(),
        "data": event.data,
    }
    return f"id: {event.sequence}\n" + _format_sse(event.type, data)
