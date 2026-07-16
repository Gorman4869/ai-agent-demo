from __future__ import annotations

import unittest

from backend.app.domain import Message
from backend.app.memory import ConversationMemory, MemoryScope


class MemoryTest(unittest.TestCase):
    def test_message_window_is_bounded(self) -> None:
        memory = ConversationMemory(message_limit=2)
        memory.append_message("s1", Message(role="user", content="one"))
        memory.append_message("s1", Message(role="assistant", content="two"))
        memory.append_message("s1", Message(role="user", content="three"))
        self.assertEqual(["two", "three"], [item.content for item in memory.messages("s1")])

    def test_long_term_memory_requires_approval_and_can_be_deleted(self) -> None:
        memory = ConversationMemory()
        with self.assertRaises(PermissionError):
            memory.remember(
                owner_id="user-1",
                key="preferred_language",
                value="Chinese",
                scope=MemoryScope.USER,
                approved=False,
            )

        fact = memory.remember(
            owner_id="user-1",
            key="preferred_language",
            value="Chinese",
            scope=MemoryScope.USER,
            approved=True,
        )
        self.assertEqual((fact,), memory.facts("user-1"))
        self.assertFalse(memory.forget(fact.id, owner_id="other-user"))
        self.assertTrue(memory.forget(fact.id, owner_id="user-1"))
        self.assertEqual((), memory.facts("user-1"))
