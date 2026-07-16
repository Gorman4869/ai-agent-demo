from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.app.advanced.code_agent import (
    CheckAction,
    CommandSpec,
    ControlledCodeAgent,
    ReadAction,
    WriteAction,
)


def run_demo() -> dict[str, object]:
    """Run a deterministic code-Agent exercise in a disposable workspace."""
    with TemporaryDirectory(prefix="controlled-code-agent-") as directory:
        workspace = Path(directory)
        (workspace / "task.txt").write_text(
            "Create a small, valid Python module.",
            encoding="utf-8",
        )
        (workspace / "generated").mkdir()
        syntax_check = CommandSpec(
            name="python-syntax",
            argv=(
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; "
                    "source=Path('generated/answer.py').read_text(encoding='utf-8'); "
                    "compile(source, 'generated/answer.py', 'exec'); "
                    "print('syntax-ok')"
                ),
            ),
            timeout_seconds=3.0,
            max_output_bytes=1_024,
        )
        agent = ControlledCodeAgent(
            workspace,
            command_specs=(syntax_check,),
        )
        context = agent.create_execution_context(
            principal_id="demo-user",
            approved_write_paths=("generated/answer.py",),
        )
        result = agent.run(
            (
                ReadAction("task.txt"),
                WriteAction(
                    "generated/answer.py",
                    "def answer() -> int:\n    return 42\n",
                ),
                CheckAction("python-syntax"),
            ),
            context=context,
        )
        return {
            "ok": result.ok,
            "actions_used": result.actions_used,
            "written_bytes": result.written_bytes,
            "read_bytes": result.read_bytes,
            "output_bytes": result.output_bytes,
            "audit": [asdict(entry) for entry in result.audit],
        }


def main() -> None:
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
