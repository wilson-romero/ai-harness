"""The `tool_calls` audit rows (mcp-gateway D11): every decision, never any content."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid7

from harness.storage.database import transaction, utc_now
from harness.text.safe_text import safe_foreign_line

NAME_LIMIT = 64
# Longest a `running` row can belong to a live command: both deadlines at their maximum plus
# the watchdog's margins (client.ABANDON_MARGIN_S), rounded up generously.
STALE_AFTER_S = 900


def stored_name(text: str) -> str:
    """A requested server or tool name as stored: cleaned and redacted first, then cut."""
    return safe_foreign_line(text).text[:NAME_LIMIT]


@dataclass(frozen=True)
class CallRow:
    call_id: str


def record_denied(
    conn: sqlite3.Connection,
    server: str,
    tool: str,
    reason: str,
    operation: str | None,
    canonical_args: bytes,
    args_bytes: int,
) -> CallRow:
    call_id = str(uuid7())
    with transaction(conn):
        conn.execute(
            "INSERT INTO tool_calls (call_id, server, tool, operation, decision, reason, "
            "args_sha256, args_bytes, status, created_at, finished_at) "
            "VALUES (?, ?, ?, ?, 'denied', ?, ?, ?, 'denied', ?, ?)",
            (
                call_id, stored_name(server), stored_name(tool), operation, reason,
                _sha256(canonical_args), args_bytes, utc_now(), utc_now(),
            ),
        )
    return CallRow(call_id)


def record_running(
    conn: sqlite3.Connection, server: str, tool: str, operation: str, canonical_args: bytes
) -> CallRow:
    """Committed before the server is started, so a crash leaves a `running` row behind."""
    call_id = str(uuid7())
    with transaction(conn):
        conn.execute(
            "INSERT INTO tool_calls (call_id, server, tool, operation, decision, reason, "
            "args_sha256, args_bytes, status, created_at) "
            "VALUES (?, ?, ?, ?, 'allowed', 'allowed', ?, ?, 'running', ?)",
            (
                call_id, stored_name(server), stored_name(tool), operation,
                _sha256(canonical_args), len(canonical_args), utc_now(),
            ),
        )
    return CallRow(call_id)


def record_denied_after_listing(
    conn: sqlite3.Connection, row: CallRow, reason: str, server_stopped: bool | None,
    duration_ms: int,
) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE tool_calls SET decision = 'denied', reason = ?, status = 'denied', "
            "server_stopped = ?, duration_ms = ?, finished_at = ? "
            "WHERE call_id = ? AND status = 'running'",
            (reason, _flag(server_stopped), duration_ms, utc_now(), row.call_id),
        )


def record_finished(
    conn: sqlite3.Connection,
    row: CallRow,
    status: str,
    error_code: str | None,
    server_stopped: bool | None,
    result_bytes: int | None,
    duration_ms: int,
) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE tool_calls SET status = ?, error_code = ?, server_stopped = ?, "
            "result_bytes = ?, duration_ms = ?, finished_at = ? "
            "WHERE call_id = ? AND status = 'running'",
            (status, error_code, _flag(server_stopped), result_bytes, duration_ms, utc_now(),
             row.call_id),
        )


def recover_stale(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """A `running` row older than any live command can be was interrupted: mark it so.

    For a read this is exact (repeating it changes nothing); writes do not exist yet.
    """
    limit = ((now or datetime.now(UTC)) - timedelta(seconds=STALE_AFTER_S)).isoformat()
    with transaction(conn):
        cursor = conn.execute(
            "UPDATE tool_calls SET status = 'failed', error_code = 'interrupted', finished_at = ? "
            "WHERE status = 'running' AND created_at < ?",
            (utc_now(), limit),
        )
    return cursor.rowcount


def _sha256(data: bytes) -> str | None:
    return hashlib.sha256(data).hexdigest() if data else None


def _flag(value: bool | None) -> int | None:
    return None if value is None else int(value)
