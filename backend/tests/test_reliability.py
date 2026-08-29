from __future__ import annotations

import unittest
from collections.abc import Callable
from typing import Any

from backend.app.agent import CancellationToken
from backend.app.reliability import (
    ExponentialBackoff,
    RetryOperation,
    RetrySafety,
    decide_retry,
    failure_spec,
    stable_run_failure,
)
from backend.app.tools import (
    InMemoryApprovalStore,
    ToolDefinition,
    ToolExecutionContext,
    ToolHandlerError,
    ToolRegistry,
)


class ReliabilityPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.backoff = ExponentialBackoff(
            initial_delay_ms=100,
            max_delay_ms=400,
        )

    def test_failure_catalog_separates_transient_and_permanent_provider_errors(
        self,
    ) -> None:
        rate_limited = stable_run_failure("provider_rate_limited")
        auth_failed = stable_run_failure("provider_auth_failed")

        self.assertTrue(rate_limited.retryable)
        self.assertFalse(auth_failed.retryable)
        self.assertEqual("provider", rate_limited.category)
        self.assertEqual("provider", auth_failed.category)

    def test_exponential_backoff_is_bounded(self) -> None:
        self.assertEqual(
            [100, 200, 400, 400],
            [self.backoff.delay_ms(number) for number in range(1, 5)],
        )

    def test_retry_stops_when_attempt_or_time_budget_is_exhausted(self) -> None:
        failure = stable_run_failure("provider_rate_limited")
        safety = RetrySafety(
            operation=RetryOperation.MODEL,
            idempotent=True,
            replay_safe=True,
        )

        attempts_exhausted = decide_retry(
            failure,
            safety=safety,
            retry_number=2,
            max_retries=1,
            backoff=self.backoff,
        )
        time_exhausted = decide_retry(
            failure,
            safety=safety,
            retry_number=1,
            max_retries=2,
            backoff=self.backoff,
            remaining_budget_ms=100,
        )

        self.assertEqual("retry_budget_exhausted", attempts_exhausted.reason)
        self.assertEqual("time_budget_exhausted", time_exhausted.reason)
        self.assertFalse(attempts_exhausted.retry)
        self.assertFalse(time_exhausted.retry)

    def test_side_effect_requires_a_persistent_idempotency_key(self) -> None:
        decision = decide_retry(
            stable_run_failure("tool_timeout"),
            safety=RetrySafety(
                operation=RetryOperation.TOOL,
                idempotent=True,
                replay_safe=True,
                side_effecting=True,
                persistent_idempotency_key=False,
                result_unknown=True,
            ),
            retry_number=1,
            max_retries=1,
            backoff=self.backoff,
        )

        self.assertFalse(decision.retry)
        self.assertEqual("persistent_idempotency_key_required", decision.reason)

    def test_mcp_disconnect_and_store_failure_remain_fail_closed_by_safety(
        self,
    ) -> None:
        mcp_disconnect = stable_run_failure("mcp_disconnected")
        store_failure = stable_run_failure("store_unavailable")

        mcp_decision = decide_retry(
            mcp_disconnect,
            safety=RetrySafety(
                operation=RetryOperation.MCP,
                idempotent=True,
                replay_safe=True,
            ),
            retry_number=1,
            max_retries=1,
            backoff=self.backoff,
        )
        store_decision = decide_retry(
            store_failure,
            safety=RetrySafety(
                operation=RetryOperation.STORE,
                idempotent=True,
                replay_safe=False,
                result_unknown=True,
            ),
            retry_number=1,
            max_retries=1,
            backoff=self.backoff,
        )

        self.assertTrue(mcp_decision.retry)
        self.assertFalse(store_decision.retry)
        self.assertEqual("result_unknown", store_decision.reason)

    def test_unknown_failure_code_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "not registered"):
            failure_spec("unreviewed_remote_error")

    def test_cancellation_token_reports_remaining_deadline_budget(self) -> None:
        current_time = 10.0

        def clock() -> float:
            return current_time

        token = CancellationToken(timeout_ms=250, clock=clock)
        self.assertEqual(250, token.remaining_ms)

        current_time = 10.125
        self.assertEqual(125, token.remaining_ms)

        current_time = 10.25
        self.assertEqual(0, token.remaining_ms)
        self.assertEqual("deadline_exceeded", token.reason)

        with self.assertRaisesRegex(ValueError, "non-negative"):
            token.wait_for_cancellation(float("inf"))


class ToolRetryBoundaryTest(unittest.TestCase):
    def test_read_only_tool_retries_one_transient_io_failure(self) -> None:
        calls = 0

        def flaky_handler(_arguments: dict[str, Any]) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("transient local fixture")
            return "recovered"

        result = _registry(flaky_handler).execute_with_retry(
            "lookup",
            {},
            max_retries=2,
            backoff=ExponentialBackoff(0, 0),
        )

        self.assertTrue(result.ok)
        self.assertEqual("recovered", result.value)
        self.assertEqual(2, calls)
        self.assertEqual(2, result.attempts)
        self.assertEqual((0,), result.retry_delays_ms)
        self.assertEqual(("tool_io_error",), result.retry_error_codes)

    def test_mcp_adapter_failure_uses_stable_code_and_retries_read_only_call(
        self,
    ) -> None:
        calls = 0

        def disconnected(_arguments: dict[str, Any]) -> None:
            nonlocal calls
            calls += 1
            raise ToolHandlerError(
                "mcp_disconnected",
                result_unknown=True,
            )

        result = _registry(disconnected).execute_with_retry(
            "lookup",
            {},
            max_retries=1,
            backoff=ExponentialBackoff(0, 0),
        )

        self.assertFalse(result.ok)
        self.assertEqual("mcp_disconnected", result.error_code)
        self.assertEqual(2, calls)
        self.assertEqual(2, result.attempts)

    def test_side_effect_tool_is_never_automatically_retried(self) -> None:
        calls = 0

        def failing_handler(_arguments: dict[str, Any]) -> None:
            nonlocal calls
            calls += 1
            raise OSError("result may be unknown")

        registry = _registry(failing_handler, has_side_effects=True)
        context, call_id = _approved_context("lookup")

        result = registry.execute_with_retry(
            "lookup",
            {},
            context=context,
            call_id=call_id,
            max_retries=3,
            backoff=ExponentialBackoff(0, 0),
        )

        self.assertFalse(result.ok)
        self.assertEqual("tool_io_error", result.error_code)
        self.assertTrue(result.result_unknown)
        self.assertEqual(1, calls)
        self.assertEqual(1, result.attempts)

    def test_cancellation_during_backoff_prevents_the_next_attempt(self) -> None:
        token = CancellationToken()
        calls = 0

        def cancelling_handler(_arguments: dict[str, Any]) -> None:
            nonlocal calls
            calls += 1
            token.cancel("cancelled_during_backoff")
            raise OSError("transient local fixture")

        result = _registry(cancelling_handler).execute_with_retry(
            "lookup",
            {},
            max_retries=2,
            backoff=ExponentialBackoff(100, 100),
            cancellation=token,
        )

        self.assertFalse(result.ok)
        self.assertEqual("run_cancelled", result.error_code)
        self.assertEqual(1, calls)
        self.assertEqual(1, result.attempts)


def _registry(
    handler: Callable[[dict[str, Any]], Any],
    *,
    has_side_effects: bool = False,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="lookup",
            description="Deterministic reliability fixture.",
            input_schema={"type": "object", "properties": {}},
            handler=handler,
            has_side_effects=has_side_effects,
        )
    )
    return registry


def _approved_context(tool_name: str) -> tuple[ToolExecutionContext, str]:
    store = InMemoryApprovalStore()
    call_id = "approved-side-effect-call"
    context = ToolExecutionContext(
        principal_id="reliability-test-user",
        run_id="reliability-test-run",
        approval_store=store,
    )
    store.grant(
        principal_id=context.principal_id,
        run_id=context.run_id,
        tool_call_id=call_id,
        tool_name=tool_name,
        arguments={},
    )
    return context, call_id


if __name__ == "__main__":
    unittest.main()
