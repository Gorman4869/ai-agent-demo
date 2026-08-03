from __future__ import annotations

import hashlib
import math
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Callable, Protocol

from backend.app.stores.base import StoreError


TokenFactory = Callable[[], str]


class RunLeaseMode(StrEnum):
    EXECUTION = "execution"
    RECOVERY = "recovery"


class RunLeaseUnavailableError(StoreError):
    code = "run_lease_unavailable"


class RunLeaseLostError(StoreError):
    code = "run_lease_lost"


class LeaseToken:
    """Opaque server credential whose string forms never reveal its value."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if (
            not isinstance(value, str)
            or value != value.strip()
            or not 32 <= len(value) <= 256
            or any(
                ord(character) < 33 or ord(character) > 126
                for character in value
            )
        ):
            raise ValueError("lease token has an invalid format")
        self._value = value

    def reveal(self) -> str:
        """Return the credential only at the persistence comparison boundary."""
        return self._value

    def __repr__(self) -> str:
        return "LeaseToken('**********')"

    def __str__(self) -> str:
        return "**********"


@dataclass(frozen=True)
class RunLease:
    """One server-owned execution or recovery lease handle."""

    run_id: str
    owner_id: str
    mode: RunLeaseMode
    version: int
    acquired_at: datetime
    heartbeat_at: datetime
    expires_at: datetime
    token: LeaseToken = field(repr=False)

    def __post_init__(self) -> None:
        _require_identifier(self.run_id, "lease run_id")
        _require_identifier(self.owner_id, "lease owner_id")
        try:
            mode = RunLeaseMode(self.mode)
        except (TypeError, ValueError):
            raise ValueError("lease mode is not supported") from None
        if (
            not isinstance(self.version, int)
            or isinstance(self.version, bool)
            or self.version < 0
        ):
            raise ValueError("lease version must be a non-negative integer")
        acquired_at = _as_utc(self.acquired_at, "lease acquired_at")
        heartbeat_at = _as_utc(self.heartbeat_at, "lease heartbeat_at")
        expires_at = _as_utc(self.expires_at, "lease expires_at")
        if heartbeat_at < acquired_at:
            raise ValueError("lease heartbeat_at must not precede acquired_at")
        if expires_at <= heartbeat_at:
            raise ValueError("lease expires_at must follow heartbeat_at")
        if not isinstance(self.token, LeaseToken):
            raise ValueError("lease token is required")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "acquired_at", acquired_at)
        object.__setattr__(self, "heartbeat_at", heartbeat_at)
        object.__setattr__(self, "expires_at", expires_at)

    def safe_summary(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "owner_id": self.owner_id,
            "mode": self.mode.value,
            "version": self.version,
            "acquired_at": self.acquired_at.isoformat(),
            "heartbeat_at": self.heartbeat_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


class RunLeaseStore(Protocol):
    """Server-owned lease arbitration for running durable Runs."""

    async def acquire(
        self,
        run_id: str,
        *,
        owner_id: str,
        ttl: timedelta,
    ) -> RunLease:
        ...

    async def heartbeat(
        self,
        lease: RunLease,
        *,
        ttl: timedelta,
    ) -> RunLease:
        """Extend an unexpired exact token/version lease with one CAS."""
        ...

    async def release(self, lease: RunLease) -> None:
        """Delete an unexpired exact token/version lease with one CAS."""
        ...

    async def claim_expired(
        self,
        *,
        limit: int,
        ttl: timedelta,
    ) -> tuple[RunLease, ...]:
        """Replace expired credentials with recovery handles at most once."""
        ...


@dataclass(frozen=True)
class _StoredRunLease:
    run_id: str
    mode: RunLeaseMode
    token_digest: str
    version: int
    acquired_at: datetime
    heartbeat_at: datetime
    expires_at: datetime


def _default_token_factory() -> str:
    return secrets.token_urlsafe(32)


def _issue_token(factory: TokenFactory | None) -> LeaseToken:
    return LeaseToken((factory or _default_token_factory)())


def _token_digest(token: LeaseToken) -> str:
    return hashlib.sha256(token.reveal().encode("ascii")).hexdigest()


def _to_handle(
    stored: _StoredRunLease,
    *,
    owner_id: str,
    token: LeaseToken,
) -> RunLease:
    return RunLease(
        run_id=stored.run_id,
        owner_id=owner_id,
        mode=stored.mode,
        version=stored.version,
        acquired_at=stored.acquired_at,
        heartbeat_at=stored.heartbeat_at,
        expires_at=stored.expires_at,
        token=token,
    )


def _require_lease(value: object) -> RunLease:
    if not isinstance(value, RunLease):
        raise ValueError("lease handle is required")
    return value


def _require_ttl(value: object) -> timedelta:
    if not isinstance(value, timedelta):
        raise ValueError("lease ttl must be a timedelta")
    seconds = value.total_seconds()
    if not math.isfinite(seconds) or seconds <= 0 or seconds > 86_400:
        raise ValueError("lease ttl must be between zero and one day")
    return value


def _require_scan_limit(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= 100
    ):
        raise ValueError("lease scan limit must be between 1 and 100")
    return value


def _require_identifier(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
    ):
        raise ValueError(f"{label} has an invalid format")


def _as_utc(value: object, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "LeaseToken",
    "RunLease",
    "RunLeaseLostError",
    "RunLeaseMode",
    "RunLeaseStore",
    "RunLeaseUnavailableError",
]
