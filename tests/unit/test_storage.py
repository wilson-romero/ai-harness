import sqlite3
from datetime import UTC, datetime
from uuid import uuid7

import pytest

from harness.core.contracts import RequestStatus, Session, SessionStatus
from harness.storage import repositories as repo
from harness.storage.database import connect, migrate, open_database, transaction


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
    assert tables == session_core | {"memory_binding", "request_context"}
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
    assert [r["version"] for r in after] == [1, 2]
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


def test_memory_binding_holds_a_single_row(conn):
    with transaction(conn):
        repo.insert_memory_binding(conn, "work", "/vault-a")
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            repo.insert_memory_binding(conn, "work", "/vault-b")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE memory_binding SET profile = 'casa'")
    assert repo.get_memory_binding(conn) == ("work", "/vault-a")


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
