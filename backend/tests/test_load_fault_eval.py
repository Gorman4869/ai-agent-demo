from __future__ import annotations

import asyncio
import io
import unittest

from backend.app.evals.load_fault import (
    LoadFaultConfig,
    ScenarioOperationError,
    execute_offline_load_fault_probe,
    measure_async_scenario,
    normalize_local_base_url,
    read_process_rss_bytes,
)
from backend.app.load_fault_probe import run_cli


class LoadFaultMeasurementTest(unittest.IsolatedAsyncioTestCase):
    async def test_measures_concurrency_latency_errors_and_resources(self) -> None:
        active = 0
        peak = 0

        async def operation(index: int) -> None:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.005)
                if index == 3:
                    raise ScenarioOperationError("fixture_unavailable")
            finally:
                active -= 1

        rss_values = iter((100, 110, 120, 130, 125))

        def read_rss() -> int:
            return next(rss_values, 125)

        report = await measure_async_scenario(
            "bounded_fixture",
            attempted=4,
            concurrency=2,
            operation=operation,
            sample_interval_ms=2,
            rss_reader=read_rss,
        )

        self.assertEqual(2, peak)
        self.assertEqual(2, report.peak_in_flight)
        self.assertEqual(3, report.succeeded)
        self.assertEqual(1, report.failed)
        self.assertEqual(("fixture_unavailable", 1), report.error_counts[0])
        self.assertEqual(0.25, report.error_rate)
        self.assertGreater(report.throughput_per_second, 0)
        self.assertEqual(130, report.rss_peak_bytes)
        self.assertGreaterEqual(report.latency.p95_ms, report.latency.p50_ms)

    async def test_unknown_exception_is_content_free(self) -> None:
        secret = "private-model-payload"

        async def operation(_: int) -> None:
            raise RuntimeError(secret)

        report = await measure_async_scenario(
            "safe_failure",
            attempted=1,
            concurrency=1,
            operation=operation,
            rss_reader=lambda: 10,
        )

        self.assertEqual((("scenario_internal_error", 1),), report.error_counts)
        self.assertNotIn(secret, repr(report))
        self.assertNotIn(secret, str(report.to_record()))

    async def test_operation_timeout_is_bounded_and_stable(self) -> None:
        async def operation(_: int) -> None:
            await asyncio.sleep(1)

        report = await measure_async_scenario(
            "bounded_timeout",
            attempted=1,
            concurrency=1,
            operation=operation,
            operation_timeout_ms=100,
            rss_reader=lambda: 10,
        )

        self.assertEqual(1, report.failed)
        self.assertEqual((("scenario_timeout", 1),), report.error_counts)


class LoadFaultProbeTest(unittest.IsolatedAsyncioTestCase):
    async def test_offline_probe_runs_real_bounded_paths(self) -> None:
        report = await execute_offline_load_fault_probe(
            LoadFaultConfig(
                concurrent_runs=6,
                concurrency=3,
                runtime_delay_ms=5,
                slow_client_pause_ms=10,
                retry_delay_ms=1,
                sample_interval_ms=2,
            )
        )

        self.assertTrue(report.passed)
        self.assertEqual(
            ("concurrent_runs", "slow_sse_client", "model_rate_limit"),
            tuple(scenario.name for scenario in report.scenarios),
        )
        concurrent, slow_client, rate_limit = report.scenarios
        self.assertEqual(3, concurrent.peak_in_flight)
        self.assertGreater(read_process_rss_bytes(), 0)
        self.assertEqual(
            10,
            dict(slow_client.measurements)["client_pause_ms"],
        )
        self.assertEqual(2, dict(rate_limit.measurements)["model_calls"])
        self.assertEqual(1, dict(rate_limit.measurements)["retry_events"])

    async def test_configuration_rejects_unbounded_work(self) -> None:
        with self.assertRaisesRegex(ValueError, "concurrent runs"):
            LoadFaultConfig(concurrent_runs=101)
        with self.assertRaisesRegex(ValueError, "concurrency"):
            LoadFaultConfig(concurrent_runs=4, concurrency=5)


class LoadFaultCliTest(unittest.TestCase):
    def test_local_base_url_rejects_remote_credentials_and_paths(self) -> None:
        self.assertEqual(
            "http://127.0.0.1:15173",
            normalize_local_base_url("http://127.0.0.1:15173/"),
        )
        for value in (
            "https://127.0.0.1:15173",
            "http://example.com:15173",
            "http://user:secret@127.0.0.1:15173",
            "http://127.0.0.1:15173/private",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "localhost"):
                    normalize_local_base_url(value)

    def test_cli_refuses_invalid_bounds_without_running_probe(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        exit_code = run_cli(
            ["--runs", "2", "--concurrency", "3"],
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(2, exit_code)
        self.assertEqual("", stdout.getvalue())
        self.assertIn("concurrency", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
