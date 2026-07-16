from __future__ import annotations

import sys
import unittest
from os import environ
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from backend.app.advanced.code_agent import (
    CheckAction,
    CodeAction,
    CommandSpec,
    ControlledCodeAgent,
    ReadAction,
    WriteAction,
)
from backend.app.advanced.harness import SafetyLimits


class ControlledCodeAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = TemporaryDirectory()
        self.workspace = Path(self._temporary_directory.name)
        (self.workspace / "generated").mkdir()

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_runs_structured_actions_and_keeps_content_out_of_audit(self) -> None:
        secret = "private source body"
        (self.workspace / "task.txt").write_text(secret, encoding="utf-8")
        agent = self._agent(
            CommandSpec(
                name="syntax",
                argv=(
                    sys.executable,
                    "-c",
                    (
                        "from pathlib import Path; "
                        "source=Path('generated/result.py').read_text(encoding='utf-8'); "
                        "compile(source, 'result.py', 'exec'); print('ok')"
                    ),
                ),
            )
        )
        context = agent.create_execution_context(
            principal_id="student-1",
            approved_write_paths=("generated/result.py",),
        )

        result = agent.run(
            (
                ReadAction("task.txt"),
                WriteAction("generated/result.py", "VALUE = 42\n"),
                CheckAction("syntax"),
            ),
            context=context,
        )

        self.assertTrue(result.ok)
        self.assertEqual(secret, result.outcomes[0].content)
        self.assertEqual("VALUE = 42\n", (self.workspace / "generated/result.py").read_text())
        self.assertEqual(["ok"], (result.outcomes[2].stdout or "").splitlines())
        self.assertEqual(len(secret.encode("utf-8")), result.read_bytes)
        self.assertGreater(result.output_bytes, result.read_bytes)
        self.assertNotIn(secret, repr(result.audit))
        self.assertNotIn("VALUE = 42", repr(result.audit))
        self.assertTrue(all(len(entry.digest or "") == 64 for entry in result.audit))

    def test_rejects_parent_traversal_and_symbolic_link_escape(self) -> None:
        outside = self.workspace.parent / f"{self.workspace.name}-outside"
        outside.mkdir()
        self.addCleanup(lambda: outside.rmdir())
        (outside / "secret.txt").write_text("outside", encoding="utf-8")
        self.addCleanup(lambda: (outside / "secret.txt").unlink(missing_ok=True))
        agent = self._agent()
        context = agent.create_execution_context(principal_id="student-1")

        traversal = agent.run(
            (ReadAction("../secret.txt"),),
            context=context,
        )

        self.assertEqual("path_outside_workspace", traversal.outcomes[0].error_code)

        link = self.workspace / "outside-link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symbolic links are unavailable: {type(error).__name__}")
        escaped = agent.run(
            (ReadAction("outside-link/secret.txt"),),
            context=context,
        )
        self.assertEqual("path_outside_workspace", escaped.outcomes[0].error_code)

    def test_requires_exact_server_side_write_approval(self) -> None:
        agent = self._agent()
        context = agent.create_execution_context(
            principal_id="student-1",
            approved_write_paths=("generated/approved.txt",),
        )

        result = agent.run(
            (WriteAction("generated/not-approved.txt", "blocked"),),
            context=context,
        )

        self.assertEqual("write_approval_required", result.outcomes[0].error_code)
        self.assertFalse((self.workspace / "generated/not-approved.txt").exists())

    def test_rejects_unlisted_commands_and_unknown_action_types(self) -> None:
        agent = self._agent()
        context = agent.create_execution_context(principal_id="student-1")

        command_result = agent.run(
            (CheckAction("arbitrary-shell"),),
            context=context,
        )
        unknown_result = agent.run(
            (cast(CodeAction, object()),),
            context=context,
        )

        self.assertEqual("command_not_allowed", command_result.outcomes[0].error_code)
        self.assertEqual("action_not_allowed", unknown_result.outcomes[0].error_code)

    def test_enforces_action_and_read_write_byte_budgets_before_effects(self) -> None:
        (self.workspace / "large.txt").write_text("1234", encoding="utf-8")
        action_agent = ControlledCodeAgent(
            self.workspace,
            command_specs=(
                CommandSpec(
                    name="ok",
                    argv=(sys.executable, "-c", "print('ok')"),
                ),
            ),
            limits=SafetyLimits(max_actions=1),
        )
        context = action_agent.create_execution_context(principal_id="student-1")
        action_result = action_agent.run(
            (ReadAction("large.txt"), CheckAction("ok")),
            context=context,
        )
        self.assertEqual("action_budget_exceeded", action_result.outcomes[1].error_code)

        read_agent = ControlledCodeAgent(
            self.workspace,
            limits=SafetyLimits(max_output_bytes=3),
        )
        read_result = read_agent.run(
            (ReadAction("large.txt"),),
            context=read_agent.create_execution_context(principal_id="student-1"),
        )
        self.assertEqual("output_budget_exceeded", read_result.outcomes[0].error_code)

        write_agent = ControlledCodeAgent(
            self.workspace,
            limits=SafetyLimits(max_input_bytes=3),
        )
        write_context = write_agent.create_execution_context(
            principal_id="student-1",
            approved_write_paths=("generated/large.txt",),
        )
        write_result = write_agent.run(
            (WriteAction("generated/large.txt", "1234"),),
            context=write_context,
        )
        self.assertEqual("input_budget_exceeded", write_result.outcomes[0].error_code)
        self.assertFalse((self.workspace / "generated/large.txt").exists())

    def test_times_out_checks_and_truncates_allowed_command_output(self) -> None:
        agent = self._agent(
            CommandSpec(
                name="slow",
                argv=(sys.executable, "-c", "import time; time.sleep(1)"),
                timeout_seconds=0.05,
            ),
            CommandSpec(
                name="verbose",
                argv=(sys.executable, "-c", "print('x' * 100)"),
                max_output_bytes=8,
            ),
        )
        context = agent.create_execution_context(principal_id="student-1")

        timeout_result = agent.run((CheckAction("slow"),), context=context)
        output_result = agent.run((CheckAction("verbose"),), context=context)

        self.assertEqual("command_timeout", timeout_result.outcomes[0].error_code)
        self.assertLessEqual(output_result.outcomes[0].byte_count, 8)
        self.assertTrue(output_result.outcomes[0].truncated)

        budget_agent = ControlledCodeAgent(
            self.workspace,
            command_specs=(
                CommandSpec(
                    name="too-much-output",
                    argv=(sys.executable, "-c", "print('12345678', end='')"),
                    max_output_bytes=8,
                ),
            ),
            limits=SafetyLimits(max_output_bytes=3),
        )
        budget_result = budget_agent.run(
            (CheckAction("too-much-output"),),
            context=budget_agent.create_execution_context(principal_id="student-1"),
        )
        self.assertEqual("output_budget_exceeded", budget_result.outcomes[0].error_code)

    def test_check_uses_only_server_owned_environment(self) -> None:
        secret_name = "CONTROLLED_CODE_AGENT_TEST_SECRET"
        previous_value = environ.get(secret_name)
        environ[secret_name] = "must-not-leak"
        self.addCleanup(self._restore_environment, secret_name, previous_value)
        agent = self._agent(
            CommandSpec(
                name="environment",
                argv=(
                    sys.executable,
                    "-c",
                    (
                        "import os; "
                        f"print(os.environ.get('{secret_name}', 'missing'))"
                    ),
                ),
            )
        )

        result = agent.run(
            (CheckAction("environment"),),
            context=agent.create_execution_context(principal_id="student-1"),
        )

        self.assertEqual(["missing"], (result.outcomes[0].stdout or "").splitlines())

    def _agent(self, *commands: CommandSpec) -> ControlledCodeAgent:
        return ControlledCodeAgent(self.workspace, command_specs=commands)

    @staticmethod
    def _restore_environment(name: str, previous_value: str | None) -> None:
        if previous_value is None:
            environ.pop(name, None)
        else:
            environ[name] = previous_value


if __name__ == "__main__":
    unittest.main()
