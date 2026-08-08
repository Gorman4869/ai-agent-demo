from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from backend.app.agent import AgentRuntime, ManualRuntime
from backend.app.agent.graph_runtime import LangGraphRuntime
from backend.app.application_lifecycle import (
    ApplicationAdmission,
    ApplicationLifecycle,
    ApplicationLifecycleState,
    ApplicationRunCommands,
)
from backend.app.domain.run import RuntimeName
from backend.app.integrations.mcp import (
    McpClientManager,
    McpServerConfig,
    default_mcp_server_configs,
)
from backend.app.knowledge import InMemoryKnowledgeBase, KnowledgeBase
from backend.app.memory import ConversationMemory, MemoryStore
from backend.app.security import StaticTokenAuthenticator
from backend.app.services import InMemoryRunService, RunCoordinator
from backend.app.services.run_service import (
    create_learning_agent_loop,
    create_learning_model,
)
from backend.app.settings import Settings
from backend.app.skills import SkillAwareRuntime, default_skill_context_builder
from backend.app.stores import (
    AsyncApprovalStore,
    AsyncLocalApprovalStore,
    AsyncLocalMemoryStore,
    AsyncMemoryStore,
    EventStore,
    InMemoryEventStore,
    InMemoryRunStore,
    RunStore,
)
from backend.app.tools import ApprovalStore, InMemoryApprovalStore


LOGGER = logging.getLogger("application.container")


class _ClosableComposition(Protocol):
    async def close(self) -> None: ...


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
    mcp_clients: McpClientManager
    knowledge_base: KnowledgeBase
    memory: MemoryStore = field(repr=False)
    approval_store: ApprovalStore = field(repr=False)
    async_memory_store: AsyncMemoryStore = field(repr=False)
    async_approval_store: AsyncApprovalStore = field(repr=False)
    authenticator: StaticTokenAuthenticator
    admission: ApplicationAdmission = field(repr=False)
    run_commands: ApplicationRunCommands = field(repr=False)
    _lifecycle: ApplicationLifecycle = field(repr=False, compare=False)

    @property
    def lifecycle_state(self) -> ApplicationLifecycleState:
        return self._lifecycle.state

    async def start(self) -> None:
        await self._lifecycle.start()

    async def close(self) -> None:
        await self._lifecycle.close()

    @classmethod
    def create(
        cls,
        *,
        settings: Settings | None = None,
        run_service: InMemoryRunService | None = None,
        run_store: RunStore | None = None,
        event_store: EventStore | None = None,
        runtimes: Mapping[RuntimeName | str, AgentRuntime] | None = None,
        mcp_clients: McpClientManager | None = None,
        mcp_server_configs: Mapping[str, McpServerConfig] | None = None,
        knowledge_base: KnowledgeBase | None = None,
        memory: MemoryStore | None = None,
        approval_store: ApprovalStore | None = None,
        authenticator: StaticTokenAuthenticator | None = None,
    ) -> ApplicationContainer:
        if (run_store is None) != (event_store is None):
            raise ValueError("run_store and event_store must be provided together")
        if mcp_clients is not None and mcp_server_configs is not None:
            raise ValueError(
                "mcp_clients and mcp_server_configs cannot be provided together"
            )
        resolved_settings = (
            settings if settings is not None else Settings.from_environment()
        )
        if resolved_settings.persistence.backend != "memory":
            raise ValueError(
                "postgres persistence requires await ApplicationContainer.open()"
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
        resolved_runtimes = _resolve_runtimes(resolved_settings, runtimes)
        run_coordinator = RunCoordinator(
            run_store=resolved_run_store,
            event_store=resolved_event_store,
            runtimes=resolved_runtimes,
            run_timeout_ms=resolved_settings.budget.run_timeout_ms,
        )
        resolved_mcp_clients = _resolve_mcp_clients(
            resolved_settings,
            mcp_clients=mcp_clients,
            mcp_server_configs=mcp_server_configs,
        )
        resolved_memory = memory if memory is not None else ConversationMemory()
        resolved_approval_store = (
            approval_store
            if approval_store is not None
            else InMemoryApprovalStore()
        )
        admission = ApplicationAdmission(accepting=True)
        lifecycle = ApplicationLifecycle(
            admission=admission,
            mcp_clients=resolved_mcp_clients,
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
            mcp_clients=resolved_mcp_clients,
            knowledge_base=(
                knowledge_base
                if knowledge_base is not None
                else InMemoryKnowledgeBase()
            ),
            memory=resolved_memory,
            approval_store=resolved_approval_store,
            async_memory_store=AsyncLocalMemoryStore(resolved_memory),
            async_approval_store=AsyncLocalApprovalStore(
                resolved_approval_store
            ),
            authenticator=(
                authenticator
                if authenticator is not None
                else StaticTokenAuthenticator.from_environment(
                    approval_store=resolved_approval_store
                )
            ),
            admission=admission,
            run_commands=ApplicationRunCommands(run_coordinator, admission),
            _lifecycle=lifecycle,
        )

    @classmethod
    async def open(
        cls,
        *,
        settings: Settings | None = None,
        run_service: InMemoryRunService | None = None,
        runtimes: Mapping[RuntimeName | str, AgentRuntime] | None = None,
        mcp_clients: McpClientManager | None = None,
        mcp_server_configs: Mapping[str, McpServerConfig] | None = None,
        knowledge_base: KnowledgeBase | None = None,
        authenticator: StaticTokenAuthenticator | None = None,
    ) -> ApplicationContainer:
        """Open an explicitly configured PostgreSQL application container."""

        if mcp_clients is not None and mcp_server_configs is not None:
            raise ValueError(
                "mcp_clients and mcp_server_configs cannot be provided together"
            )
        resolved_settings = (
            settings if settings is not None else Settings.from_environment()
        )
        if resolved_settings.persistence.backend != "postgres":
            raise ValueError("ApplicationContainer.open() requires postgres persistence")
        postgres_dsn = resolved_settings.persistence.postgres_dsn
        if postgres_dsn is None:
            raise ValueError("postgres persistence requires a configured DSN")

        resolved_runtimes = _resolve_runtimes(resolved_settings, runtimes)
        resolved_mcp_clients = _resolve_mcp_clients(
            resolved_settings,
            mcp_clients=mcp_clients,
            mcp_server_configs=mcp_server_configs,
        )
        resolved_run_service = (
            run_service if run_service is not None else InMemoryRunService()
        )
        resolved_knowledge_base = (
            knowledge_base
            if knowledge_base is not None
            else InMemoryKnowledgeBase()
        )

        from backend.app.postgres_execution import PostgresExecutionComposition

        composition = await PostgresExecutionComposition.open(
            postgres_dsn.get_secret_value(),
            runtimes=resolved_runtimes,
            run_timeout_ms=resolved_settings.budget.run_timeout_ms,
        )
        try:
            persistence = composition.persistence
            resolved_authenticator = (
                authenticator
                if authenticator is not None
                else StaticTokenAuthenticator.from_environment()
            )
            admission = ApplicationAdmission()
            lifecycle = ApplicationLifecycle(
                admission=admission,
                mcp_clients=resolved_mcp_clients,
                execution_composition=composition,
            )
            return cls(
                settings=resolved_settings,
                run_service=resolved_run_service,
                run_store=persistence.run_store,
                event_store=persistence.event_store,
                runtimes=resolved_runtimes,
                run_coordinator=composition.coordinator,
                mcp_clients=resolved_mcp_clients,
                knowledge_base=resolved_knowledge_base,
                memory=persistence.memory_store,
                approval_store=persistence.approval_store,
                async_memory_store=persistence.async_memory_store,
                async_approval_store=persistence.async_approval_store,
                authenticator=resolved_authenticator,
                admission=admission,
                run_commands=ApplicationRunCommands(
                    composition.coordinator,
                    admission,
                ),
                _lifecycle=lifecycle,
            )
        except asyncio.CancelledError:
            await _close_composition_after_container_failure(composition)
            raise
        except Exception:
            await _close_composition_after_container_failure(composition)
            raise


def _resolve_runtimes(
    settings: Settings,
    runtimes: Mapping[RuntimeName | str, AgentRuntime] | None,
) -> Mapping[RuntimeName | str, AgentRuntime]:
    if runtimes is not None:
        return MappingProxyType(dict(runtimes))

    manual_runtime = ManualRuntime(
        lambda request, token: create_learning_agent_loop(
            request.input_text,
            execution_context=request.execution_context,
            cancellation_token=token,
            max_steps=settings.budget.max_steps,
            max_model_retries=settings.budget.max_model_retries,
            prompt_context=request.prompt_context,
        )
    )
    runtime_map: dict[RuntimeName | str, AgentRuntime] = {
        "manual": manual_runtime
    }
    if settings.runtime == "agents_sdk":
        runtime_map["agents_sdk"] = _create_agents_sdk_runtime(settings)
    elif settings.runtime == "langgraph":
        runtime_map["langgraph"] = _create_langgraph_runtime(settings)
    skill_context_builder = default_skill_context_builder()
    return MappingProxyType(
        {
            name: SkillAwareRuntime(
                runtime,
                builder=skill_context_builder,
            )
            for name, runtime in runtime_map.items()
        }
    )


def _resolve_mcp_clients(
    settings: Settings,
    *,
    mcp_clients: McpClientManager | None,
    mcp_server_configs: Mapping[str, McpServerConfig] | None,
) -> McpClientManager:
    if mcp_clients is not None:
        return mcp_clients
    return McpClientManager(
        settings=settings.mcp,
        allowed_servers=(
            mcp_server_configs
            if mcp_server_configs is not None
            else default_mcp_server_configs()
        ),
    )


async def _close_composition_after_container_failure(
    composition: _ClosableComposition,
) -> None:
    try:
        await composition.close()
    except (asyncio.CancelledError, Exception):
        LOGGER.error("PostgreSQL container startup cleanup failed")


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
            ),
            prompt_context=_request.prompt_context,
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


def _create_langgraph_runtime(settings: Settings) -> AgentRuntime:
    """Assemble the deterministic LangGraph comparison Runtime."""
    from backend.app.tools.builtin import create_default_registry

    if settings.runtime != "langgraph" or settings.model_provider != "mock":
        raise ValueError("langgraph runtime currently requires the mock provider")
    return LangGraphRuntime(
        model_factory=lambda request: create_learning_model(request.input_text),
        tool_registry_factory=lambda _request: create_default_registry(),
        max_steps=settings.budget.max_steps,
        max_model_retries=settings.budget.max_model_retries,
    )
