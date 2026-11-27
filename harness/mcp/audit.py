"""The `tool_calls` audit rows (mcp-gateway D11): every decision, never any content."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid7

from harness.storage.database import transaction, utc_now
from harness.storage.locks import NamedLock
from harness.text.safe_text import safe_foreign_line

NAME_LIMIT = 64
KEY_BYTES = 32
# The arguments are kept as HMAC-SHA-256 under a random key of this installation (revised on
# 2026-11-24): the same arguments give the same digest here, so repeated calls can be told
# apart, but a guessable argument (a project slug) cannot be confirmed by hashing guesses.
ARGS_KEY = Path("keys") / "mcp-args.key"
KEY_LOCK_WAIT_S = 10.0


def stored_name(text: str) -> str:
    """A requested server or tool name as stored: cleaned and redacted first, then cut."""
    return safe_foreign_line(text).text[:NAME_LIMIT]


@dataclass(frozen=True)
class CallRow:
    call_id: str


def new_call_id() -> str:
    return str(uuid7())


def call_lock(data_dir: Path, call_id: str) -> NamedLock:
    """Held by the command for as long as its call row is `running` (taken before the row is
    written). The operating system releases it when that process ends, however it ends."""
    return NamedLock(data_dir, f"mcp-call-{call_id}")


def args_key(data_dir: Path) -> bytes:
    """The installation's key for argument digests: created once, readable by its owner only,
    never printed.

    A key file of the wrong length (v0.2.0 on Windows wrote one in about eight with b"\\n"
    turned into b"\\r\\n") is set aside as `mcp-args.key.damaged-<random>` and replaced
    (hotfix 0.2.1). No digest was ever computed with such a key, because every read checks the
    length, so no stored digest changes meaning; the old file is kept, not deleted.

    Revised on 2026-11-26: every read of the key file is done under the same lock as its
    recovery. Where the system refuses to rename a file another handle has open (Windows), a
    read outside the lock made a concurrent recovery's rename fail (WinError 32).
    """
    path = data_dir / ARGS_KEY
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if hasattr(os, "getuid"):
        os.chmod(path.parent, 0o700)
    lock = NamedLock(data_dir, "mcp-args-key")
    if not lock.acquire(wait_s=KEY_LOCK_WAIT_S):
        raise OSError("the MCP argument key is busy")
    try:
        key = _read_key(path)
        if key is not None and len(key) == KEY_BYTES:
            return key
        if key is not None:
            path.rename(path.with_name(f"{path.name}.damaged-{secrets.token_hex(8)}"))
        _create_key(path)
        key = path.read_bytes()
    finally:
        lock.release()
    if len(key) != KEY_BYTES:
        raise OSError("the MCP argument key is damaged")
    return key


def _read_key(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _create_key(path: Path) -> None:
    temporary = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
    # O_BINARY: in text mode Windows writes each b"\\n" of the key as b"\\r\\n".
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        os.write(descriptor, secrets.token_bytes(KEY_BYTES))
    finally:
        os.close(descriptor)
    try:
        os.link(temporary, path)  # never replaces a key another process wrote first
    except FileExistsError:
        pass
    finally:
        os.unlink(temporary)


def record_denied(
    conn: sqlite3.Connection,
    server: str,
    tool: str,
    reason: str,
    operation: str | None,
    canonical_args: bytes,
    args_bytes: int,
    key: bytes,
) -> CallRow:
    call_id = new_call_id()
    with transaction(conn):
        conn.execute(
            "INSERT INTO tool_calls (call_id, server, tool, operation, decision, reason, "
            "args_hmac, args_bytes, status, created_at, finished_at) "
            "VALUES (?, ?, ?, ?, 'denied', ?, ?, ?, 'denied', ?, ?)",
            (
                call_id, stored_name(server), stored_name(tool), operation, reason,
                _digest(key, canonical_args), args_bytes, utc_now(), utc_now(),
            ),
        )
    return CallRow(call_id)


def record_running(
    conn: sqlite3.Connection, call_id: str, server: str, tool: str, operation: str,
    canonical_args: bytes, key: bytes,
) -> CallRow:
    """Committed before the server is started, so a crash leaves a `running` row behind. The
    caller already holds `call_lock(data_dir, call_id)`."""
    with transaction(conn):
        conn.execute(
            "INSERT INTO tool_calls (call_id, server, tool, operation, decision, reason, "
            "args_hmac, args_bytes, status, created_at) "
            "VALUES (?, ?, ?, ?, 'allowed', 'allowed', ?, ?, 'running', ?)",
            (
                call_id, stored_name(server), stored_name(tool), operation,
                _digest(key, canonical_args), len(canonical_args), utc_now(),
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


def recover_stale(conn: sqlite3.Connection, data_dir: Path, now: datetime | None = None) -> int:
    """Mark `failed`/`interrupted` every `running` row whose lock nobody holds.

    Revised on 2026-11-24: "stale" no longer means "older than N seconds" (a live call held
    past that was mislabelled) but "its owner is gone", which the lock tells exactly. For a read
    this is safe (repeating it changes nothing); writes do not exist yet.
    """
    finished = (now or datetime.now(UTC)).isoformat()
    running = [r[0] for r in conn.execute(
        "SELECT call_id FROM tool_calls WHERE status = 'running'").fetchall()]
    recovered = 0
    for call_id in running:
        lock = call_lock(data_dir, call_id)
        if not lock.acquire():
            continue  # a live command holds it
        try:
            with transaction(conn):
                cursor = conn.execute(
                    "UPDATE tool_calls SET status = 'failed', error_code = 'interrupted', "
                    "finished_at = ? WHERE call_id = ? AND status = 'running'",
                    (finished, call_id),
                )
            recovered += cursor.rowcount
        finally:
            lock.release()
            forget_lock(data_dir, call_id)
    return recovered


def forget_lock(data_dir: Path, call_id: str) -> None:
    """Remove a released call lock's file (its row is no longer `running`)."""
    try:
        (data_dir / "locks" / f"mcp-call-{call_id}.lock").unlink()
    except OSError:
        pass


def _digest(key: bytes, data: bytes) -> str | None:
    return hmac.new(key, data, hashlib.sha256).hexdigest() if data else None


def _flag(value: bool | None) -> int | None:
    return None if value is None else int(value)
