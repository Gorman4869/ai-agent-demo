from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Timer

from backend.app.advanced.code_agent import (
    CheckAction,
    CommandSpec,
    ControlledCodeAgent,
    ReadAction,
)
from backend.app.advanced.process_runner import ProcessResourceLimits
from backend.app.advanced.harness import SafetyLimits
from backend.app.agent.cancellation import CancellationToken


class ControlledCodeAgentProcessTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = TemporaryDirectory()
        self.workspace = Path(self._temporary_directory.name)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_streams_and_bounds_stdout_stderr_flood_without_pipe_deadlock(
        self,
    ) -> None:
        chunk_size = 64 * 1024
        repetitions = 64
        agent = self._agent(
            CommandSpec(
                name="output-flood",
                argv=(
                    sys.executable,
                    "-c",
                    (
                        "import os; "
                        f"chunk=b'x'*{chunk_size}; "
                        f"[(os.write(1, chunk), os.write(2, chunk)) "
                        f"for _ in range({repetitions})]"
                    ),
                ),
                max_output_bytes=1_024,
            )
        )

        result = agent.run(
            (CheckAction("output-flood"),),
            context=agent.create_execution_context(principal_id="student-1"),
        )

        outcome = result.outcomes[0]
        self.assertTrue(result.ok)
        self.assertEqual(1_024, outcome.byte_count)
        self.assertEqual(chunk_size * repetitions * 2, outcome.observed_output_bytes)
        self.assertTrue(outcome.truncated)
        self.assertTrue(outcome.process_tree_cleaned)
        self.assertEqual("exited", outcome.termination_reason)
        self.assertEqual(outcome.observed_output_bytes, result.audit[0].observed_output_bytes)
        self.assertNotIn("x" * 100, repr(result.audit))

    def test_timeout_reason_wins_after_bounded_output_is_exhausted(self) -> None:
        agent = ControlledCodeAgent(
            self.workspace,
            command_specs=(
                CommandSpec(
                    name="infinite-output",
                    argv=(
                        sys.executable,
                        "-c",
                        "import os; exec(\"while True:\\n os.write(1, b'x'*4096)\")",
                    ),
                    timeout_seconds=0.2,
                    max_output_bytes=1_024,
                ),
            ),
            limits=SafetyLimits(max_output_bytes=64),
        )

        result = agent.run(
            (CheckAction("infinite-output"),),
            context=agent.create_execution_context(principal_id="student-1"),
        )

        outcome = result.outcomes[0]
        self.assertEqual("command_timeout", outcome.error_code)
        self.assertEqual(64, outcome.byte_count)
        self.assertTrue(outcome.truncated)
        self.assertTrue(outcome.process_tree_cleaned)

    def test_timeout_cleans_nested_process_tree(self) -> None:
        agent = self._agent(
            self._nested_process_command(
                name="nested-timeout",
                escaped_marker="timeout-escaped.txt",
                child_delay_seconds=1.2,
                timeout_seconds=0.7,
            )
        )

        result = agent.run(
            (CheckAction("nested-timeout"),),
            context=agent.create_execution_context(principal_id="student-1"),
        )
        time.sleep(0.7)

        outcome = result.outcomes[0]
        self.assertEqual("command_timeout", outcome.error_code)
        self.assertEqual("timeout", outcome.termination_reason)
        self.assertTrue(outcome.process_tree_cleaned)
        self.assertIn(outcome.process_scope, {"windows_job", "linux_process_group"})
        self.assertFalse((self.workspace / "timeout-escaped.txt").exists())

    def test_cancellation_cleans_nested_process_tree_and_is_audited(self) -> None:
        agent = self._agent(
            self._nested_process_command(
                name="nested-cancel",
                escaped_marker="cancel-escaped.txt",
                child_delay_seconds=1.2,
                timeout_seconds=5.0,
            )
        )
        cancellation = CancellationToken()
        timer = Timer(0.5, cancellation.cancel, args=("cancelled_by_user",))
        timer.start()
        self.addCleanup(timer.cancel)

        result = agent.run(
            (CheckAction("nested-cancel"),),
            context=agent.create_execution_context(principal_id="student-1"),
            cancellation=cancellation,
        )
        time.sleep(0.8)

        outcome = result.outcomes[0]
        audit = result.audit[0]
        self.assertEqual("cancelled", outcome.status)
        self.assertEqual("command_cancelled", outcome.error_code)
        self.assertEqual("cancelled", audit.termination_reason)
        self.assertTrue(audit.process_tree_cleaned)
        self.assertFalse((self.workspace / "cancel-escaped.txt").exists())

    def test_already_cancelled_run_does_not_start_command(self) -> None:
        cancellation = CancellationToken()
        cancellation.cancel("cancelled_by_user")
        agent = self._agent(
            CommandSpec(
                name="must-not-start",
                argv=(
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('started.txt').write_text('yes')",
                ),
            )
        )

        result = agent.run(
            (CheckAction("must-not-start"),),
            context=agent.create_execution_context(principal_id="student-1"),
            cancellation=cancellation,
        )

        self.assertEqual("run_cancelled", result.outcomes[0].error_code)
        self.assertEqual(0, result.actions_used)
        self.assertFalse((self.workspace / "started.txt").exists())

    def test_process_count_budget_terminates_the_tree(self) -> None:
        child = "import time; time.sleep(30)"
        parent = (
            "import subprocess, sys, time; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
            "time.sleep(30)"
        )
        agent = self._agent(
            CommandSpec(
                name="too-many-processes",
                argv=(sys.executable, "-c", parent),
                timeout_seconds=5.0,
                resources=ProcessResourceLimits(max_processes=1),
            )
        )

        result = agent.run(
            (CheckAction("too-many-processes"),),
            context=agent.create_execution_context(principal_id="student-1"),
        )

        outcome = result.outcomes[0]
        self.assertEqual("command_resource_exceeded", outcome.error_code)
        self.assertEqual("process_count", outcome.resource_limit)
        self.assertTrue(outcome.process_tree_cleaned)

    def test_memory_budget_terminates_the_tree(self) -> None:
        script = (
            "import time; blocks=[]; "
            "exec(\"while True:\\n blocks.append(bytearray(1024*1024))\\n time.sleep(0.01)\")"
        )
        agent = self._agent(
            CommandSpec(
                name="memory-budget",
                argv=(sys.executable, "-c", script),
                timeout_seconds=5.0,
                resources=ProcessResourceLimits(max_memory_bytes=64 * 1024 * 1024),
            )
        )

        result = agent.run(
            (CheckAction("memory-budget"),),
            context=agent.create_execution_context(principal_id="student-1"),
        )

        outcome = result.outcomes[0]
        self.assertEqual("command_resource_exceeded", outcome.error_code)
        self.assertEqual("memory", outcome.resource_limit)
        self.assertTrue(outcome.process_tree_cleaned)

    def test_cpu_budget_terminates_the_tree(self) -> None:
        agent = self._agent(
            CommandSpec(
                name="cpu-budget",
                argv=(sys.executable, "-c", "while True: pass"),
                timeout_seconds=5.0,
                resources=ProcessResourceLimits(max_cpu_seconds=0.15),
            )
        )

        started = time.monotonic()
        result = agent.run(
            (CheckAction("cpu-budget"),),
            context=agent.create_execution_context(principal_id="student-1"),
        )

        outcome = result.outcomes[0]
        self.assertEqual("command_resource_exceeded", outcome.error_code)
        self.assertEqual("cpu", outcome.resource_limit)
        self.assertTrue(outcome.process_tree_cleaned)
        self.assertLess(time.monotonic() - started, 3.0)

    @unittest.skipUnless(os.name == "nt", "Windows junction capability test")
    def test_rejects_windows_junction_escape(self) -> None:
        with TemporaryDirectory() as outside_directory:
            outside = Path(outside_directory)
            (outside / "secret.txt").write_text("outside", encoding="utf-8")
            junction = self.workspace / "outside-junction"
            command = (
                os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe"),
                "/d",
                "/c",
                "mklink",
                "/J",
                str(junction),
                str(outside),
            )
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                shell=False,
            )
            if completed.returncode != 0:
                self.skipTest("Windows junction creation is unavailable")
            try:
                agent = self._agent()
                result = agent.run(
                    (ReadAction("outside-junction/secret.txt"),),
                    context=agent.create_execution_context(principal_id="student-1"),
                )

                self.assertEqual(
                    "path_outside_workspace",
                    result.outcomes[0].error_code,
                )
            finally:
                os.rmdir(junction)

    def test_resource_limit_validation_fails_closed(self) -> None:
        for kwargs in (
            {"max_processes": 0},
            {"max_memory_bytes": 0},
            {"max_cpu_seconds": 0},
            {"max_cpu_seconds": float("inf")},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    ProcessResourceLimits(**kwargs)

    def _agent(self, *commands: CommandSpec) -> ControlledCodeAgent:
        return ControlledCodeAgent(self.workspace, command_specs=commands)

    @staticmethod
    def _nested_process_command(
        *,
        name: str,
        escaped_marker: str,
        child_delay_seconds: float,
        timeout_seconds: float,
    ) -> CommandSpec:
        child = (
            "import time; from pathlib import Path; "
            f"time.sleep({child_delay_seconds}); "
            f"Path({escaped_marker!r}).write_text('escaped', encoding='utf-8')"
        )
        parent = (
            "import subprocess, sys, time; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
            "time.sleep(30)"
        )
        return CommandSpec(
            name=name,
            argv=(sys.executable, "-c", parent),
            timeout_seconds=timeout_seconds,
            resources=ProcessResourceLimits(max_processes=4),
        )


if __name__ == "__main__":
    unittest.main()
