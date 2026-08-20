from __future__ import annotations

import asyncio
import unittest

from backend.app.domain import Message
from backend.app.memory import (
    ConversationMemory,
    MemoryScope,
    MemoryStore,
    MemoryTurnConflictError,
    PublishTurn,
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

    async def test_publish_turn_is_atomic_idempotent_and_session_isolated(
        self,
    ) -> None:
        command = _turn("run-1", session_id="session-1")
        rendered = repr(command)

        created = self.memory_store.publish_turn(command)
        replay = self.memory_store.publish_turn(command)

        self.assertNotIn(command.session_id, rendered)
        self.assertNotIn(command.user_message.content, rendered)
        self.assertNotIn(command.assistant_message.content, rendered)
        self.assertEqual(64, len(command.digest))
        self.assertTrue(created.created)
        self.assertFalse(replay.created)
        self.assertEqual(
            (command.user_message, command.assistant_message),
            self.memory_store.messages("session-1"),
        )
        self.assertEqual((), self.memory_store.messages("session-2"))

    async def test_publish_turn_replay_with_changed_binding_conflicts(
        self,
    ) -> None:
        original = _turn("run-conflict", session_id="session-1")
        self.memory_store.publish_turn(original)

        for changed in (
            _turn("run-conflict", session_id="session-2"),
            _turn("run-conflict", user_content="changed user"),
            _turn("run-conflict", assistant_content="changed assistant"),
        ):
            with self.subTest(changed=changed.digest):
                with self.assertRaises(MemoryTurnConflictError) as raised:
                    self.memory_store.publish_turn(changed)
                self.assertEqual("memory_turn_conflict", raised.exception.code)

        self.assertEqual(
            (original.user_message, original.assistant_message),
            self.memory_store.messages("session-1"),
        )
        self.assertEqual((), self.memory_store.messages("session-2"))

    async def test_concurrent_publish_turn_has_one_winner_and_one_pair(
        self,
    ) -> None:
        command = _turn("run-concurrent")

        first, second = await asyncio.gather(
            asyncio.to_thread(self.memory_store.publish_turn, command),
            asyncio.to_thread(self.memory_store.publish_turn, command),
        )

        self.assertEqual([False, True], sorted((first.created, second.created)))
        self.assertEqual(
            (command.user_message, command.assistant_message),
            self.memory_store.messages(command.session_id),
        )

    async def test_publish_turn_uses_the_existing_bounded_message_window(
        self,
    ) -> None:
        store = await self.create_memory_store(message_limit=3)
        first = _turn("run-window-1", user_content="one", assistant_content="two")
        second = _turn(
            "run-window-2",
            user_content="three",
            assistant_content="four",
        )

        store.publish_turn(first)
        store.publish_turn(second)

        self.assertEqual(
            (
                first.assistant_message,
                second.user_message,
                second.assistant_message,
            ),
            store.messages("session-1"),
        )

    async def test_publish_turn_rejects_invalid_commands_before_mutation(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            self.memory_store.publish_turn(object())  # type: ignore[arg-type]
        for kwargs in (
            {"run_id": " run-1 "},
            {"session_id": ""},
            {"user_message": Message(role="assistant", content="wrong")},
            {
                "assistant_message": Message(
                    role="assistant",
                    content="answer",
                    name="unexpected",
                )
            },
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    _turn(**kwargs)
        self.assertEqual((), self.memory_store.messages("session-1"))

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


def _turn(
    run_id: str = "run-1",
    *,
    session_id: str = "session-1",
    user_content: str = "user fixture",
    assistant_content: str = "assistant fixture",
    user_message: Message | None = None,
    assistant_message: Message | None = None,
) -> PublishTurn:
    return PublishTurn(
        run_id=run_id,
        session_id=session_id,
        user_message=(
            user_message
            if user_message is not None
            else Message(role="user", content=user_content)
        ),
        assistant_message=(
            assistant_message
            if assistant_message is not None
            else Message(role="assistant", content=assistant_content)
        ),
    )


class InMemoryMemoryStoreContractTest(
    MemoryStoreContract,
    unittest.IsolatedAsyncioTestCase,
):
    async def create_memory_store(self, *, message_limit: int) -> MemoryStore:
        return ConversationMemory(message_limit=message_limit)


if __name__ == "__main__":
    unittest.main()
