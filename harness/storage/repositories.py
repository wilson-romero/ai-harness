"""Parameterised queries. Callers own the transaction."""

from __future__ import annotations

import sqlite3
from uuid import UUID, uuid7

from harness.core.contracts import IN_FLIGHT, HistoryEntry, RequestStatus, Session, SessionStatus
from harness.storage.database import utc_now


def insert_session(conn: sqlite3.Connection, session: Session) -> None:
    conn.execute(
        "INSERT INTO sessions (session_id, name, project_id, provider, remote_ref, status,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(session.session_id),
            session.name,
            session.project_id,
            session.provider,
            session.remote_ref,
            session.status.value,
            session.created_at.isoformat(),
            session.updated_at.isoformat(),
        ),
    )


def get_session(conn: sqlite3.Connection, session_id: UUID) -> Session | None:
    row = conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (str(session_id),)
    ).fetchone()
    return Session(**dict(row)) if row else None


def list_sessions(conn: sqlite3.Connection) -> list[Session]:
    rows = conn.execute("SELECT * FROM sessions ORDER BY updated_at DESC, session_id DESC")
    return [Session(**dict(row)) for row in rows]


def set_session_status(conn: sqlite3.Connection, session_id: UUID, status: SessionStatus) -> None:
    conn.execute(
        "UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?",
        (status.value, utc_now(), str(session_id)),
    )


def insert_request(conn: sqlite3.Connection, request_id: UUID, session_id: UUID) -> None:
    conn.execute(
        "INSERT INTO requests (request_id, session_id, status, started_at) VALUES (?, ?, ?, ?)",
        (str(request_id), str(session_id), RequestStatus.PENDING.value, utc_now()),
    )


def set_request_status(
    conn: sqlite3.Connection,
    request_id: UUID,
    status: RequestStatus,
    *,
    error_code: str | None = None,
    duration_ms: int | None = None,
) -> None:
    finished_at = None if status in IN_FLIGHT else utc_now()
    conn.execute(
        "UPDATE requests SET status = ?, error_code = ?, duration_ms = ?, finished_at = ?"
        " WHERE request_id = ?",
        (status.value, error_code, duration_ms, finished_at, str(request_id)),
    )


def in_flight_requests(conn: sqlite3.Connection) -> dict[UUID, list[UUID]]:
    """Requests still pending or running, grouped by session."""
    rows = conn.execute(
        "SELECT session_id, request_id FROM requests WHERE status IN (?, ?) ORDER BY started_at",
        tuple(status.value for status in IN_FLIGHT),
    )
    grouped: dict[UUID, list[UUID]] = {}
    for row in rows:
        grouped.setdefault(UUID(row["session_id"]), []).append(UUID(row["request_id"]))
    return grouped


def insert_message(
    conn: sqlite3.Connection,
    *,
    session_id: UUID,
    request_id: UUID,
    role: str,
    content: str | None,
) -> None:
    conn.execute(
        "INSERT INTO messages (message_id, session_id, request_id, role, content, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid7()), str(session_id), str(request_id), role, content, utc_now()),
    )


def history(conn: sqlite3.Connection, session_id: UUID) -> list[HistoryEntry]:
    rows = conn.execute(
        "SELECT m.request_id, r.status AS request_status, m.role, m.content, m.created_at"
        " FROM messages m JOIN requests r ON r.request_id = m.request_id"
        " WHERE m.session_id = ? ORDER BY m.created_at, m.message_id",
        (str(session_id),),
    )
    return [HistoryEntry(**dict(row)) for row in rows]


def insert_audit(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    outcome: str,
    actor: str,
    session_id: UUID | None = None,
    request_id: UUID | None = None,
    run_id: str | None = None,
    detail: str | None = None,
) -> None:
    """Record what happened. There is deliberately no free-text column for content.

    `detail` is structured and built only from identifiers, hashes, counts and fixed names
    (step, attempt, limit), never from an input, a template or a model output.
    """
    conn.execute(
        "INSERT INTO audit_events (event_id, session_id, request_id, event_type, outcome, actor,"
        " created_at, run_id, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid7()),
            str(session_id) if session_id else None,
            str(request_id) if request_id else None,
            event_type,
            outcome,
            actor,
            utc_now(),
            run_id,
            detail,
        ),
    )


def insert_request_context(
    conn: sqlite3.Connection,
    *,
    request_id: UUID,
    note_path: str,
    sha256: str,
    size_bytes: int,
    truncated: bool,
) -> None:
    """Record that a note went out with a request. Path and hash only, never the text."""
    conn.execute(
        "INSERT INTO request_context (request_id, note_path, sha256, bytes, truncated)"
        " VALUES (?, ?, ?, ?, ?)",
        (str(request_id), note_path, sha256, size_bytes, int(truncated)),
    )
