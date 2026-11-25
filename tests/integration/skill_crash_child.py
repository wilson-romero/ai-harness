"""A real process for the crash tests: runs demo-echo with a test effect and dies at one point.

Usage: python -m tests.integration.skill_crash_child DATA_DIR SKILLS_ROOT EFFECT_DIR POINT

POINT is where the process ends with `os._exit(9)` (no cleanup, no `finally`, like a kill):
- `before_consume`: the person granted the approval; nothing consumed it yet.
- `between_consume_and_apply`: the approval is consumed; the effect has not started.
- `during_apply`: the effect wrote half of its content.
- `after_apply`: the effect finished; the step was not recorded as completed.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from harness.skills.engine import SkillEngine
from harness.storage.database import open_database
from tests.skill_support import ApprovingTerminal, WriteEffect, build

KILLED = 9


class CrashingEffect(WriteEffect):
    def __init__(self, folder: Path, point: str) -> None:
        super().__init__(folder)
        self.point = point

    def apply(self, context, *args) -> None:
        if self.point == "between_consume_and_apply":
            os._exit(KILLED)
        if self.point == "during_apply":
            content = args[0] if isinstance(args[0], str) else args[0].content
            half = content.encode("utf-8")[: len(content) // 2]
            (self.folder / "0.md").write_bytes(half)
            os._exit(KILLED)
        super().apply(context, *args)


def main(data_dir: str, root: str, folder: str, point: str) -> int:
    if point == "before_consume":
        SkillEngine._apply = lambda *args, **kwargs: os._exit(KILLED)  # type: ignore[method-assign]
    if point == "after_apply":
        original = SkillEngine._complete

        def complete(self, state, step_key, row, output):
            if step_key == "confirm":
                os._exit(KILLED)
            return original(self, state, step_key, row, output)

        SkillEngine._complete = complete  # type: ignore[method-assign]
    conn = open_database(Path(data_dir))
    effect = CrashingEffect(Path(folder), point)
    engine, sessions, _ = build(conn, Path(data_dir), root=Path(root), terminal=ApprovingTerminal(),
                                effects={"test.write": effect})
    session = sessions.create_session("Demo")
    outcome = asyncio.run(engine.run("demo-echo", str(session.session_id), {"text": "hola"}))
    print(outcome.status)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
