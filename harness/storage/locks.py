"""Per-session lock backed by SQLite's own file locking.

Holding an exclusive transaction on a small per-session database is the lock. SQLite takes
care of the operating system's locking primitive, so this is the same code on every platform,
and the operating system releases the lock when the owning process dies, however it dies.
That makes "the lock is free" a reliable sign that nobody is still working on the session.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID


class SessionLock:
    """Exclusive, non-blocking lock for one session."""

    def __init__(self, data_dir: Path, session_id: UUID) -> None:
        self._path = data_dir / "locks" / f"{session_id}.lock"
        self._conn: sqlite3.Connection | None = None

    def acquire(self) -> bool:
        """Take the lock if it is free. Returns False when another holder has it."""
        if self._conn is not None:
            return True
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, timeout=0, autocommit=True)
        try:
            conn.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError:
            conn.close()
            return False
        self._conn = conn
        return True

    def release(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute("ROLLBACK")
        finally:
            self._conn.close()
            self._conn = None
