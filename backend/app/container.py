from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from backend.app.agent import AgentRuntime, ManualRuntime
from backend.app.domain.run import RuntimeName
from backend.app.knowledge import InMemoryKnowledgeBase, KnowledgeBase
from backend.app.memory import ConversationMemory
from backend.app.security import StaticTokenAuthenticator
from backend.app.services import InMemoryRunService, RunCoordinator
from backend.app.services.run_service import create_learning_agent_loop
from backend.app.settings import Settings
from backend.app.stores import (
    EventStore,
    InMemoryEventStore,
    InMemoryRunStore,
    RunStore,
)


@dataclass(frozen=True)
class ApplicationContainer:
    """Small composition root for application-owned dependencies.

    Freezing the container prevents accidental rebinding. Its in-memory
    adapters remain mutable by design and will gain persistent alternatives in
    later milestones.
    """

    settings: Settings
    run_service: InMemoryRunService
    run_store: RunStore
    event_store: EventStore
    runtimes: Mapping[RuntimeName | str, AgentRuntime]
    run_coordinator: RunCoordinator
    knowledge_base: KnowledgeBase
    memory: ConversationMemory
    authenticator: StaticTokenAuthenticator

    @classmethod
    def create(
        cls,
        *,
        settings: Settings | None = None,
        run_service: InMemoryRunService | None = None,
        run_store: RunStore | None = None,
        event_store: EventStore | None = None,
        runtimes: Mapping[RuntimeName | str, AgentRuntime] | None = None,
        knowledge_base: KnowledgeBase | None = None,
        memory: ConversationMemory | None = None,
        authenticator: StaticTokenAuthenticator | None = None,
    ) -> ApplicationContainer:
        if (run_store is None) != (event_store is None):
            raise ValueError("run_store and event_store must be provided together")
        resolved_settings = (
            settings if settings is not None else Settings.from_environment()
        )
        if run_store is None:
            memory_run_store = InMemoryRunStore()
            resolved_run_store: RunStore = memory_run_store
            resolved_event_store: EventStore = InMemoryEventStore(
                memory_run_store
            )
        else:
            resolved_run_store = run_store
            assert event_store is not None
            resolved_event_store = event_store
        if runtimes is None:
            manual_runtime = ManualRuntime(
                lambda request, token: create_learning_agent_loop(
                    request.input_text,
                    execution_context=request.execution_context,
                    cancellation_token=token,
                    max_steps=resolved_settings.budget.max_steps,
                    max_model_retries=(
                        resolved_settings.budget.max_model_retries
                    ),
                )
            )
            runtime_map: dict[RuntimeName | str, AgentRuntime] = {
                "manual": manual_runtime
            }
            if resolved_settings.runtime == "agents_sdk":
                runtime_map["agents_sdk"] = _create_agents_sdk_runtime(
                    resolved_settings
                )
            resolved_runtimes: Mapping[RuntimeName | str, AgentRuntime] = (
                MappingProxyType(runtime_map)
            )
        else:
            resolved_runtimes = MappingProxyType(dict(runtimes))
        run_coordinator = RunCoordinator(
            run_store=resolved_run_store,
            event_store=resolved_event_store,
            runtimes=resolved_runtimes,
            run_timeout_ms=resolved_settings.budget.run_timeout_ms,
        )
        return cls(
            settings=resolved_settings,
            run_service=(
                run_service if run_service is not None else InMemoryRunService()
            ),
            run_store=resolved_run_store,
            event_store=resolved_event_store,
            runtimes=resolved_runtimes,
            run_coordinator=run_coordinator,
            knowledge_base=(
                knowledge_base
                if knowledge_base is not None
                else InMemoryKnowledgeBase()
            ),
            memory=memory if memory is not None else ConversationMemory(),
            authenticator=(
                authenticator
                if authenticator is not None
                else StaticTokenAuthenticator.from_environment()
            ),
        )


def _create_agents_sdk_runtime(settings: Settings) -> AgentRuntime:
    """Assemble the opt-in SDK adapter without creating a network request."""

    from backend.app.agent.sdk_runtime import (
        OpenAIAgentsRuntime,
        build_sdk_tools,
        create_openai_learning_agent,
        create_openai_model_factory,
    )
    from backend.app.tools.builtin import create_default_registry

    if (
        settings.runtime != "agents_sdk"
        or settings.model_provider != "openai"
        or not settings.online_provider_enabled
        or settings.trace_include_sensitive
        or settings.openai_api_key is None
        or settings.openai_model is None
    ):
        raise ValueError("agents_sdk runtime requires complete OpenAI settings")

    def create_agent(_request, run_context):
        return create_openai_learning_agent(
            tools=build_sdk_tools(
                create_default_registry(),
                run_context=run_context,
            )
        )

    return OpenAIAgentsRuntime(
        agent_factory=create_agent,
        model_factory=create_openai_model_factory(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.openai_model,
            timeout_ms=settings.budget.model_timeout_ms,
        ),
        provider=settings.model_provider,
        model=settings.openai_model,
        budget=settings.budget,
    )
