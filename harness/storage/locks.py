"""Per-session lock backed by an OS file lock.

The operating system releases the lock when the owning process dies, however it dies. That
makes "the lock is free" a reliable sign that nobody is still working on the session.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import UUID

if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class SessionLock:
    """Exclusive, non-blocking lock for one session."""

    def __init__(self, data_dir: Path, session_id: UUID) -> None:
        self._path = data_dir / "locks" / f"{session_id}.lock"
        self._fd: int | None = None

    def acquire(self) -> bool:
        """Take the lock if it is free. Returns False when another holder has it."""
        if self._fd is not None:
            return True
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT)
        if not _try_lock(fd):
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            _unlock(self._fd)
        finally:
            os.close(self._fd)
            self._fd = None
