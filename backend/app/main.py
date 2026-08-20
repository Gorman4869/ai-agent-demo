from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

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
    EvidenceResponse,
    EvalReportResponse,
    HealthResponse,
    MemoryCorrectionRequest,
    MemoryFactAuditResponse,
    MemoryFactResponse,
    MemoryRequest,
    MemoryResponse,
    ResearchRequest,
    ResearchResponse,
    RunErrorResponse,
    RunObservationResponse,
    RunRequest,
    RunResponse,
    SessionResponse,
)
from backend.app.agent import CancellationToken
from backend.app.agent.research_workflow import create_research_workflow
from backend.app.application_lifecycle import ApplicationNotAcceptingError
from backend.app.container import ApplicationContainer
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
from backend.app.tools import ToolExecutionContext


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


app = create_app()


def _format_sse(event_type: str, data: dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"
