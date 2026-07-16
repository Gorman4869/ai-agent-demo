from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ResearchTask:
    topic: str
    max_sources: int


def parse_task(payload: str) -> ResearchTask:
    data: dict[str, Any] = json.loads(payload)
    topic = data.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic must be a non-empty string")
    max_sources = data.get("max_sources", 3)
    if not isinstance(max_sources, int) or isinstance(max_sources, bool):
        raise ValueError("max_sources must be an integer")
    return ResearchTask(topic=topic, max_sources=max_sources)


async def execute(task: ResearchTask) -> dict[str, Any]:
    await asyncio.sleep(0)
    return {"status": "completed", "task": asdict(task)}


async def main() -> None:
    task = parse_task('{"topic":"Agent Loop","max_sources":2}')
    print(json.dumps(await execute(task), ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
