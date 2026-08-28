from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from backend.app.domain.run import StoredRunEvent


class InProcessEventNotifier:
    """Wake live event readers without retaining event payloads.

    EventStore remains the replayable source of truth. A subscriber receives
    only a coalesced signal, then reads the persisted sequence it has not seen.
    """

    def __init__(self) -> None:
        self._listeners: dict[str, set[asyncio.Event]] = {}
        self._lock = asyncio.Lock()

    async def notify(self, event: StoredRunEvent) -> None:
        async with self._lock:
            listeners = tuple(self._listeners.get(event.run_id, ()))
        for listener in listeners:
            listener.set()

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Event]:
        signal = asyncio.Event()
        async with self._lock:
            self._listeners.setdefault(run_id, set()).add(signal)
        try:
            yield signal
        finally:
            async with self._lock:
                listeners = self._listeners.get(run_id)
                if listeners is None:
                    return
                listeners.discard(signal)
                if not listeners:
                    del self._listeners[run_id]
