"""A process killed while writing a decision never leaves two notes, an unapproved note, an
overwrite or a temporary file the memory would read (decision-notes D6, D7; review demands).

Each test runs `architecture-memory` in a real child process that dies with `os._exit(9)` at one
point of the write; then, as after a restart, recovery runs and the run is resumed in this
process at a (fake) terminal that approves whatever it is shown.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys

import pytest

from harness.core.errors import InvalidInput
from harness.memory.decisions import DECISIONS_DIR, find_decision_notes
from harness.memory.paths import walk_vault
from harness.skills.engine import recover_runs
from tests.conftest import REPO_ROOT, fingerprint, subprocess_env
from tests.integration.decision_crash_child import KILLED
from tests.integration.test_architecture_memory import SOURCE, engine_for
from tests.skill_support import ApprovingTerminal


def _crash(data_dir, vault, point):
    result = subprocess.run(
        [sys.executable, "-m", "tests.integration.decision_crash_child", str(data_dir),
         str(vault), point],
        cwd=REPO_ROOT, env=subprocess_env(data_dir), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == KILLED, result.stdout + result.stderr


def _hidden(vault):
    return sorted(p.name for p in (vault / DECISIONS_DIR).iterdir() if p.name.startswith("."))


def _approvals(conn):
    return [r[0] for r in conn.execute("SELECT status FROM approvals ORDER BY created_at")]


def _restart(conn, data_dir, vault):
    recover_runs(conn, data_dir)  # what every `skill` command does first
    terminal = ApprovingTerminal()
    engine, _, _ = engine_for(conn, data_dir, vault, terminal=terminal)
    run_id = conn.execute("SELECT run_id FROM skill_runs").fetchone()[0]
    return engine, terminal, run_id


def _notes_of_the_run(conn, vault):
    ident = conn.execute(
        "SELECT effect_ref FROM skill_steps WHERE step_key = 'save' AND effect_ref IS NOT NULL "
        "ORDER BY attempt DESC").fetchone()[0]
    return ident, find_decision_notes(vault.resolve() / DECISIONS_DIR, ident)


def _check_final(conn, vault, before):
    """One note, approved, never an overwrite, no temporary file, visible to the memory."""
    after = fingerprint(vault)
    for key, value in before.items():
        assert key in after and (value[0] == "dir" or after[key] == value), key
    new = set(after) - set(before)
    assert len(new) == 1, new
    target = new.pop()
    assert target.startswith(f"{DECISIONS_DIR}/") and _hidden(vault) == []
    ident, notes = _notes_of_the_run(conn, vault)
    assert len(notes) == 1 and f"{DECISIONS_DIR}/{notes[0][0]}" == target
    completed_sha = conn.execute(
        "SELECT output_sha256 FROM skill_steps WHERE step_key = 'save' AND status = 'completed'"
    ).fetchone()[0]
    assert notes[0][1] == completed_sha == hashlib.sha256((vault / target).read_bytes()).hexdigest()
    assert os.lstat(vault / target).st_nlink == 1
    assert target in {f.relative for f in walk_vault(vault.resolve()).files}
    assert "consumed" in _approvals(conn)
    assert set(_approvals(conn)) == {"consumed"}  # no approval is left usable
    return target


def test_killed_before_the_approval_is_consumed(conn, data_dir, vault):
    before = fingerprint(vault)
    _crash(data_dir, vault, "before_consume")
    assert fingerprint(vault) == before
    engine, terminal, run_id = _restart(conn, data_dir, vault)
    assert _approvals(conn) == ["granted"]
    outcome = asyncio.run(engine.resume(run_id, {"source": SOURCE}))
    assert outcome.status == "completed", outcome.message
    assert terminal.questions == 0  # the granted approval is consumed once, no new one
    _check_final(conn, vault, before)
    assert _approvals(conn) == ["consumed"]


@pytest.mark.parametrize("point", ["after_consume", "after_temp"])
def test_killed_before_the_note_is_published_needs_a_new_approval(conn, data_dir, vault, point):
    before = fingerprint(vault)
    _crash(data_dir, vault, point)
    if point == "after_temp":
        # A leftover hidden temporary file, never read by the memory.
        assert len(_hidden(vault)) == 1
        assert all(not f.relative.split("/")[-1].startswith(".")
                   for f in walk_vault(vault.resolve()).files)
    engine, terminal, run_id = _restart(conn, data_dir, vault)
    status = engine.status(run_id)
    assert status["run"]["status"] == "uncertain"
    assert [s["status"] for s in status["steps"] if s["step_key"] == "save"] == ["uncertain"]
    outcome = asyncio.run(engine.resume(run_id, {"source": SOURCE}))
    assert outcome.status == "completed", outcome.message
    assert terminal.questions == 1  # a new approval, for the same bytes
    _check_final(conn, vault, before)
    assert _approvals(conn) == ["consumed", "consumed"]
    hashes = [r[0] for r in conn.execute("SELECT proposal_hash FROM approvals")]
    assert len(set(hashes)) == 1


@pytest.mark.parametrize("point", ["after_link", "after_publish"])
def test_killed_after_the_note_is_published_completes_without_writing_again(conn, data_dir,
                                                                           vault, point):
    before = fingerprint(vault)
    _crash(data_dir, vault, point)
    if point == "after_link":
        # Two hard links: the memory skips the note until the reconciliation removes the
        # temporary file.
        assert len(_hidden(vault)) == 1
        assert not any(f.relative.startswith(f"{DECISIONS_DIR}/2")
                       for f in walk_vault(vault.resolve()).files)
    engine, terminal, run_id = _restart(conn, data_dir, vault)
    assert engine.status(run_id)["run"]["status"] == "uncertain"
    written = {k: v for k, v in fingerprint(vault).items() if k not in before
               and not k.split("/")[-1].startswith(".")}
    outcome = asyncio.run(engine.resume(run_id, {"source": SOURCE}))
    assert outcome.status == "completed", outcome.message
    assert terminal.questions == 0  # reconciled as applied: nothing asked, nothing written
    target = _check_final(conn, vault, before)
    assert {target: fingerprint(vault)[target]} == written
    assert _approvals(conn) == ["consumed"]
    assert outcome.applied == (target,)


def test_another_note_with_the_same_identifier_is_a_conflict(conn, data_dir, vault):
    _crash(data_dir, vault, "after_temp")
    engine, terminal, run_id = _restart(conn, data_dir, vault)
    ident = conn.execute("SELECT effect_ref FROM skill_steps WHERE step_key = 'save'"
                         ).fetchone()[0]
    other = vault / DECISIONS_DIR / "escrita-a-mano.md"
    other.write_text(f"---\ntype: decision\ndecision_id: {ident}\ncreated: 2026-11-01\n"
                     "updated: 2026-11-01\n---\nOtra nota.\n", encoding="utf-8", newline="\n")
    before = {k: v for k, v in fingerprint(vault).items() if not k.split("/")[-1].startswith(".")}
    with pytest.raises(InvalidInput, match="conflict"):
        asyncio.run(engine.resume(run_id, {"source": SOURCE}))
    assert terminal.questions == 0
    after = {k: v for k, v in fingerprint(vault).items() if not k.split("/")[-1].startswith(".")}
    assert {k: v for k, v in after.items() if v[0] != "dir"} == {
        k: v for k, v in before.items() if v[0] != "dir"}
    assert _hidden(vault) == []  # its own temporary file is cleaned, nothing else changes
    steps = engine.status(run_id)["steps"]
    assert [s["status"] for s in steps if s["step_key"] == "save"] == ["uncertain"]
