from __future__ import annotations

from backend.app.agent import (
    ManualRuntime,
    RuntimeApprovalResume,
    RuntimeControl,
    RuntimeEventSink,
    RuntimeOutcome,
    RuntimeRequest,
)
from backend.app.agent.approval_runtime import (
    ApprovalLangGraphRuntime,
    PlannedToolCall,
)
from backend.app.container import ApplicationContainer
from backend.app.main import create_app
from backend.app.services.run_service import create_learning_agent_loop
from backend.app.settings import Settings
from backend.app.tools import (
    InMemoryApprovalStore,
    ToolDefinition,
    ToolRegistry,
    ToolRisk,
)


class _FrontendE2ERuntime:
    """Keep normal Mock runs while exposing one real approval interrupt."""

    def __init__(
        self,
        manual: ManualRuntime,
        approval: ApprovalLangGraphRuntime,
    ) -> None:
        self._manual = manual
        self._approval = approval

    async def run(
        self,
        request: RuntimeRequest,
        *,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ) -> RuntimeOutcome:
        runtime = (
            self._approval
            if request.input_text.startswith("发布报告 ")
            else self._manual
        )
        return await runtime.run(request, emit=emit, control=control)

    async def resume(
        self,
        request: RuntimeRequest,
        *,
        approval: RuntimeApprovalResume,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ) -> RuntimeOutcome:
        return await self._approval.resume(
            request,
            approval=approval,
            emit=emit,
            control=control,
        )


def _create_test_container() -> ApplicationContainer:
    settings = Settings.from_environment()
    approval_store = InMemoryApprovalStore()
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="publish_report",
            description="Publish one synthetic report in the browser E2E fixture.",
            input_schema={
                "type": "object",
                "properties": {"report_id": {"type": "string"}},
                "required": ["report_id"],
            },
            handler=lambda arguments: {
                "report_id": arguments["report_id"],
                "status": "published",
            },
            risk_level=ToolRisk.HIGH,
            has_side_effects=True,
        )
    )
    manual = ManualRuntime(
        lambda request, token: create_learning_agent_loop(
            request.input_text,
            execution_context=request.execution_context,
            cancellation_token=token,
            max_steps=settings.budget.max_steps,
            max_model_retries=settings.budget.max_model_retries,
            prompt_context=request.prompt_context,
        )
    )
    approval = ApprovalLangGraphRuntime(
        registry=registry,
        approval_store=approval_store,
        planner=lambda request: PlannedToolCall(
            call_id="frontend-e2e-publish-call",
            tool_name="publish_report",
            arguments={"report_id": request.input_text.removeprefix("发布报告 ")},
        ),
    )
    runtime = _FrontendE2ERuntime(manual, approval)
    return ApplicationContainer.create(
        settings=settings,
        runtimes={"manual": runtime},
        approval_store=approval_store,
    )


app = create_app(container=_create_test_container())
