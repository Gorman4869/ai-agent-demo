from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable, Sequence
from typing import TextIO

from backend.app.evals.load_fault import (
    LoadFaultConfig,
    LoadFaultReport,
    execute_local_http_load_probe,
    execute_offline_load_fault_probe,
)


_FAILURE_EXIT_CODE = 1
_CONFIGURATION_EXIT_CODE = 2

ProbeExecutor = Callable[[LoadFaultConfig], Awaitable[LoadFaultReport]]
HttpProbeExecutor = Callable[[str, LoadFaultConfig], Awaitable[LoadFaultReport]]


async def execute_probe(
    config: LoadFaultConfig,
    *,
    base_url: str | None = None,
    offline_executor: ProbeExecutor = execute_offline_load_fault_probe,
    http_executor: HttpProbeExecutor = execute_local_http_load_probe,
) -> dict[str, object]:
    offline = await offline_executor(config)
    reports = [offline]
    if base_url is not None:
        reports.append(await http_executor(base_url, config))
    return {
        "suite": "M13-T6",
        "passed": all(report.passed for report in reports),
        "reports": [report.to_record() for report in reports],
    }


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    executor: Callable[..., Awaitable[dict[str, object]]] = execute_probe,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    arguments = _create_parser().parse_args(argv)
    try:
        config = LoadFaultConfig(
            concurrent_runs=arguments.runs,
            concurrency=arguments.concurrency,
            runtime_delay_ms=arguments.runtime_delay_ms,
            slow_client_pause_ms=arguments.slow_client_pause_ms,
            retry_delay_ms=arguments.retry_delay_ms,
            operation_timeout_ms=arguments.operation_timeout_ms,
            sample_interval_ms=arguments.sample_interval_ms,
        )
        summary = asyncio.run(
            executor(config, base_url=arguments.base_url)
        )
    except ValueError as error:
        print(f"M13-T6 load/fault probe refused: {error}", file=stderr)
        return _CONFIGURATION_EXIT_CODE
    except Exception:
        print(
            "M13-T6 load/fault probe failed with an internal error",
            file=stderr,
        )
        return _FAILURE_EXIT_CODE

    print(json.dumps(summary, ensure_ascii=True, sort_keys=True), file=stdout)
    return 0 if summary.get("passed") is True else _FAILURE_EXIT_CODE


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run bounded M13-T6 offline scenarios and an optional localhost "
            "durable HTTP load probe."
        ),
    )
    parser.add_argument("--base-url")
    parser.add_argument("--runs", type=int, default=24)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--runtime-delay-ms", type=int, default=20)
    parser.add_argument("--slow-client-pause-ms", type=int, default=100)
    parser.add_argument("--retry-delay-ms", type=int, default=20)
    parser.add_argument("--operation-timeout-ms", type=int, default=10_000)
    parser.add_argument("--sample-interval-ms", type=int, default=10)
    return parser


def main() -> int:
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
