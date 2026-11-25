"""A real process for the decision crash tests: runs architecture-memory and dies at one point.

Usage: python -m tests.integration.decision_crash_child DATA_DIR VAULT POINT

POINT is where the process ends with `os._exit(9)` (no cleanup, no `finally`, like a kill), with
the vault writer's lock held:
- `before_consume`: the person granted the approval; nothing consumed it yet.
- `after_consume`: the approval is consumed and the step is `applying`; nothing written.
- `after_temp`: the hidden temporary file is written and synced; the note is not published.
- `after_link`: the note is published (hard link) and the temporary file is still there.
- `after_publish`: the note is published and the temporary file removed; the step is not
  recorded as completed.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from harness.memory import decisions
from harness.skills.engine import SkillEngine
from harness.storage.database import open_database
from tests.integration.test_architecture_memory import SOURCE, engine_for
from tests.skill_support import ApprovingTerminal

KILLED = 9
POINTS = ("before_consume", "after_consume", "after_temp", "after_link", "after_publish")


def _die(*args, **kwargs):
    os._exit(KILLED)


def main(data_dir: str, vault: str, point: str) -> int:
    if point not in POINTS:
        raise SystemExit(f"unknown point {point!r}")
    if point == "before_consume":
        SkillEngine._consume_and_apply = _die  # type: ignore[method-assign]
    elif point == "after_consume":
        decisions.write_decision = _die  # the effect module imported the name: patch both
        import harness.skills.decision_effect as effect_module

        effect_module.write_decision = _die
    elif point == "after_temp":
        decisions._publish = _die
    elif point == "after_link":
        original_publish = decisions._publish

        def publish_then_die(*args, **kwargs):
            original_publish(*args, **kwargs)
            os._exit(KILLED)

        decisions._publish = publish_then_die
    else:
        original = SkillEngine._complete

        def complete(self, state, step_key, row, output):
            if step_key == "save":
                os._exit(KILLED)
            return original(self, state, step_key, row, output)

        SkillEngine._complete = complete  # type: ignore[method-assign]
    conn = open_database(Path(data_dir))
    engine, sessions, _ = engine_for(conn, Path(data_dir), Path(vault),
                                     terminal=ApprovingTerminal())
    session = sessions.create_session("Demo", "demo-alpha")
    outcome = asyncio.run(engine.run("architecture-memory", str(session.session_id),
                                     {"source": SOURCE}))
    print(outcome.status, outcome.message)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
