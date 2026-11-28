"""SQLite connection and numbered migrations."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from harness.storage.private import private_dir, private_file

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
DATABASE_NAME = "harness.sqlite3"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


OPEN_RETRY_S = 5.0
# Revised on 2026-11-26. A process killed while it holds the WAL database can keep its `-shm`
# file mapped for a moment after it is reported dead (Windows). The next opener truncates
# `-shm`, and SQLite before its fix of 2026-10-05 fails that with SQLITE_IOERR_TRUNCATE
# ("disk I/O error"; SQLITE_IOERR_SHMOPEN in older versions). That error, at open only, is
# transient: it is retried for a bounded time. Any other error is raised at once.
_TRANSIENT_OPEN_ERRORS = {"SQLITE_IOERR_TRUNCATE", "SQLITE_IOERR_SHMOPEN"}


def connect(data_dir: Path) -> sqlite3.Connection:
    """Open the local database. Transactions are explicit: see `transaction`."""
    private_dir(data_dir)  # owner-only where the system uses permission bits (F-08)
    private_file(data_dir / DATABASE_NAME)
    deadline = time.monotonic() + OPEN_RETRY_S
    pause = 0.02
    while True:
        conn = sqlite3.connect(data_dir / DATABASE_NAME, autocommit=True, timeout=5.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            return conn
        except sqlite3.OperationalError as exc:
            conn.close()
            transient = getattr(exc, "sqlite_errorname", None) in _TRANSIENT_OPEN_ERRORS
            if not transient or time.monotonic() >= deadline:
                raise
        except BaseException:
            conn.close()
            raise
        time.sleep(pause)
        pause = min(pause * 2, 0.25)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


# The first line of a migration that rebuilds a table other tables refer to (code-mode A2,
# migration 010). SQLite cannot change a CHECK in place; its documented procedure (create the
# new table, copy, drop the old one, rename) needs the foreign keys off, which only takes
# effect outside a transaction. Such a migration runs with them off, inside its transaction,
# and is refused (rolled back) unless `PRAGMA foreign_key_check` finds no broken reference.
FOREIGN_KEYS_OFF = "-- migrate: foreign keys off"


class MigrationError(sqlite3.IntegrityError):
    """A rebuilding migration would leave a broken reference: nothing of it was applied."""


def migrate(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[int]:
    """Apply pending migrations in order and return the versions applied now."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied: list[int] = []
    for path in sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(path.name[:3])
        script = path.read_text(encoding="utf-8")
        rebuilds = script.startswith(FOREIGN_KEYS_OFF)
        if rebuilds:
            conn.execute("PRAGMA foreign_keys = OFF")
        try:
            with transaction(conn):
                done = conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
                ).fetchone()
                if done:
                    continue
                conn.executescript(script)
                if rebuilds and conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise MigrationError(f"migration {version} would break a reference; "
                                         "nothing of it was applied")
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, utc_now()),
                )
                applied.append(version)
        finally:
            if rebuilds:
                conn.execute("PRAGMA foreign_keys = ON")
    return applied


def open_database(data_dir: Path) -> sqlite3.Connection:
    conn = connect(data_dir)
    migrate(conn)
    return conn
