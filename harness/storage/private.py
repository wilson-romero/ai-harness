"""Owner-only directories and files under HARNESS_DATA_DIR (security review 2026-11-27, F-08).

What the harness creates there (the data directory itself, the database and its WAL and
shared-memory files, the lock files, `copilot/`) is created readable by its owner only: 0700
for a directory, 0600 for a file. The same calls on every platform: where the system does not
use POSIX permission bits (Windows), the mode is ignored and the entry has the permissions it
inherits from its parent folder; no ACL is set or checked. Only what is created is narrowed:
an entry that already exists keeps its mode.
"""

from __future__ import annotations

import os
from pathlib import Path

DIR_MODE = 0o700
FILE_MODE = 0o600


def private_dir(path: Path) -> None:
    """Create `path` and every missing parent as owner-only directories (`mkdir` with
    `parents=True` would create the parents with the default mode)."""
    missing = []
    current = path
    while not current.exists() and current.parent != current:
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=DIR_MODE, exist_ok=True)


def private_file(path: Path) -> None:
    """Create `path` empty and owner-only if it does not exist; an existing one is not opened.

    SQLite gives a database's `-wal` and `-shm` files the mode of the database file, so a
    database created here first is owner-only with them.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        os.close(os.open(path, flags, FILE_MODE))
    except FileExistsError:
        pass
