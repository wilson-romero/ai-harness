"""Against the REAL Copilot Web (task 5.4). Run by hand, never in CI:

    uv run pytest -m copilot -p no:cacheprovider

It reads `HARNESS_COPILOT_URL` and `HARNESS_DATA_DIR` (for its `copilot/ui.json` and the
dedicated profile, or `HARNESS_EDGE_PROFILE`) from the environment the command starts with.
Without them every test is skipped with the reason. Edge opens with a window.

Every prompt is fixed and synthetic. Sends: 3 (three sessions) + 1 (a new process continues the
first) + 1 (uncertain with a short deadline) = 5. Sessions live in a temporary data directory,
not in your harness database. Nothing here prints or stores an answer, a conversation
identifier or a URL: assertions compare states, exit codes, lengths and hashes.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness.providers.copilot_ui import measurement_path
from harness.storage.database import DATABASE_NAME
from tests.conftest import REPO_ROOT, query

# Read at import, before the suite's isolation fixture clears these variables for each test.
REAL_URL = os.environ.get("HARNESS_COPILOT_URL") or ""
REAL_DATA = Path(os.environ["HARNESS_DATA_DIR"]) if os.environ.get("HARNESS_DATA_DIR") else None
REAL_PROFILE = os.environ.get("HARNESS_EDGE_PROFILE") or (
    str(REAL_DATA / "edge-profile") if REAL_DATA else ""
)
REAL_UI = measurement_path(REAL_DATA) if REAL_DATA else None

pytestmark = [
    pytest.mark.copilot,
    pytest.mark.skipif(not REAL_URL, reason="HARNESS_COPILOT_URL is not set: no real Copilot"),
    pytest.mark.skipif(
        REAL_UI is None or not REAL_UI.is_file(),
        reason="no ui.json in HARNESS_DATA_DIR/copilot: run the probe first",
    ),
]

QUESTIONS = (
    "Responde solo con la palabra ALFA.",
    "Responde solo con la palabra BETA.",
    "Responde solo con la palabra GAMMA.",
)
FOLLOW_UP = "Responde solo con la palabra DELTA."
LONG_ANSWER = "Escribe los numeros del 1 al 300, uno por linea, sin nada mas."


def digest(value: str | None) -> str:
    return hashlib.sha256((value or "").encode()).hexdigest()[:12]


@pytest.fixture(scope="module")
def work(tmp_path_factory) -> Path:
    data = tmp_path_factory.mktemp("copilot-real") / "data"
    assert REAL_UI is not None
    measurement_path(data).parent.mkdir(parents=True)
    shutil.copy(REAL_UI, measurement_path(data))
    return data


def harness(data: Path, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)  # this process's environment, adjusted: a visible Edge
    env.pop("HARNESS_TEST_HEADLESS", None)
    env |= {
        "HARNESS_DATA_DIR": str(data),
        "HARNESS_PROVIDER": "copilot_web",
        "HARNESS_COPILOT_URL": REAL_URL,
        "HARNESS_EDGE_PROFILE": REAL_PROFILE,
        **extra,
    }
    return subprocess.run(
        [sys.executable, "main.py", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def state(data: Path, session_id: str) -> tuple[str, str | None]:
    status, ref = query(data, "SELECT status, remote_ref FROM sessions WHERE session_id = ?", (session_id,))[0]
    return status, ref


def stderr_kind(result: subprocess.CompletedProcess[str]) -> str:
    """The first word after `ended as`, or the exit code: never the whole message."""
    match = re.search(r"ended as (\w+)", result.stderr)
    return match.group(1) if match else f"exit {result.returncode}"


def test_three_sessions_three_conversations_then_a_new_process_continues(work):
    sessions = []
    for n, question in enumerate(QUESTIONS):
        created = harness(work, "session", "create", f"real-{n}")
        assert created.returncode == 0
        session_id = created.stdout.strip()
        asked = harness(work, "ask", session_id, question)
        assert asked.returncode == 0, stderr_kind(asked)
        assert len(asked.stdout.strip()) > 0
        sessions.append(session_id)
    refs = [state(work, s)[1] for s in sessions]
    assert all(refs), "a session has no remote reference"
    assert len({digest(r) for r in refs}) == 3, "two sessions share a conversation"

    again = harness(work, "ask", sessions[0], FOLLOW_UP)  # a new process
    assert again.returncode == 0, stderr_kind(again)
    assert digest(state(work, sessions[0])[1]) == digest(refs[0]), "the reference changed"
    assert "more turn(s)" not in again.stderr


def test_short_deadline_leaves_the_request_uncertain(work):
    session_id = harness(work, "session", "create", "real-uncertain").stdout.strip()
    stuck = harness(work, "ask", session_id, LONG_ANSWER, HARNESS_REQUEST_TIMEOUT_S="16")
    assert stuck.returncode == 1
    assert stderr_kind(stuck) == "uncertain"
    rows = query(work, "SELECT status FROM requests WHERE session_id = ?", (session_id,))
    assert rows == [("uncertain",)]
    assert (work / DATABASE_NAME).is_file()
