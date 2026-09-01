from __future__ import annotations

import base64
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol
from urllib.parse import urlsplit

from backend.app.advanced.browser_agent import (
    BrowserAction,
    BrowserActionKind,
    _parse_allowed_origin,
    canonical_browser_url,
)
from backend.app.advanced.harness import PolicyViolation, content_digest
from backend.app.advanced.browser_network import BrowserNetworkPolicy
from backend.app.advanced.process_runner import (
    BoundedProcessResult,
    ProcessResourceLimits,
    ProcessStartError,
    run_bounded_process,
)


_MAX_FIXTURE_DOCUMENTS = 32
_MAX_FIXTURE_DOCUMENT_BYTES = 256 * 1024
_MAX_FIXTURE_TOTAL_BYTES = 2 * 1024 * 1024
_DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_DEFAULT_MAX_SCREENSHOT_BYTES = 512 * 1024
_DEFAULT_MAX_TEXT_BYTES = 16 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ELEMENT_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}")
_DRIVER_ERROR_DETAILS = MappingProxyType(
    {
        "browser_action_timeout": "browser action exceeded its time budget",
        "browser_address_not_allowed": "browser target address is not allowed",
        "browser_cross_origin": "browser attempted a cross-origin navigation",
        "browser_download_blocked": "browser download is disabled",
        "browser_driver_invalid_response": (
            "browser driver returned an invalid response"
        ),
        "browser_driver_unavailable": "controlled browser runtime is unavailable",
        "browser_element_ambiguous": "browser element id is not unique",
        "browser_element_missing": "browser element is no longer available",
        "browser_fixture_not_found": "browser fixture document is unavailable",
        "browser_observation_required": "browser action requires a page observation",
        "browser_page_changed": "browser page no longer matches the observation",
        "browser_page_mismatch": "browser page does not match the planned origin",
        "browser_popup_blocked": "browser popup or new window is disabled",
        "browser_redirect_unplanned": "browser redirect was not prevalidated",
        "browser_upload_blocked": "browser upload is disabled",
        "browser_screenshot_too_large": "browser screenshot exceeded its size limit",
    }
)


class BrowserProcessRunner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
        max_output_bytes: int,
        resources: ProcessResourceLimits,
    ) -> BoundedProcessResult: ...


class BrowserDriver(Protocol):
    def validate(self, actions: Sequence[BrowserAction]) -> None: ...

    def execute(self, actions: Sequence[BrowserAction]) -> BrowserDriverRun: ...


@dataclass(frozen=True)
class BrowserFixtureSite:
    """Server-owned synthetic HTTPS documents for a network-free browser run."""

    origin: str
    documents: Mapping[str, str] = field(repr=False)
    redirects: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        canonical_origin = _parse_allowed_origin(self.origin)
        if not isinstance(self.documents, Mapping):
            raise TypeError("fixture documents must use a mapping")
        if len(self.documents) < 1 or len(self.documents) > _MAX_FIXTURE_DOCUMENTS:
            raise ValueError("fixture documents must use a bounded non-empty mapping")
        copied: dict[str, str] = {}
        total_bytes = 0
        for target, document in self.documents.items():
            if not isinstance(target, str) or not _is_fixture_target(target):
                raise ValueError("fixture targets must be absolute local URL paths")
            if not isinstance(document, str):
                raise TypeError("fixture documents must be strings")
            document_bytes = len(document.encode("utf-8"))
            if document_bytes < 1 or document_bytes > _MAX_FIXTURE_DOCUMENT_BYTES:
                raise ValueError("fixture document size is outside the allowed range")
            total_bytes += document_bytes
            if total_bytes > _MAX_FIXTURE_TOTAL_BYTES:
                raise ValueError("fixture document total exceeds the allowed range")
            copied[canonical_browser_url(f"{canonical_origin}{target}")] = document
        if not isinstance(self.redirects, Mapping):
            raise TypeError("fixture redirects must use a mapping")
        if len(self.redirects) > _MAX_FIXTURE_DOCUMENTS:
            raise ValueError("fixture redirects exceed the allowed count")
        copied_redirects: dict[str, str] = {}
        for source, target in self.redirects.items():
            if not isinstance(source, str) or not _is_fixture_target(source):
                raise ValueError("fixture redirect sources must be local URL paths")
            if not isinstance(target, str):
                raise TypeError("fixture redirect targets must be strings")
            source_url = canonical_browser_url(f"{canonical_origin}{source}")
            target_url = canonical_browser_url(target)
            if source_url in copied:
                raise ValueError("fixture documents and redirects must not overlap")
            copied_redirects[source_url] = target_url
        object.__setattr__(self, "origin", canonical_origin)
        object.__setattr__(self, "documents", MappingProxyType(copied))
        object.__setattr__(self, "redirects", MappingProxyType(copied_redirects))


@dataclass(frozen=True)
class BrowserDriverActionResult:
    action_id: str
    kind: str
    origin: str
    page_digest: str
    text: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class BrowserObservation:
    origin: str
    page_digest: str
    visible_element_ids: tuple[str, ...]
    screenshot_sha256: str
    screenshot_bytes: int
    url: str = field(repr=False)
    title: str = field(repr=False)
    text: str = field(repr=False)
    screenshot_png: bytes = field(repr=False)


@dataclass(frozen=True)
class BrowserDriverRun:
    actions: tuple[BrowserDriverActionResult, ...]
    observation: BrowserObservation
    driver: Literal["playwright"] = "playwright"
    network_access: Literal[False] = False


class PlaywrightBrowserDriver:
    """Run a validated plan in real Chromium against server-owned fixture pages."""

    def __init__(
        self,
        fixture_site: BrowserFixtureSite,
        *,
        network_policy: BrowserNetworkPolicy,
        node_executable: str | None = None,
        driver_script: Path | None = None,
        timeout_seconds: float = 30.0,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        max_screenshot_bytes: int = _DEFAULT_MAX_SCREENSHOT_BYTES,
        max_text_bytes: int = _DEFAULT_MAX_TEXT_BYTES,
        resources: ProcessResourceLimits | None = None,
        temporary_root: Path | None = None,
        process_runner: BrowserProcessRunner = run_bounded_process,
    ) -> None:
        for field_name, value in (
            ("max_response_bytes", max_response_bytes),
            ("max_screenshot_bytes", max_screenshot_bytes),
            ("max_text_bytes", max_text_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive")
        script = driver_script or _default_driver_script()
        script = Path(script).resolve(strict=True)
        if not script.is_file():
            raise ValueError("browser driver script must be a file")
        resolved_temporary_root = None
        if temporary_root is not None:
            resolved_temporary_root = Path(temporary_root).resolve(strict=True)
            if not resolved_temporary_root.is_dir():
                raise ValueError("temporary_root must be a directory")
        self._fixture_site = fixture_site
        self._network_policy = network_policy
        self._node_executable = node_executable
        self._driver_script = script
        self._timeout_seconds = float(timeout_seconds)
        self._max_response_bytes = max_response_bytes
        self._max_screenshot_bytes = max_screenshot_bytes
        self._max_text_bytes = max_text_bytes
        self._resources = resources or ProcessResourceLimits(
            max_processes=32,
            max_memory_bytes=1_024 * 1024 * 1024,
            max_cpu_seconds=60.0,
        )
        self._temporary_root = resolved_temporary_root
        self._process_runner = process_runner

    def validate(self, actions: Sequence[BrowserAction]) -> None:
        if not actions or not all(isinstance(action, BrowserAction) for action in actions):
            raise PolicyViolation(
                "invalid_browser_plan",
                "browser driver requires validated browser actions",
            )
        current_origin: str | None = None
        current_page_url: str | None = None
        for action in actions:
            if action.origin != self._fixture_site.origin:
                raise PolicyViolation(
                    "browser_page_mismatch",
                    "browser action origin does not match the fixture site",
                )
            if action.kind is BrowserActionKind.NAVIGATE:
                if (
                    action.url not in self._fixture_site.documents
                    and action.url not in self._fixture_site.redirects
                ):
                    raise PolicyViolation(
                        "browser_fixture_not_found",
                        _DRIVER_ERROR_DETAILS["browser_fixture_not_found"],
                    )
                decisions = self._network_policy.validate_navigation_chain(
                    action.url,
                    self._fixture_site.redirects,
                )
                if any(
                    decision.origin != self._fixture_site.origin
                    for decision in decisions
                ):
                    raise PolicyViolation(
                        "browser_cross_origin",
                        _DRIVER_ERROR_DETAILS["browser_cross_origin"],
                    )
                current_page_url = decisions[-1].canonical_url
                if current_page_url not in self._fixture_site.documents:
                    raise PolicyViolation(
                        "browser_fixture_not_found",
                        _DRIVER_ERROR_DETAILS["browser_fixture_not_found"],
                    )
                current_origin = action.origin
                continue
            if current_origin is None or current_page_url is None:
                raise PolicyViolation(
                    "navigation_required",
                    "navigate before executing browser DOM actions",
                )
            if action.page_url != current_page_url:
                raise PolicyViolation(
                    "browser_page_mismatch",
                    _DRIVER_ERROR_DETAILS["browser_page_mismatch"],
                )
            if action.expected_page_digest is None:
                raise PolicyViolation(
                    "browser_observation_required",
                    _DRIVER_ERROR_DETAILS["browser_observation_required"],
                )

    def execute(self, actions: Sequence[BrowserAction]) -> BrowserDriverRun:
        self.validate(actions)
        node_executable = self._resolve_node_executable()
        payload = self._request_payload(actions)
        try:
            with tempfile.TemporaryDirectory(
                prefix="ai-agent-browser-",
                dir=self._temporary_root,
            ) as temporary:
                temporary_path = Path(temporary)
                request_path = temporary_path / "request.json"
                response_path = temporary_path / "response.json"
                request_path.write_text(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    encoding="utf-8",
                )
                try:
                    request_path.chmod(0o600)
                except OSError:
                    pass
                completed = self._process_runner(
                    (
                        node_executable,
                        str(self._driver_script),
                        str(request_path),
                        str(response_path),
                    ),
                    cwd=self._driver_script.parent.parent,
                    environment=_browser_environment(),
                    timeout_seconds=self._timeout_seconds,
                    max_output_bytes=8 * 1024,
                    resources=self._resources,
                )
                response = self._read_response(response_path, completed)
        except ProcessStartError as error:
            raise PolicyViolation(
                "browser_driver_unavailable",
                "controlled browser process is unavailable",
            ) from error
        except OSError as error:
            raise PolicyViolation(
                "browser_driver_unavailable",
                "controlled browser files are unavailable",
            ) from error
        return self._parse_success(response, actions)

    def _resolve_node_executable(self) -> str:
        if self._node_executable is not None:
            candidate = Path(self._node_executable)
            if candidate.is_absolute() and candidate.is_file():
                return str(candidate)
            resolved = shutil.which(self._node_executable)
            if resolved is not None:
                return resolved
            raise PolicyViolation(
                "browser_driver_unavailable",
                "configured Node executable is unavailable",
            )
        resolved = shutil.which("node")
        if resolved is None:
            raise PolicyViolation(
                "browser_driver_unavailable",
                "Node executable is unavailable",
            )
        return resolved

    def _request_payload(self, actions: Sequence[BrowserAction]) -> dict[str, object]:
        encoded_actions: list[dict[str, object]] = []
        for action in actions:
            encoded: dict[str, object] = {
                "id": action.id,
                "kind": action.kind.value,
                "origin": action.origin,
            }
            if action.url is not None:
                encoded["url"] = action.url
                encoded["navigation_url"] = self._fixture_navigation_url(action.url)
            if action.element_id is not None:
                encoded["element_id"] = action.element_id
            if action.value is not None:
                encoded["value"] = action.value
            if action.expected_page_digest is not None:
                encoded["expected_page_digest"] = action.expected_page_digest
            encoded["page_url"] = action.page_url
            encoded_actions.append(encoded)
        return {
            "schema_version": 1,
            "fixture": {
                "origin": self._fixture_site.origin,
                "documents": dict(self._fixture_site.documents),
                "redirects": dict(self._fixture_site.redirects),
            },
            "actions": encoded_actions,
            "limits": {
                "action_timeout_ms": max(1, int(self._timeout_seconds * 500)),
                "max_screenshot_bytes": self._max_screenshot_bytes,
                "max_text_bytes": self._max_text_bytes,
            },
        }

    def _fixture_navigation_url(self, start_url: str) -> str:
        current_url = start_url
        seen: set[str] = set()
        while current_url in self._fixture_site.redirects:
            if current_url in seen:
                raise PolicyViolation(
                    "browser_redirect_loop",
                    "browser redirect loop is disabled",
                )
            seen.add(current_url)
            current_url = self._fixture_site.redirects[current_url]
        return current_url

    def _read_response(
        self,
        response_path: Path,
        completed: BoundedProcessResult,
    ) -> Mapping[str, object]:
        if completed.termination_reason == "timeout":
            raise PolicyViolation(
                "browser_action_timeout",
                _DRIVER_ERROR_DETAILS["browser_action_timeout"],
            )
        if completed.termination_reason == "resource_limit":
            raise PolicyViolation(
                "browser_resource_limit",
                "browser process exceeded its resource budget",
            )
        if not completed.process_tree_cleaned:
            raise PolicyViolation(
                "browser_process_cleanup_failed",
                "browser process tree cleanup failed",
            )
        if not completed.output_read_succeeded or completed.truncated:
            raise PolicyViolation(
                "browser_driver_invalid_response",
                "browser driver emitted unexpected process output",
            )
        if completed.stdout or completed.stderr:
            raise PolicyViolation(
                "browser_driver_invalid_response",
                "browser driver process output must be empty",
            )
        if not response_path.is_file():
            raise PolicyViolation(
                "browser_driver_invalid_response",
                "browser driver response is unavailable",
            )
        response_size = response_path.stat().st_size
        if response_size < 2 or response_size > self._max_response_bytes:
            raise PolicyViolation(
                "browser_driver_invalid_response",
                "browser driver response size is invalid",
            )
        try:
            response = json.loads(response_path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise PolicyViolation(
                "browser_driver_invalid_response",
                "browser driver response is invalid",
            ) from error
        if not isinstance(response, Mapping):
            raise PolicyViolation(
                "browser_driver_invalid_response",
                "browser driver response must be an object",
            )
        if response.get("ok") is False:
            code = response.get("code")
            if not isinstance(code, str) or code not in _DRIVER_ERROR_DETAILS:
                raise PolicyViolation(
                    "browser_driver_invalid_response",
                    "browser driver returned an unknown error",
                )
            raise PolicyViolation(code, _DRIVER_ERROR_DETAILS[code])
        if completed.return_code != 0 or response.get("ok") is not True:
            raise PolicyViolation(
                "browser_driver_invalid_response",
                "browser driver did not return a successful result",
            )
        return response

    def _parse_success(
        self,
        response: Mapping[str, object],
        actions: Sequence[BrowserAction],
    ) -> BrowserDriverRun:
        raw_actions = response.get("actions")
        raw_observation = response.get("observation")
        if not isinstance(raw_actions, list) or not isinstance(
            raw_observation, Mapping
        ):
            raise _invalid_driver_response()
        if len(raw_actions) != len(actions):
            raise _invalid_driver_response()
        parsed_actions: list[BrowserDriverActionResult] = []
        for expected, raw_action in zip(actions, raw_actions, strict=True):
            if not isinstance(raw_action, Mapping):
                raise _invalid_driver_response()
            action_id = raw_action.get("action_id")
            kind = raw_action.get("kind")
            origin = raw_action.get("origin")
            page_digest = raw_action.get("page_digest")
            text = raw_action.get("text")
            if (
                action_id != expected.id
                or kind != expected.kind.value
                or origin != expected.origin
                or not _is_digest(page_digest)
                or (text is not None and not isinstance(text, str))
            ):
                raise _invalid_driver_response()
            if isinstance(text, str) and len(text.encode("utf-8")) > self._max_text_bytes:
                raise _invalid_driver_response()
            parsed_actions.append(
                BrowserDriverActionResult(
                    action_id=action_id,
                    kind=kind,
                    origin=origin,
                    page_digest=page_digest,
                    text=text,
                )
            )
        observation = self._parse_observation(raw_observation)
        return BrowserDriverRun(tuple(parsed_actions), observation)

    def _parse_observation(
        self,
        raw_observation: Mapping[str, object],
    ) -> BrowserObservation:
        origin = raw_observation.get("origin")
        page_digest = raw_observation.get("page_digest")
        visible_element_ids = raw_observation.get("visible_element_ids")
        url = raw_observation.get("url")
        title = raw_observation.get("title")
        text = raw_observation.get("text")
        screenshot_base64 = raw_observation.get("screenshot_base64")
        if (
            origin != self._fixture_site.origin
            or not _is_digest(page_digest)
            or not isinstance(visible_element_ids, list)
            or not all(isinstance(value, str) for value in visible_element_ids)
            or not isinstance(url, str)
            or not isinstance(title, str)
            or not isinstance(text, str)
            or not isinstance(screenshot_base64, str)
        ):
            raise _invalid_driver_response()
        if (
            len(title.encode("utf-8")) > self._max_text_bytes
            or len(text.encode("utf-8")) > self._max_text_bytes
        ):
            raise _invalid_driver_response()
        if (
            len(visible_element_ids) > 256
            or len(set(visible_element_ids)) != len(visible_element_ids)
            or any(_ELEMENT_ID.fullmatch(value) is None for value in visible_element_ids)
        ):
            raise _invalid_driver_response()
        try:
            screenshot = base64.b64decode(screenshot_base64, validate=True)
        except (ValueError, TypeError) as error:
            raise _invalid_driver_response() from error
        if (
            len(screenshot) < len(_PNG_SIGNATURE)
            or len(screenshot) > self._max_screenshot_bytes
            or not screenshot.startswith(_PNG_SIGNATURE)
        ):
            raise _invalid_driver_response()
        try:
            observed_origin = _parse_allowed_origin(origin)
            url_origin = _origin_from_url(url)
        except (TypeError, ValueError, PolicyViolation) as error:
            raise _invalid_driver_response() from error
        if observed_origin != self._fixture_site.origin or url_origin != observed_origin:
            raise _invalid_driver_response()
        return BrowserObservation(
            origin=origin,
            page_digest=page_digest,
            visible_element_ids=tuple(visible_element_ids),
            screenshot_sha256=content_digest(screenshot),
            screenshot_bytes=len(screenshot),
            url=url,
            title=title,
            text=text,
            screenshot_png=screenshot,
        )


def _default_driver_script() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "frontend"
        / "scripts"
        / "controlled-browser-driver.mjs"
    )


def _browser_environment() -> dict[str, str]:
    allowed = (
        "HOME",
        "LOCALAPPDATA",
        "PATH",
        "SystemRoot",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    )
    return {name: os.environ[name] for name in allowed if name in os.environ}


def _is_fixture_target(value: str) -> bool:
    if not value.startswith("/") or value.startswith("//"):
        return False
    if "\\" in value or any(ord(character) < 32 for character in value):
        return False
    parts = urlsplit(value)
    return not parts.scheme and not parts.netloc and not parts.fragment


def _origin_from_url(value: str) -> str:
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        raise ValueError("URL must be absolute")
    return _parse_allowed_origin(f"{parts.scheme}://{parts.netloc}")


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _invalid_driver_response() -> PolicyViolation:
    return PolicyViolation(
        "browser_driver_invalid_response",
        "browser driver response failed validation",
    )


__all__ = [
    "BrowserDriver",
    "BrowserDriverActionResult",
    "BrowserDriverRun",
    "BrowserFixtureSite",
    "BrowserObservation",
    "PlaywrightBrowserDriver",
]
