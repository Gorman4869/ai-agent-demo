from __future__ import annotations

import unittest

from backend.app.domain import Message
from backend.app.memory import (
    ConversationMemory,
    MemoryScope,
    MemoryStore,
)


class MemoryStoreContract:
    """Adapter-independent contract for memory and PostgreSQL."""

    async def asyncSetUp(self) -> None:
        self.memory_store = await self.create_memory_store(message_limit=2)

    async def create_memory_store(self, *, message_limit: int) -> MemoryStore:
        raise NotImplementedError

    async def test_message_window_preserves_the_latest_complete_messages(
        self,
    ) -> None:
        self.memory_store.append_message(
            "session-1",
            Message(role="user", content="one"),
        )
        self.memory_store.append_message(
            "session-1",
            Message(
                role="tool",
                content="two",
                name="lookup",
                tool_call_id="call-1",
            ),
        )
        self.memory_store.append_message(
            "session-1",
            Message(role="assistant", content="three"),
        )

        self.assertEqual(
            (
                Message(
                    role="tool",
                    content="two",
                    name="lookup",
                    tool_call_id="call-1",
                ),
                Message(role="assistant", content="three"),
            ),
            self.memory_store.messages("session-1"),
        )

    async def test_message_history_is_session_isolated(self) -> None:
        self.memory_store.append_message(
            "session-1",
            Message(role="user", content="private fixture message"),
        )

        self.assertEqual((), self.memory_store.messages("session-2"))

    async def test_long_term_memory_requires_explicit_approval(self) -> None:
        with self.assertRaises(PermissionError):
            self.memory_store.remember(
                owner_id="owner-1",
                key="language",
                value="Chinese",
                scope=MemoryScope.USER,
                approved=False,
            )
        self.assertEqual((), self.memory_store.facts("owner-1"))

    async def test_facts_are_trimmed_ordered_and_owner_isolated(self) -> None:
        first = self.memory_store.remember(
            owner_id="owner-1",
            key=" language ",
            value=" Chinese ",
            scope=MemoryScope.USER,
            approved=True,
        )
        second = self.memory_store.remember(
            owner_id="owner-1",
            key="timezone",
            value="Asia/Shanghai",
            scope=MemoryScope.SESSION,
            approved=True,
        )

        self.assertEqual("language", first.key)
        self.assertEqual("Chinese", first.value)
        self.assertEqual((first, second), self.memory_store.facts("owner-1"))
        self.assertEqual((), self.memory_store.facts("owner-2"))

    async def test_forget_does_not_disclose_or_delete_another_owner(self) -> None:
        fact = self.memory_store.remember(
            owner_id="owner-1",
            key="language",
            value="Chinese",
            scope=MemoryScope.USER,
            approved=True,
        )

        self.assertFalse(
            self.memory_store.forget(fact.id, owner_id="owner-2")
        )
        self.assertTrue(
            self.memory_store.forget(fact.id, owner_id="owner-1")
        )
        self.assertFalse(
            self.memory_store.forget(fact.id, owner_id="owner-1")
        )


class InMemoryMemoryStoreContractTest(
    MemoryStoreContract,
    unittest.IsolatedAsyncioTestCase,
):
    async def create_memory_store(self, *, message_limit: int) -> MemoryStore:
        return ConversationMemory(message_limit=message_limit)


if __name__ == "__main__":
    unittest.main()
