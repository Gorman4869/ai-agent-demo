from __future__ import annotations

import ipaddress
import socket
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol
from urllib.parse import urlsplit

from backend.app.advanced.browser_agent import canonical_browser_url
from backend.app.advanced.harness import PolicyViolation, content_digest


_DEFAULT_MAX_ADDRESSES = 16
_DEFAULT_MAX_REDIRECTS = 5


class BrowserAddressResolver(Protocol):
    def resolve(self, hostname: str, port: int) -> Sequence[str]: ...


class SystemBrowserAddressResolver:
    """Resolve a browser target without caching across validation boundaries."""

    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        records = socket.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
        return tuple(dict.fromkeys(record[4][0] for record in records))


class StaticBrowserAddressResolver:
    """Deterministic resolver for server-owned fixtures and security tests."""

    def __init__(self, addresses: Mapping[str, Sequence[str]]) -> None:
        copied: dict[str, tuple[str, ...]] = {}
        for hostname, values in addresses.items():
            canonical_hostname = _canonical_hostname(hostname)
            if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
                raise TypeError("static browser addresses must use sequences")
            copied[canonical_hostname] = tuple(values)
        self._addresses = MappingProxyType(copied)

    def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        del port
        try:
            return self._addresses[_canonical_hostname(hostname)]
        except KeyError as error:
            raise OSError("browser hostname is unavailable") from error


@dataclass(frozen=True)
class BrowserNetworkDecision:
    origin: str
    hostname: str
    port: int
    url_sha256: str
    canonical_url: str = field(repr=False)
    addresses: tuple[str, ...] = field(repr=False)


class BrowserNetworkPolicy:
    """Validate every browser navigation target and redirect before execution."""

    def __init__(
        self,
        resolver: BrowserAddressResolver,
        *,
        max_addresses: int = _DEFAULT_MAX_ADDRESSES,
        max_redirects: int = _DEFAULT_MAX_REDIRECTS,
    ) -> None:
        for field_name, value in (
            ("max_addresses", max_addresses),
            ("max_redirects", max_redirects),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        self._resolver = resolver
        self._max_addresses = max_addresses
        self._max_redirects = max_redirects

    def validate_url(self, value: str) -> BrowserNetworkDecision:
        canonical_url = canonical_browser_url(value)
        parts = urlsplit(canonical_url)
        hostname = parts.hostname
        if hostname is None:
            raise PolicyViolation(
                "invalid_browser_url",
                "browser URL has no hostname",
            )
        canonical_hostname = _canonical_hostname(hostname)
        port = parts.port or 443
        try:
            literal_address = ipaddress.ip_address(canonical_hostname)
        except ValueError:
            literal_address = None
        if literal_address is not None:
            raw_addresses: Sequence[str] = (str(literal_address),)
        else:
            try:
                raw_addresses = self._resolver.resolve(canonical_hostname, port)
            except (LookupError, OSError, UnicodeError) as error:
                raise PolicyViolation(
                    "browser_dns_unavailable",
                    "browser hostname resolution is unavailable",
                ) from error
        addresses = self._validate_addresses(raw_addresses)
        origin = f"{parts.scheme}://{parts.netloc}"
        return BrowserNetworkDecision(
            origin=origin,
            hostname=canonical_hostname,
            port=port,
            url_sha256=content_digest(canonical_url),
            canonical_url=canonical_url,
            addresses=addresses,
        )

    def validate_navigation_chain(
        self,
        start_url: str,
        redirects: Mapping[str, str],
    ) -> tuple[BrowserNetworkDecision, ...]:
        current_url = canonical_browser_url(start_url)
        decisions: list[BrowserNetworkDecision] = []
        seen: set[str] = set()
        for redirect_count in range(self._max_redirects + 1):
            if current_url in seen:
                raise PolicyViolation(
                    "browser_redirect_loop",
                    "browser redirect loop is disabled",
                )
            seen.add(current_url)
            decision = self.validate_url(current_url)
            decisions.append(decision)
            redirect_target = redirects.get(decision.canonical_url)
            if redirect_target is None:
                return tuple(decisions)
            if redirect_count >= self._max_redirects:
                raise PolicyViolation(
                    "browser_redirect_limit",
                    "browser redirect limit exceeded",
                )
            current_url = canonical_browser_url(redirect_target)
        raise AssertionError("redirect loop must return or fail")

    def _validate_addresses(self, values: Sequence[str]) -> tuple[str, ...]:
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise PolicyViolation(
                "browser_dns_invalid_response",
                "browser resolver returned an invalid response",
            )
        if not values or len(values) > self._max_addresses:
            raise PolicyViolation(
                "browser_dns_invalid_response",
                "browser resolver returned an invalid address count",
            )
        addresses: list[str] = []
        for value in values:
            if not isinstance(value, str) or "%" in value:
                raise PolicyViolation(
                    "browser_dns_invalid_response",
                    "browser resolver returned an invalid address",
                )
            try:
                address = ipaddress.ip_address(value)
            except ValueError as error:
                raise PolicyViolation(
                    "browser_dns_invalid_response",
                    "browser resolver returned an invalid address",
                ) from error
            if (
                not address.is_global
                or address.is_multicast
                or address.is_reserved
                or address.is_unspecified
            ):
                raise PolicyViolation(
                    "browser_address_not_allowed",
                    "browser target resolved to a non-public address",
                )
            rendered = str(address)
            if rendered not in addresses:
                addresses.append(rendered)
        return tuple(addresses)


def _canonical_hostname(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("browser hostname is invalid")
    if value.endswith(".") or any(ord(character) < 32 for character in value):
        raise ValueError("browser hostname is invalid")
    try:
        return value.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ValueError("browser hostname is invalid") from error


__all__ = [
    "BrowserAddressResolver",
    "BrowserNetworkDecision",
    "BrowserNetworkPolicy",
    "StaticBrowserAddressResolver",
    "SystemBrowserAddressResolver",
]
