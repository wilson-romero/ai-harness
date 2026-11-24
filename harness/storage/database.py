"""SQLite connection and numbered migrations."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
DATABASE_NAME = "harness.sqlite3"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def connect(data_dir: Path) -> sqlite3.Connection:
    """Open the local database. Transactions are explicit: see `transaction`."""
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data_dir / DATABASE_NAME, autocommit=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[int]:
    """Apply pending migrations in order and return the versions applied now."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied: list[int] = []
    for path in sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(path.name[:3])
        with transaction(conn):
            done = conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
            ).fetchone()
            if done:
                continue
            conn.executescript(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, utc_now()),
            )
            applied.append(version)
    return applied


def open_database(data_dir: Path) -> sqlite3.Connection:
    conn = connect(data_dir)
    migrate(conn)
    return conn
