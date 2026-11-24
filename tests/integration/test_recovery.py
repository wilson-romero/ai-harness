"""SEC-07 and SEC-08: interrupted requests become uncertain and are never resent."""

import signal
import sys

import pytest

from harness.core.contracts import RequestStatus, SessionStatus
from harness.providers.mock import MockProvider
from harness.storage import repositories as repo
from harness.storage.database import transaction
from tests.conftest import query, run_main, spawn_main, wait_for_running
from uuid import uuid7

SLOW = {"HARNESS_MOCK_DELAY_MS": "60000"}


def _create(data_dir, name="S") -> str:
    result = run_main(data_dir, "session", "create", name)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _status(data_dir, request_id: str) -> str:
    return query(data_dir, "SELECT status FROM requests WHERE request_id = ?", (request_id,))[0][0]


def test_history_survives_a_new_process(data_dir):
    session_id = _create(data_dir)
    asked = run_main(data_dir, "ask", session_id, "persisted question")
    assert asked.returncode == 0
    history = run_main(data_dir, "history", session_id)
    assert history.returncode == 0
    assert "persisted question" in history.stdout
    assert asked.stdout.strip() in history.stdout


def test_killed_process_leaves_the_request_uncertain(data_dir):
    session_id = _create(data_dir)
    proc = spawn_main(data_dir, "ask", session_id, "will be interrupted", **SLOW)
    try:
        request_id = wait_for_running(data_dir, session_id)
        proc.kill()
        proc.wait(timeout=10)
    finally:
        proc.kill()

    listing = run_main(data_dir, "session", "list")
    assert listing.returncode == 0
    assert _status(data_dir, request_id) == "uncertain"
    assert listing.stdout.split("\t")[1] == "uncertain"
    history = run_main(data_dir, "history", session_id)
    assert history.stdout.strip() == "[uncertain] user: will be interrupted"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Ctrl+C cannot be delivered to a single child process on Windows; "
    "checked by hand in the demo",
)
def test_ctrl_c_after_send_leaves_the_request_uncertain(data_dir):
    session_id = _create(data_dir)
    proc = spawn_main(data_dir, "ask", session_id, "interrupt me", **SLOW)
    try:
        request_id = wait_for_running(data_dir, session_id)
        proc.send_signal(signal.SIGINT)
        code = proc.wait(timeout=10)
    finally:
        proc.kill()
    assert code == 130
    # Already uncertain before any other command runs: no recovery was involved.
    assert _status(data_dir, request_id) == "uncertain"
    assert query(data_dir, "SELECT actor FROM audit_events WHERE outcome = 'uncertain'") == [
        ("cli",)
    ]


def test_recovery_does_not_resend(conn, make_service):
    provider = MockProvider()
    service = make_service({"mock": provider})
    session = service.create_session("S")
    orphan = uuid7()
    with transaction(conn):  # a request left behind by a process that no longer exists
        repo.insert_request(conn, orphan, session.session_id)

    assert service.recover() == [orphan]
    assert provider.calls == 0
    assert conn.execute("SELECT status, error_code FROM requests").fetchone()[:] == (
        "uncertain",
        "interrupted",
    )
    assert repo.get_session(conn, session.session_id).status is SessionStatus.UNCERTAIN
    assert service.recover() == []


async def test_repeating_is_a_new_request_and_session_returns_to_active(conn, make_service):
    uncertain = make_service({"mock": MockProvider("timeout_after_send")}, timeout_s=0.2)
    session = uncertain.create_session("S")
    first = await uncertain.ask(str(session.session_id), "same text")
    assert first.status is RequestStatus.UNCERTAIN and first.warnings == ()

    healthy = make_service()
    second = await healthy.ask(str(session.session_id), "same text")
    assert second.status is RequestStatus.COMPLETED
    assert second.request_id != first.request_id
    assert any("earlier uncertain request" in w for w in second.warnings)
    statuses = dict(conn.execute("SELECT request_id, status FROM requests").fetchall())
    assert statuses == {str(first.request_id): "uncertain", str(second.request_id): "completed"}
    assert repo.get_session(conn, session.session_id).status is SessionStatus.ACTIVE


def test_warning_reaches_stderr(cli):
    session_id = cli("session", "create", "S")[1].strip()
    cli(
        "ask",
        session_id,
        "hello",
        HARNESS_MOCK_BEHAVIOR="timeout_after_send",
        HARNESS_REQUEST_TIMEOUT_S="0.2",
    )
    code, out, err = cli("ask", session_id, "hello again")
    assert code == 0 and out.startswith("[mock ")
    assert "warning:" in err and "uncertain" in err


def test_live_request_is_not_touched_by_another_process(data_dir):
    session_id = _create(data_dir)
    proc = spawn_main(data_dir, "ask", session_id, "still running", HARNESS_MOCK_DELAY_MS="3000")
    try:
        request_id = wait_for_running(data_dir, session_id)
        listing = run_main(data_dir, "session", "list")
        assert listing.returncode == 0
        assert _status(data_dir, request_id) == "running"
        assert proc.wait(timeout=30) == 0
    finally:
        proc.kill()
    assert _status(data_dir, request_id) == "completed"


def test_second_question_in_a_busy_session_is_rejected(data_dir):
    session_id = _create(data_dir)
    proc = spawn_main(data_dir, "ask", session_id, "first", **SLOW)
    try:
        wait_for_running(data_dir, session_id)
        second = run_main(data_dir, "ask", session_id, "otra")
        assert second.returncode == 1
        assert "already has a question in progress" in second.stderr
        assert query(data_dir, "SELECT count(*) FROM requests") == [(1,)]
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_questions_in_different_sessions_both_complete(data_dir):
    a, b = _create(data_dir, "A"), _create(data_dir, "B")
    delay = {"HARNESS_MOCK_DELAY_MS": "500"}
    procs = [spawn_main(data_dir, "ask", sid, "parallel", **delay) for sid in (a, b)]
    try:
        assert [p.wait(timeout=30) for p in procs] == [0, 0]
    finally:
        for p in procs:
            p.kill()
    assert query(data_dir, "SELECT status FROM requests") == [("completed",), ("completed",)]
