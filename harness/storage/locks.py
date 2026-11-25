"""Named locks backed by SQLite's own file locking.

Holding an exclusive transaction on a small lock database is the lock. SQLite takes care of
the operating system's locking primitive, so this is the same code on every platform, and the
operating system releases the lock when the owning process dies, however it dies. That makes
"the lock is free" a reliable sign that nobody is still working on what it protects.
"""

from __future__ import annotations

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

    def acquire(self, wait_s: float = 0.0) -> bool:
        """Take the lock if it is free, waiting up to `wait_s`. False if another holder has it."""
        if self._conn is not None:
            return True
        self._path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + wait_s
        while True:
            conn = sqlite3.connect(self._path, timeout=0, autocommit=True)
            try:
                conn.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError:
                conn.close()
                if time.monotonic() >= deadline:
                    return False
                time.sleep(_POLL_S)
                continue
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


class SessionLock(NamedLock):
    """Exclusive, non-blocking lock for one session."""

    def __init__(self, data_dir: Path, session_id: UUID) -> None:
        super().__init__(data_dir, str(session_id))
