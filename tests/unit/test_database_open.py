"""Opening the database right after another process was killed holding it (2026-11-26).

On Windows, a process killed while it holds a WAL database can keep its `-shm` file mapped
for a moment after it is reported dead. The next opener takes the dead-man lock and truncates
`-shm`; SQLite before its fix of 2026-10-05 ("Allow windows clients to open and recover a wal
mode database even if an old client still has the *-shm file mapped") failed that truncate
with SQLITE_IOERR_TRUNCATE ("disk I/O error"). The harness retries that one transient error,
and only that, for a bounded time. Simulated here: the real failure needs Windows and an old
SQLite.
"""

from __future__ import annotations

import sqlite3

import pytest

from harness.storage import database


class FlakyOpen:
    """`sqlite3.connect` whose `PRAGMA journal_mode` fails `failures` times with `name`."""

    def __init__(self, failures: int, name: str) -> None:
        self.failures, self.name, self.opened, self.closed = failures, name, 0, 0
        self.real = sqlite3.connect

    def __call__(self, *args, **kwargs):
        self.opened += 1
        conn = self.real(*args, **kwargs)
        flaky = self

        class Conn:
            row_factory = None

            def __setattr__(self, key, value):
                setattr(conn, key, value)

            def execute(self, sql, *params):
                if "journal_mode" in sql and flaky.failures > 0:
                    flaky.failures -= 1
                    error = sqlite3.OperationalError("disk I/O error")
                    error.sqlite_errorname = flaky.name
                    raise error
                return conn.execute(sql, *params)

            def close(self):
                flaky.closed += 1
                conn.close()

            def __getattr__(self, key):
                return getattr(conn, key)

        return Conn()


def test_a_transient_shm_truncate_error_is_retried(tmp_path, monkeypatch):
    flaky = FlakyOpen(3, "SQLITE_IOERR_TRUNCATE")
    monkeypatch.setattr(database.sqlite3, "connect", flaky)
    conn = database.connect(tmp_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()
    assert flaky.opened == 4 and flaky.closed == 4  # every failed attempt was closed


@pytest.mark.parametrize("name", ["SQLITE_IOERR", "SQLITE_IOERR_WRITE", "SQLITE_CORRUPT", None])
def test_any_other_open_error_is_not_retried(tmp_path, monkeypatch, name):
    flaky = FlakyOpen(1, name)
    monkeypatch.setattr(database.sqlite3, "connect", flaky)
    with pytest.raises(sqlite3.OperationalError):
        database.connect(tmp_path)
    assert flaky.opened == 1 and flaky.closed == 1


def test_the_retry_is_bounded(tmp_path, monkeypatch):
    flaky = FlakyOpen(10**6, "SQLITE_IOERR_TRUNCATE")
    monkeypatch.setattr(database.sqlite3, "connect", flaky)
    monkeypatch.setattr(database, "OPEN_RETRY_S", 0.3)
    with pytest.raises(sqlite3.OperationalError):
        database.connect(tmp_path)
    assert 1 < flaky.opened < 50 and flaky.closed == flaky.opened
