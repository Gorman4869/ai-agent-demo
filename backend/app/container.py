from __future__ import annotations

from dataclasses import dataclass

from backend.app.knowledge import InMemoryKnowledgeBase, KnowledgeBase
from backend.app.memory import ConversationMemory
from backend.app.security import StaticTokenAuthenticator
from backend.app.services import InMemoryRunService
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
        return cls(
            settings=resolved_settings,
            run_service=(
                run_service if run_service is not None else InMemoryRunService()
            ),
            run_store=resolved_run_store,
            event_store=resolved_event_store,
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
