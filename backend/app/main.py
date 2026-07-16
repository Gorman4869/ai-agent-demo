from __future__ import annotations

import asyncio
import json
import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from backend.app.api.schemas import (
    DocumentRequest,
    DocumentResponse,
    EvidenceResponse,
    EvalReportResponse,
    HealthResponse,
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
from backend.app.container import ApplicationContainer
from backend.app.evals import EvalCase, OfflineEvaluator
from backend.app.knowledge import (
    DEMO_COURSE_DOCUMENT,
    Document,
    InMemoryKnowledgeBase,
    KnowledgeBase,
)
from backend.app.memory import ConversationMemory, MemoryScope
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


def create_app(
    run_service: InMemoryRunService | None = None,
    knowledge_base: KnowledgeBase | None = None,
    memory: ConversationMemory | None = None,
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
    if container is not None:
        if settings is not None or any(
            dependency is not None for dependency in legacy_dependencies
        ):
            raise ValueError(
                "container cannot be combined with settings or dependency overrides"
            )
        resolved_container = container
    else:
        resolved_container = ApplicationContainer.create(
            settings=settings,
            run_service=run_service,
            knowledge_base=knowledge_base,
            memory=memory,
            authenticator=authenticator,
        )
    service = resolved_container.run_service
    knowledge = resolved_container.knowledge_base
    conversation_memory = resolved_container.memory
    token_authenticator = resolved_container.authenticator
    demo_document_chunk_count = knowledge.add(DEMO_COURSE_DOCUMENT)
    app = FastAPI(title="AI Agent Learning API", version="0.5.0")
    app.state.container = resolved_container

    def current_principal(
        authorization: str | None = Header(default=None),
    ) -> Principal:
        try:
            return token_authenticator.authenticate(authorization)
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

    @app.get("/api/runs/{run_id}", response_model=RunResponse)
    def get_run(
        run_id: str,
        principal: Principal = Depends(current_principal),
        x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    ) -> RunResponse:
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
        return DocumentResponse(
            id=DEMO_COURSE_DOCUMENT.id,
            chunk_count=demo_document_chunk_count,
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
    def remember(
        request: MemoryRequest,
        principal: Principal = Depends(current_principal),
    ) -> MemoryResponse:
        _require_authenticated(principal)
        try:
            fact = conversation_memory.remember(
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

    @app.delete("/api/memories/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
    def forget(
        fact_id: str,
        principal: Principal = Depends(current_principal),
    ) -> None:
        _require_authenticated(principal)
        if not conversation_memory.forget(
            fact_id,
            owner_id=principal.principal_id,
        ):
            raise HTTPException(status_code=404, detail="Memory not found")

    def resolve_session_principal(
        session_id: str,
        *,
        principal: Principal,
        access_token: str | None,
    ) -> Principal:
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
