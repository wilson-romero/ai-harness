"""Named locks backed by SQLite's own file locking.

Holding an exclusive transaction on a small lock database is the lock. SQLite takes care of
the operating system's locking primitive, so this is the same code on every platform, and the
operating system releases the lock when the owning process dies, however it dies. That makes
"the lock is free" a reliable sign that nobody is still working on what it protects.

Only SQLite's "busy" and "locked" answers mean "taken". Any other error (for instance a lock
file held for a moment by a virus scanner on Windows) is retried until the caller's deadline
and then raised, never reported as "taken". Deadlines use the monotonic clock.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
import time
from pathlib import Path
from uuid import UUID

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_POLL_S = 0.05


class NamedLock:
    """Exclusive lock with a plain file name, under `<data_dir>/locks/`."""

    def __init__(self, data_dir: Path, name: str) -> None:
        if not _NAME_RE.fullmatch(name):
            raise ValueError(f"invalid lock name {name!r}")
        self._path = data_dir / "locks" / f"{name}.lock"
        self._conn: sqlite3.Connection | None = None
        self.last_error: str | None = None  # SQLite's error name of the last failed attempt

    def _try(self) -> bool:
        """One attempt. False when another holder has the lock; other errors are raised."""
        conn = None
        try:
            conn = sqlite3.connect(self._path, timeout=0, autocommit=True)
            conn.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            if conn is not None:
                conn.close()
            self.last_error = _error_name(exc)
            if _is_busy(exc):
                return False
            raise
        self._conn = conn
        self.last_error = None
        return True

    def acquire(self, wait_s: float = 0.0) -> bool:
        """Take the lock if it is free, waiting up to `wait_s`. False if another holder has it."""
        if self._conn is not None:
            return True
        self._path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + wait_s
        while True:
            failure = None
            try:
                if self._try():
                    return True
            except sqlite3.OperationalError as exc:
                failure = exc
            if time.monotonic() >= deadline:
                if failure is not None:
                    raise failure
                return False
            time.sleep(min(_POLL_S, max(0.0, deadline - time.monotonic())))

    async def acquire_within(self, timeout_s: float, poll_s: float = 0.25) -> bool:
        """`acquire` for async code: polls without blocking the event loop."""
        deadline = time.monotonic() + timeout_s
        while True:
            failure = None
            try:
                if self.acquire():
                    return True
            except sqlite3.OperationalError as exc:
                failure = exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if failure is not None:
                    raise failure
                return False
            await asyncio.sleep(min(poll_s, remaining))

    def release(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute("ROLLBACK")
        finally:
            self._conn.close()
            self._conn = None


class SessionLock(NamedLock):
    """Exclusive, non-blocking lock for one session."""

    def __init__(self, data_dir: Path, session_id: UUID) -> None:
        super().__init__(data_dir, str(session_id))


def _is_busy(exc: sqlite3.OperationalError) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    if code is None:  # older SQLite bindings: fall back to the message
        return "locked" in str(exc) or "busy" in str(exc)
    return code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


def _error_name(exc: sqlite3.OperationalError) -> str:
    return getattr(exc, "sqlite_errorname", None) or str(exc)
