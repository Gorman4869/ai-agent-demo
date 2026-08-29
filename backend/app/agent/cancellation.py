from __future__ import annotations

from collections.abc import Callable
from math import ceil, isfinite
from threading import Event, Lock
from time import monotonic


CancellationClock = Callable[[], float]


class RunCancelled(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CancellationToken:
    """Thread-safe cooperative cancellation and deadline signal."""

    def __init__(
        self,
        *,
        timeout_ms: int | None = None,
        clock: CancellationClock = monotonic,
    ) -> None:
        if timeout_ms is not None and timeout_ms < 1:
            raise ValueError("timeout_ms must be positive")
        self._clock = clock
        self._deadline = (
            clock() + timeout_ms / 1000 if timeout_ms is not None else None
        )
        self._event = Event()
        self._lock = Lock()
        self._reason: str | None = None

    def cancel(self, reason: str = "cancelled_by_caller") -> None:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("cancellation reason must not be empty")
        with self._lock:
            if self._event.is_set():
                return
            self._reason = normalized_reason
            self._event.set()

    @property
    def is_cancelled(self) -> bool:
        if (
            not self._event.is_set()
            and self._deadline is not None
            and self._clock() >= self._deadline
        ):
            self.cancel("deadline_exceeded")
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        return self._reason if self.is_cancelled else None

    @property
    def remaining_ms(self) -> int | None:
        if self._deadline is None:
            return None
        if self.is_cancelled:
            return 0
        return max(0, ceil((self._deadline - self._clock()) * 1_000))

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise RunCancelled(self._reason or "cancelled")

    def wait_for_cancellation(self, timeout_seconds: float) -> bool:
        """Wait for cancellation without delaying a caller past this deadline."""

        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not isfinite(timeout_seconds)
            or timeout_seconds < 0
        ):
            raise ValueError("timeout_seconds must be non-negative")
        if self.is_cancelled:
            return True
        wait_seconds = float(timeout_seconds)
        if self._deadline is not None:
            wait_seconds = min(
                wait_seconds,
                max(0.0, self._deadline - self._clock()),
            )
        self._event.wait(wait_seconds)
        return self.is_cancelled
