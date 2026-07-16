from __future__ import annotations

from dataclasses import dataclass

from backend.app.knowledge import InMemoryKnowledgeBase, KnowledgeBase
from backend.app.memory import ConversationMemory
from backend.app.security import StaticTokenAuthenticator
from backend.app.services import InMemoryRunService
from backend.app.settings import Settings


@dataclass(frozen=True)
class ApplicationContainer:
    """Small composition root for application-owned dependencies.

    Freezing the container prevents accidental rebinding. Its in-memory
    adapters remain mutable by design and will gain persistent alternatives in
    later milestones.
    """

    settings: Settings
    run_service: InMemoryRunService
    knowledge_base: KnowledgeBase
    memory: ConversationMemory
    authenticator: StaticTokenAuthenticator

    @classmethod
    def create(
        cls,
        *,
        settings: Settings | None = None,
        run_service: InMemoryRunService | None = None,
        knowledge_base: KnowledgeBase | None = None,
        memory: ConversationMemory | None = None,
        authenticator: StaticTokenAuthenticator | None = None,
    ) -> ApplicationContainer:
        return cls(
            settings=settings if settings is not None else Settings.from_environment(),
            run_service=(
                run_service if run_service is not None else InMemoryRunService()
            ),
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
