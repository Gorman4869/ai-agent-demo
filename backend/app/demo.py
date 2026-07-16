from __future__ import annotations

import json
from dataclasses import asdict

from backend.app.agent import ManualAgentLoop
from backend.app.domain import ModelDecision, ToolCall
from backend.app.models import MockModel
from backend.app.tools.builtin import create_default_registry


def main() -> None:
    model = MockModel(
        [
            ModelDecision(
                tool_call=ToolCall(
                    id="call-1",
                    name="add_numbers",
                    arguments={"a": 12, "b": 30},
                )
            ),
            ModelDecision(final_answer="12 + 30 = 42"),
        ]
    )
    result = ManualAgentLoop(model, create_default_registry()).run("12 加 30 等于多少？")

    for event in result.events:
        print(json.dumps(asdict(event), ensure_ascii=False))


if __name__ == "__main__":
    main()
