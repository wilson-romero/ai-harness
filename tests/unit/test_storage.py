import sqlite3
from datetime import UTC, datetime
from uuid import uuid7

import pytest

from harness.core.contracts import RequestStatus, Session, SessionStatus
from harness.storage import repositories as repo
from harness.storage.database import (
    MIGRATIONS_DIR,
    connect,
    migrate,
    open_database,
    transaction,
)


def _new_session(conn, name="Synthetic") -> Session:
    now = datetime.now(UTC)
    session = Session(
        session_id=uuid7(),
        name=name,
        provider="mock",
        status=SessionStatus.CREATED,
        created_at=now,
        updated_at=now,
    )
    with transaction(conn):
        repo.insert_session(conn, session)
    return session


def test_first_run_creates_the_schema(conn):
    tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    session_core = {"sessions", "requests", "messages", "audit_events", "schema_migrations"}
    assert tables == session_core | {
        "request_context", "skill_runs", "skill_steps", "approvals", "tool_calls",
        "effect_sources", "plan_runs",
    }
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migrating_twice_changes_nothing(data_dir):
    first = open_database(data_dir)
    session = _new_session(first)
    first.close()

    second = connect(data_dir)
    before = second.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall()
    assert migrate(second) == []
    after = second.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall()
    assert [tuple(r) for r in after] == [tuple(r) for r in before]
    assert [r["version"] for r in after] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert repo.get_session(second, session.session_id) == session
    second.close()


def test_session_round_trip_and_listing_order(conn):
    older = _new_session(conn, "older")
    newer = _new_session(conn, "newer")
    assert repo.get_session(conn, older.session_id) == older
    assert repo.get_session(conn, uuid7()) is None
    assert [s.name for s in repo.list_sessions(conn)] == ["newer", "older"]
    with transaction(conn):
        repo.set_session_status(conn, older.session_id, SessionStatus.ACTIVE)
    assert repo.list_sessions(conn)[0].session_id == older.session_id
    assert newer.session_id != older.session_id


def test_request_and_message_round_trip(conn):
    session = _new_session(conn)
    request_id = uuid7()
    with transaction(conn):
        repo.insert_request(conn, request_id, session.session_id)
        repo.insert_message(
            conn, session_id=session.session_id, request_id=request_id, role="user", content="q"
        )
    assert repo.in_flight_requests(conn) == {session.session_id: [request_id]}

    with transaction(conn):
        repo.insert_message(
            conn,
            session_id=session.session_id,
            request_id=request_id,
            role="assistant",
            content="a",
        )
        repo.set_request_status(conn, request_id, RequestStatus.COMPLETED, duration_ms=7)
    assert repo.in_flight_requests(conn) == {}
    entries = repo.history(conn, session.session_id)
    assert [(e.role, e.content) for e in entries] == [("user", "q"), ("assistant", "a")]
    assert {e.request_status for e in entries} == {RequestStatus.COMPLETED}
    row = conn.execute("SELECT duration_ms, finished_at FROM requests").fetchone()
    assert row["duration_ms"] == 7 and row["finished_at"] is not None


def test_audit_round_trip(conn):
    session = _new_session(conn)
    with transaction(conn):
        repo.insert_audit(
            conn,
            event_type="session.created",
            outcome="ok",
            actor="cli",
            session_id=session.session_id,
        )
    row = conn.execute("SELECT * FROM audit_events").fetchone()
    assert (row["event_type"], row["outcome"], row["actor"]) == ("session.created", "ok", "cli")
    assert row["session_id"] == str(session.session_id) and row["request_id"] is None


def test_request_context_needs_an_existing_request(conn):
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            repo.insert_request_context(
                conn,
                request_id=uuid7(),
                note_path="projects/demo-alpha/_project.md",
                sha256="0" * 64,
                size_bytes=10,
                truncated=False,
            )


# -- migration 003: skills (skill-engine D8) ------------------------------------------------------


def _new_run(conn, session, status="pending", run_id=None):
    run_id = run_id or str(uuid7())
    conn.execute(
        "INSERT INTO skill_runs (run_id, session_id, skill_name, skill_version, skill_sha256,"
        " status, inputs_manifest, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, str(session.session_id), "demo-echo", "1.0.0", "0" * 64, status, "{}",
         "2026-11-24T00:00:00+00:00", "2026-11-24T00:00:00+00:00"),
    )
    return run_id


def _new_approval(conn, run_id, status="pending"):
    conn.execute(
        "INSERT INTO approvals (approval_id, run_id, step_key, scope, proposal_hash, status,"
        " created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid7()), run_id, "confirm", "none", "a" * 64, status,
         "2026-11-24T00:00:00+00:00", "2026-11-24T00:15:00+00:00"),
    )


def test_skill_indexes_exist(conn):
    indexes = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        if not row[0].startswith("sqlite_autoindex")
    }
    assert {"idx_skill_runs_one_open_per_session", "idx_approvals_one_live_per_step"} <= indexes
    columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_events)")}
    assert {"run_id", "detail"} <= columns


def test_one_open_run_per_session(conn):
    session = _new_session(conn)
    with transaction(conn):
        _new_run(conn, session, "awaiting_approval")
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            _new_run(conn, session, "pending")
    with transaction(conn):  # closed runs do not count
        _new_run(conn, session, "completed")
        _new_run(conn, session, "cancelled")
    other = _new_session(conn, "other")
    with transaction(conn):
        _new_run(conn, other, "running")


def test_one_live_approval_per_step(conn):
    session = _new_session(conn)
    with transaction(conn):
        run_id = _new_run(conn, session)
        _new_approval(conn, run_id, "pending")
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            _new_approval(conn, run_id, "granted")
    with transaction(conn):
        _new_approval(conn, run_id, "expired")
        _new_approval(conn, run_id, "consumed")


@pytest.mark.parametrize(
    "table, sql",
    [
        ("skill_runs", "UPDATE skill_runs SET status = 'paused'"),
        ("skill_runs", "UPDATE skill_runs SET skill_sha256 = 'short'"),
        ("approvals", "UPDATE approvals SET status = 'approved'"),
        ("approvals", "UPDATE approvals SET channel = 'file'"),
    ],
)
def test_skill_checks_refuse_unknown_values(conn, table, sql):
    session = _new_session(conn)
    with transaction(conn):
        run_id = _new_run(conn, session)
        _new_approval(conn, run_id)
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            conn.execute(sql)


def test_skill_run_needs_an_existing_session(conn):
    class Ghost:
        session_id = uuid7()

    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            _new_run(conn, Ghost)


def test_a_remote_reference_belongs_to_one_session(conn):
    """Review 2026-11-26 (SEC-02): binding a reference another session holds is refused
    with a controlled error, and nothing changes."""
    first, second = _new_session(conn, "A"), _new_session(conn, "B")
    with transaction(conn):
        assert repo.bind_remote_ref(conn, first.session_id, "conv-0001")
    with pytest.raises(repo.RemoteRefTaken), transaction(conn):
        repo.bind_remote_ref(conn, second.session_id, "conv-0001")
    assert repo.get_session(conn, second.session_id).remote_ref is None
    assert repo.get_session(conn, first.session_id).remote_ref == "conv-0001"
    # Control: another reference binds as usual, and sessions with none do not conflict.
    with transaction(conn):
        assert repo.bind_remote_ref(conn, second.session_id, "conv-0002")
    _new_session(conn, "C")
    _new_session(conn, "D")


def test_a_database_at_008_upgrades_to_009_and_keeps_its_rows(data_dir, tmp_path):
    """response-mode (008) and code-mode (009) in order: a database left at 008 takes 009 only,
    its sessions keep their mode, and the new table and columns are there and empty."""
    up_to_8 = tmp_path / "migrations-008"
    up_to_8.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("00[1-8]_*.sql")):
        (up_to_8 / path.name).write_text(path.read_text("utf-8"), "utf-8")
    conn = connect(data_dir)
    assert migrate(conn, up_to_8) == [1, 2, 3, 4, 5, 6, 7, 8]
    session = _new_session(conn, "A")
    with transaction(conn):
        conn.execute("UPDATE sessions SET response_mode = 'deep' WHERE name = 'A'")
    assert migrate(conn) == [9]
    assert conn.execute("SELECT response_mode FROM sessions WHERE session_id = ?",
                        (str(session.session_id),)).fetchone()[0] == "deep"
    assert conn.execute("SELECT COUNT(*) FROM plan_runs").fetchone()[0] == 0
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(tool_calls)")}
    assert {"plan_id", "plan_step"} <= columns
    assert migrate(conn) == []
    conn.close()


def test_migration_007_unbinds_every_session_of_a_shared_reference(data_dir, tmp_path):
    """Duplicates written before migration 007: nobody can tell whose context the remote
    conversation holds, so every session that shares it is unbound (and audited); a
    reference held by one session only is kept."""
    up_to_6 = tmp_path / "migrations-006"
    up_to_6.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("00[1-6]_*.sql")):
        (up_to_6 / path.name).write_text(path.read_text("utf-8"), "utf-8")
    conn = connect(data_dir)
    assert migrate(conn, up_to_6) == [1, 2, 3, 4, 5, 6]
    a, b, c = _new_session(conn, "A"), _new_session(conn, "B"), _new_session(conn, "C")
    with transaction(conn):
        repo.bind_remote_ref(conn, a.session_id, "conv-shared")
        repo.bind_remote_ref(conn, b.session_id, "conv-shared")  # allowed before 007
        repo.bind_remote_ref(conn, c.session_id, "conv-own")
    assert migrate(conn) == [7, 8, 9]  # and 008 (response-mode), 009 (code-mode)
    refs = {r["name"]: r["remote_ref"] for r in conn.execute("SELECT name, remote_ref FROM sessions")}
    assert refs == {"A": None, "B": None, "C": "conv-own"}
    audited = conn.execute(
        "SELECT session_id, outcome FROM audit_events WHERE event_type = 'session.unbound'"
    ).fetchall()
    assert sorted(tuple(r) for r in audited) == sorted(
        [(str(a.session_id), "duplicate_remote_ref"), (str(b.session_id), "duplicate_remote_ref")])
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE sessions SET remote_ref = 'conv-own' WHERE name = 'A'")
    conn.close()
