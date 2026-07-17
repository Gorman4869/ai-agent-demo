from __future__ import annotations

import io
import json
import os
import secrets
import shutil
import subprocess
import unittest
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from backend.app.agent import RuntimeEvent, RuntimeResult
from backend.app.container import ApplicationContainer
from backend.app.domain.run import RunRecord, RunStatus, StoredRunEvent
from backend.app.online_smoke import (
    OnlineSmokeError,
    TokenPrices,
    build_online_summary,
    execute_online_smoke,
    load_online_settings,
    run_cli,
    validate_low_budget,
)
from backend.app.security import StaticTokenAuthenticator
from backend.app.settings import Settings


_REPO_ROOT = Path(__file__).resolve().parents[2]


class ExplodingEnvironment(Mapping[str, str]):
    def __getitem__(self, key: str) -> str:
        raise AssertionError(f"environment was read: {key}")

    def __iter__(self) -> Iterator[str]:
        raise AssertionError("environment was iterated")

    def __len__(self) -> int:
        raise AssertionError("environment length was read")


class SuccessfulOnlineRuntime:
    async def run(self, request, *, emit, control) -> RuntimeResult:
        del control
        await emit(
            RuntimeEvent(
                type="model.output.delta",
                step=1,
                data={"delta": "5", "segment": 1},
            )
        )
        await emit(
            RuntimeEvent(
                type="tool.started",
                step=2,
                data={"id": "call-1", "name": "add_numbers"},
            )
        )
        await emit(
            RuntimeEvent(
                type="tool.completed",
                step=3,
                data={
                    "id": "call-1",
                    "name": "add_numbers",
                    "ok": True,
                },
            )
        )
        await emit(
            RuntimeEvent(
                type="model.usage",
                step=4,
                data={
                    "scope": "run",
                    "provider": "openai",
                    "model": "online-smoke-model",
                    "requests": 2,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "estimated_cost_usd": None,
                    "cost_source": "unknown",
                },
            )
        )
        self.last_input = request.input_text
        return RuntimeResult(
            status=RunStatus.COMPLETED,
            answer="5",
            step=4,
        )


class OnlineSmokeGateTests(unittest.TestCase):
    def test_unauthorized_cli_does_not_read_environment_or_call_executor(self) -> None:
        called = False

        async def executor(settings, prices):
            nonlocal called
            called = True
            return {}

        stderr = io.StringIO()

        exit_code = run_cli(
            [],
            environment=ExplodingEnvironment(),
            executor=executor,
            stdout=io.StringIO(),
            stderr=stderr,
        )

        self.assertEqual(64, exit_code)
        self.assertFalse(called)
        self.assertIn("authorization is missing", stderr.getvalue())

    def test_online_settings_require_agents_sdk_runtime(self) -> None:
        environment = _online_environment(AI_AGENT_RUNTIME="langgraph")

        with self.assertRaisesRegex(
            OnlineSmokeError,
            "AI_AGENT_RUNTIME must be agents_sdk",
        ) as raised:
            load_online_settings(environment, authorized=True)

        self.assertEqual(65, raised.exception.exit_code)

    def test_default_broad_budget_is_refused(self) -> None:
        settings = Settings.from_environment(
            _online_environment(include_low_budget=False)
        )

        with self.assertRaisesRegex(
            OnlineSmokeError,
            "online smoke requires low limits",
        ) as raised:
            validate_low_budget(settings, _prices())

        self.assertEqual(65, raised.exception.exit_code)

    def test_declared_price_upper_bound_must_fit_cost_cap(self) -> None:
        settings = Settings.from_environment(
            _online_environment(AI_AGENT_MAX_COST_USD="0.001")
        )

        with self.assertRaisesRegex(
            OnlineSmokeError,
            "upper bound exceeds",
        ):
            validate_low_budget(settings, _prices())

    def test_token_prices_must_be_positive_finite_decimals(self) -> None:
        for input_price, output_price in (
            ("invalid", "1"),
            ("0", "1"),
            ("1", "NaN"),
        ):
            with self.subTest(
                input_price=input_price,
                output_price=output_price,
            ):
                with self.assertRaises(OnlineSmokeError) as raised:
                    TokenPrices.from_strings(input_price, output_price)
                self.assertEqual(65, raised.exception.exit_code)

    def test_successful_cli_output_excludes_provider_credential(self) -> None:
        environment = _online_environment()
        credential = environment["OPENAI_API_KEY"]

        async def executor(settings, prices):
            self.assertIsNotNone(settings.openai_api_key)
            self.assertEqual(_prices(), prices)
            return {"suite": "M8-T6", "exit_code": 0}

        stdout = io.StringIO()

        exit_code = run_cli(
            [
                "--authorized",
                "--input-price-per-million-usd",
                "1.25",
                "--output-price-per-million-usd",
                "5",
            ],
            environment=environment,
            executor=executor,
            stdout=stdout,
            stderr=io.StringIO(),
        )

        self.assertEqual(0, exit_code)
        self.assertEqual(
            {"exit_code": 0, "suite": "M8-T6"},
            json.loads(stdout.getvalue()),
        )
        self.assertNotIn(credential, stdout.getvalue())


class OnlineSmokeExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_fake_runtime_exercises_durable_vertical_slice(self) -> None:
        settings = Settings.from_environment(_online_environment())
        runtime = SuccessfulOnlineRuntime()

        def create_container(config: Settings) -> ApplicationContainer:
            return ApplicationContainer.create(
                settings=config,
                runtimes={"agents_sdk": runtime},
                authenticator=StaticTokenAuthenticator(),
            )

        timestamps = iter((10.0, 10.25))

        summary = await execute_online_smoke(
            settings,
            _prices(),
            container_factory=create_container,
            clock=lambda: next(timestamps),
        )

        self.assertEqual("completed", summary["status"])
        self.assertEqual("online-smoke-model", summary["model"])
        self.assertEqual(250.0, summary["duration_ms"])
        self.assertEqual(1, summary["stream_delta_count"])
        self.assertEqual(
            {"name": "add_numbers", "completed": True},
            summary["tool"],
        )
        self.assertEqual(120, summary["usage"]["total_tokens"])
        self.assertEqual("0.00022500", summary["estimated_cost_usd"])
        self.assertIn("add_numbers", runtime.last_input)

    async def test_failed_runtime_exposes_only_stable_failure_code(self) -> None:
        failed = _queued_run().transition_to(
            RunStatus.RUNNING,
            at=_now() + timedelta(seconds=1),
        ).transition_to(
            RunStatus.FAILED,
            at=_now() + timedelta(seconds=2),
            error_code="provider_unavailable",
            public_message="sensitive provider detail",
        )

        with self.assertRaisesRegex(
            OnlineSmokeError,
            "provider_unavailable",
        ) as raised:
            build_online_summary(
                failed,
                (),
                duration_ms=1,
                prices=_prices(),
                max_cost_usd=Decimal("0.05"),
            )

        self.assertNotIn("sensitive provider detail", str(raised.exception))


class OnlineSmokeEvidenceTests(unittest.TestCase):
    def test_stream_tool_and_usage_evidence_are_all_required(self) -> None:
        run = _completed_run()
        events = list(_successful_events(run))
        cases = {
            "streamed model output": [
                event for event in events if event.type != "model.output.delta"
            ],
            "tool completion": [
                event for event in events if event.type != "tool.completed"
            ],
            "exactly one model.usage": [
                event for event in events if event.type != "model.usage"
            ],
        }

        for message, incomplete_events in cases.items():
            with self.subTest(message=message):
                resequenced = _resequence(incomplete_events)
                with self.assertRaisesRegex(OnlineSmokeError, message):
                    _build_summary(run, resequenced)

    def test_usage_values_must_be_positive_and_consistent(self) -> None:
        run = _completed_run()
        cases = (
            {"input_tokens": 0, "total_tokens": 20},
            {"requests": True},
            {"total_tokens": 121},
        )

        for changes in cases:
            with self.subTest(changes=changes):
                events = list(_successful_events(run))
                usage_index = next(
                    index
                    for index, event in enumerate(events)
                    if event.type == "model.usage"
                )
                usage = dict(events[usage_index].data)
                usage.update(changes)
                events[usage_index] = _event(
                    run,
                    events[usage_index].sequence,
                    "model.usage",
                    usage,
                )
                with self.assertRaises(OnlineSmokeError):
                    _build_summary(run, events)

    def test_event_run_and_sequence_must_match_durable_run(self) -> None:
        run = _completed_run()
        events = list(_successful_events(run))
        events[1] = StoredRunEvent(
            id="event-other-run",
            run_id="other-run",
            sequence=2,
            type="model.output.delta",
            data={"delta": "5", "segment": 1},
            created_at=_now(),
            step=1,
        )

        with self.assertRaisesRegex(OnlineSmokeError, "lifecycle evidence"):
            _build_summary(run, events)


class VerifyOnlineScriptTests(unittest.TestCase):
    def test_powershell_script_refuses_before_launching_python(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("powershell.exe")
        if powershell is None:
            self.skipTest("Windows PowerShell is unavailable")
        environment = {
            name: value
            for name in ("SystemRoot", "ComSpec", "PATH", "TEMP", "TMP")
            if (value := os.environ.get(name)) is not None
        }

        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(_REPO_ROOT / "scripts" / "verify-online.ps1"),
                "-Suite",
                "M8",
            ],
            cwd=_REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )

        self.assertEqual(64, completed.returncode)
        self.assertEqual("", completed.stdout)
        self.assertIn("authorization is missing", completed.stderr)


def _online_environment(
    *,
    include_low_budget: bool = True,
    **overrides: str,
) -> dict[str, str]:
    environment = {
        "AI_AGENT_RUNTIME": "agents_sdk",
        "AI_AGENT_MODEL_PROVIDER": "openai",
        "AI_AGENT_ONLINE_ENABLED": "true",
        "AI_AGENT_TRACE_INCLUDE_SENSITIVE": "false",
        "OPENAI_API_KEY": secrets.token_urlsafe(32),
        "OPENAI_MODEL": "online-smoke-model",
    }
    if include_low_budget:
        environment.update(
            {
                "AI_AGENT_MAX_STEPS": "3",
                "AI_AGENT_MAX_MODEL_CALLS": "2",
                "AI_AGENT_RUN_TIMEOUT_MS": "60000",
                "AI_AGENT_MODEL_TIMEOUT_MS": "30000",
                "AI_AGENT_MAX_INPUT_TOKENS": "4000",
                "AI_AGENT_MAX_OUTPUT_TOKENS": "512",
                "AI_AGENT_MAX_COST_USD": "0.05",
                "AI_AGENT_MAX_MODEL_RETRIES": "0",
            }
        )
    environment.update(overrides)
    return environment


def _prices() -> TokenPrices:
    return TokenPrices(
        input_per_million_usd=Decimal("1.25"),
        output_per_million_usd=Decimal("5"),
    )


def _now() -> datetime:
    return datetime(2026, 7, 17, tzinfo=UTC)


def _queued_run() -> RunRecord:
    return RunRecord.create(
        run_id="online-smoke-run",
        session_id="online-smoke-session",
        owner_id="online-smoke-owner",
        runtime="agents_sdk",
        model_provider="openai",
        model="online-smoke-model",
        input_text="safe test prompt",
        idempotency_key="online-smoke-idempotency-key",
        created_at=_now(),
    )


def _completed_run() -> RunRecord:
    return _queued_run().transition_to(
        RunStatus.RUNNING,
        at=_now() + timedelta(seconds=1),
    ).transition_to(
        RunStatus.COMPLETED,
        at=_now() + timedelta(seconds=2),
        answer="5",
    )


def _event(
    run: RunRecord,
    sequence: int,
    event_type: str,
    data: dict[str, object],
) -> StoredRunEvent:
    return StoredRunEvent(
        id=f"event-{sequence}",
        run_id=run.id,
        sequence=sequence,
        type=event_type,
        data=data,
        created_at=_now(),
        step=max(0, sequence - 1),
    )


def _successful_events(run: RunRecord) -> tuple[StoredRunEvent, ...]:
    return (
        _event(run, 1, "run.started", {}),
        _event(run, 2, "model.output.delta", {"delta": "5", "segment": 1}),
        _event(
            run,
            3,
            "tool.started",
            {"id": "call-1", "name": "add_numbers"},
        ),
        _event(
            run,
            4,
            "tool.completed",
            {"id": "call-1", "name": "add_numbers", "ok": True},
        ),
        _event(
            run,
            5,
            "model.usage",
            {
                "provider": "openai",
                "model": run.model,
                "requests": 2,
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
            },
        ),
        _event(run, 6, "run.completed", {}),
    )


def _resequence(events: list[StoredRunEvent]) -> list[StoredRunEvent]:
    run = _completed_run()
    return [
        _event(run, sequence, event.type, dict(event.data))
        for sequence, event in enumerate(events, start=1)
    ]


def _build_summary(
    run: RunRecord,
    events: list[StoredRunEvent],
) -> dict[str, object]:
    return build_online_summary(
        run,
        events,
        duration_ms=100,
        prices=_prices(),
        max_cost_usd=Decimal("0.05"),
    )


if __name__ == "__main__":
    unittest.main()
