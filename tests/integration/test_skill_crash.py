"""A process killed around an effect never re-applies it (review 8.1; skill-engine D10, D13).

Each test runs demo-echo with a test effect in a real child process that dies with
`os._exit(9)` at one point; then, as after a restart, recovery runs and the run is resumed in this
process with an effect that writes to the same folder.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from harness.core.errors import InvalidInput
from harness.skills.engine import recover_runs
from tests.conftest import REPO_ROOT, subprocess_env
from tests.integration.skill_crash_child import KILLED
from tests.skill_support import (
    GOOD_ECHO,
    ApprovingTerminal,
    FakeTerminal,
    WriteEffect,
    build,
    copy_skills,
    with_effect,
)


def _crash(tmp_path, data_dir, point):
    root = copy_skills(tmp_path)
    with_effect(root, "demo-echo", "test.write")
    folder = tmp_path / "efecto"
    result = subprocess.run(
        [sys.executable, "-m", "tests.integration.skill_crash_child", str(data_dir), str(root),
         str(folder), point],
        cwd=REPO_ROOT, env=subprocess_env(data_dir), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == KILLED, result.stdout + result.stderr
    return root, folder


def _restart(conn, data_dir, root, folder, terminal):
    recover_runs(conn, data_dir)  # what every `skill` command does first
    engine, _, _ = build(conn, data_dir, root=root, terminal=terminal,
                         effects={"test.write": WriteEffect(folder)})
    run_id = conn.execute("SELECT run_id FROM skill_runs").fetchone()[0]
    return engine, run_id


def _files(folder):
    return [p.read_bytes().decode("utf-8") for p in sorted(folder.iterdir())]


def _confirm(conn):
    return [tuple(r) for r in conn.execute(
        "SELECT attempt, status, error_code FROM skill_steps WHERE step_key = 'confirm' "
        "ORDER BY attempt")]


def _approvals(conn):
    return [r[0] for r in conn.execute("SELECT status FROM approvals ORDER BY created_at")]


def _run_status(conn):
    return conn.execute("SELECT status FROM skill_runs").fetchone()[0]


def test_killed_before_the_approval_is_consumed(conn, data_dir, tmp_path):
    root, folder = _crash(tmp_path, data_dir, "before_consume")
    engine, run_id = _restart(conn, data_dir, root, folder, FakeTerminal(interactive=False))
    assert _confirm(conn) == [(1, "awaiting_approval", None)]
    assert _approvals(conn) == ["granted"] and _files(folder) == []
    outcome = asyncio.run(engine.resume(run_id, {"text": "hola"}))
    assert outcome.status == "completed"
    assert _files(folder) == [GOOD_ECHO] and _approvals(conn) == ["consumed"]


def test_killed_between_consume_and_apply_needs_a_new_approval(conn, data_dir, tmp_path):
    root, folder = _crash(tmp_path, data_dir, "between_consume_and_apply")
    engine, run_id = _restart(conn, data_dir, root, folder, FakeTerminal(interactive=False))
    assert _confirm(conn) == [(1, "uncertain", "interrupted")]
    assert _run_status(conn) == "uncertain"
    assert _approvals(conn) == ["consumed"] and _files(folder) == []
    waiting = asyncio.run(engine.resume(run_id, {"text": "hola"}))
    assert waiting.status == "awaiting_approval"  # nothing was applied: a person approves again
    assert _approvals(conn) == ["consumed", "pending"] and _files(folder) == []
    assert _confirm(conn) == [(1, "uncertain", "interrupted"), (2, "awaiting_approval", None)]
    engine, _ = _restart(conn, data_dir, root, folder, ApprovingTerminal())
    assert asyncio.run(engine.resume(run_id, {"text": "hola"})).status == "completed"
    assert _files(folder) == [GOOD_ECHO]


def test_killed_during_the_effect_needs_a_person(conn, data_dir, tmp_path):
    root, folder = _crash(tmp_path, data_dir, "during_apply")
    terminal = ApprovingTerminal()
    engine, run_id = _restart(conn, data_dir, root, folder, terminal)
    assert _confirm(conn) == [(1, "uncertain", "interrupted")]
    partial = _files(folder)
    assert len(partial) == 1 and partial[0] != GOOD_ECHO
    with pytest.raises(InvalidInput, match="conflict"):
        asyncio.run(engine.resume(run_id, {"text": "hola"}))
    with pytest.raises(InvalidInput, match="never retried"):
        asyncio.run(engine.resume(run_id, {"text": "hola"}, "confirm"))
    assert _files(folder) == partial and terminal.questions == 0
    assert _confirm(conn) == [(1, "uncertain", "interrupted")]
    assert _run_status(conn) == "uncertain" and _approvals(conn) == ["consumed"]


def test_killed_after_the_effect_is_not_applied_again(conn, data_dir, tmp_path):
    root, folder = _crash(tmp_path, data_dir, "after_apply")
    terminal = ApprovingTerminal()
    engine, run_id = _restart(conn, data_dir, root, folder, terminal)
    assert _confirm(conn) == [(1, "uncertain", "interrupted")]
    assert _files(folder) == [GOOD_ECHO]
    outcome = asyncio.run(engine.resume(run_id, {"text": "hola"}))
    assert outcome.status == "completed"
    assert _files(folder) == [GOOD_ECHO] and terminal.questions == 0
    assert _approvals(conn) == ["consumed"]
    assert _confirm(conn) == [(1, "completed", None)]
    reconciled = [r[0] for r in conn.execute(
        "SELECT outcome FROM audit_events WHERE event_type = 'skill.step.reconciled'")]
    assert reconciled == ["applied"]
