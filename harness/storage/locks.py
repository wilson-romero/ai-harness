"""Per-session and named locks backed by SQLite's own file locking.

Holding an exclusive transaction on a small per-session database is the lock. SQLite takes
care of the operating system's locking primitive, so this is the same code on every platform,
and the operating system releases the lock when the owning process dies, however it dies.
That makes "the lock is free" a reliable sign that nobody is still working on the session.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
import time
from pathlib import Path
from uuid import UUID

LOCK_NAME = re.compile(r"[a-z][a-z0-9-]{0,31}")


class _ExclusiveLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None
        self.last_error: str | None = None  # SQLite's error name of the last failed attempt

    def acquire(self) -> bool:
        """Take the lock if it is free. Returns False when another holder has it.

        Only SQLite's "busy" and "locked" answers mean "taken"; any other error is raised,
        so a broken lock file is never mistaken for a busy one.
        """
        if self._conn is not None:
            return True
        self._path.parent.mkdir(parents=True, exist_ok=True)
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

    def release(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute("ROLLBACK")
        finally:
            self._conn.close()
            self._conn = None


class SessionLock(_ExclusiveLock):
    """Exclusive, non-blocking lock for one session."""

    def __init__(self, data_dir: Path, session_id: UUID) -> None:
        super().__init__(data_dir / "locks" / f"{session_id}.lock")


class NamedLock(_ExclusiveLock):
    """Exclusive lock for a shared resource such as the browser, same mechanism as sessions.

    A name is lowercase letters, digits and hyphens, so it can never collide with a session id.
    """

    def __init__(self, data_dir: Path, name: str) -> None:
        if not LOCK_NAME.fullmatch(name) or _looks_like_uuid(name):
            raise ValueError(f"invalid lock name {name!r}")
        super().__init__(data_dir / "locks" / f"{name}.lock")

    async def acquire_within(self, timeout_s: float, poll_s: float = 0.25) -> bool:
        """Poll until the lock is free or `timeout_s` runs out. False when it ran out.

        The deadline is checked against the monotonic clock on every attempt. An error other
        than "busy" (for instance a file briefly held by a virus scanner on Windows) is retried
        until the deadline and then raised, never reported as "busy".
        """
        deadline = time.monotonic() + timeout_s
        failure: sqlite3.OperationalError | None = None
        while True:
            try:
                if self.acquire():
                    return True
                failure = None
            except sqlite3.OperationalError as exc:
                failure = exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if failure is not None:
                    raise failure
                return False
            await asyncio.sleep(min(poll_s, remaining))


def _is_busy(exc: sqlite3.OperationalError) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    if code is None:  # older SQLite bindings: fall back to the message
        return "locked" in str(exc) or "busy" in str(exc)
    return code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


def _error_name(exc: sqlite3.OperationalError) -> str:
    return getattr(exc, "sqlite_errorname", None) or str(exc)


def _looks_like_uuid(name: str) -> bool:
    try:
        UUID(name)
    except ValueError:
        return False
    return True
