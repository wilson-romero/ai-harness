import sqlite3
import subprocess
import sys
import threading
import time
from uuid import uuid7

import pytest

from harness.storage.locks import NamedLock, SessionLock
from tests.conftest import REPO_ROOT

# No step of these tests may block the suite for longer than this, on any platform.
STEP_LIMIT_S = 30

HOLDER = """
import sys, time
from pathlib import Path
from uuid import UUID
from harness.storage.locks import SessionLock
lock = SessionLock(Path(sys.argv[1]), UUID(sys.argv[2]))
assert lock.acquire()
print("held", flush=True)
time.sleep(120)
"""

NAMED_HOLDER = """
import sys, time
from pathlib import Path
from harness.storage.locks import NamedLock
lock = NamedLock(Path(sys.argv[1]), sys.argv[2])
assert lock.acquire()
print("held", flush=True)
time.sleep(float(sys.argv[3]) if len(sys.argv) > 3 else 120)
lock.release()
"""

NAMED_WAITER = """
import asyncio, sys, time
from pathlib import Path
from harness.storage.locks import NamedLock
lock = NamedLock(Path(sys.argv[1]), "browser")
started = time.monotonic()
acquired = asyncio.run(lock.acquire_within(float(sys.argv[2])))
print("acquired" if acquired else "busy", round(time.monotonic() - started, 2), flush=True)
"""


def _python(*args: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", *args],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _first_line(proc: subprocess.Popen[str], timeout_s: float = STEP_LIMIT_S) -> str:
    """The child's first line of output, or a failure after `timeout_s`, never a hang."""
    line: list[str] = []
    reader = threading.Thread(target=lambda: line.append(proc.stdout.readline()), daemon=True)
    reader.start()
    reader.join(timeout_s)
    if reader.is_alive():
        raise AssertionError(f"no output from the child within {timeout_s} s")
    return line[0].strip()


def _output(proc: subprocess.Popen[str], timeout_s: float = STEP_LIMIT_S) -> tuple[str, str]:
    try:
        return proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _reap(proc)
        raise AssertionError(f"the child did not finish within {timeout_s} s") from None


def _reap(*procs: subprocess.Popen[str] | None) -> None:
    """Kill and wait for every child; closing the pipes means no reader thread can block."""
    for proc in procs:
        if proc is None:
            continue
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=STEP_LIMIT_S)
        except subprocess.TimeoutExpired:
            pass
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()


def test_lock_is_exclusive_and_reusable(tmp_path):
    session_id = uuid7()
    first = SessionLock(tmp_path, session_id)
    second = SessionLock(tmp_path, session_id)
    assert first.acquire()
    assert not second.acquire()
    assert second.last_error == "SQLITE_BUSY"
    assert SessionLock(tmp_path, uuid7()).acquire()  # another session is independent
    first.release()
    assert second.acquire()
    second.release()


def test_lock_is_freed_when_the_owner_process_is_killed(tmp_path):
    session_id = uuid7()
    holder = None
    try:
        holder = _python(HOLDER, str(tmp_path), str(session_id))
        assert _first_line(holder) == "held"
        lock = SessionLock(tmp_path, session_id)
        assert not lock.acquire()
        _reap(holder)
        assert lock.acquire(wait_s=5), "the lock was not released after the kill"
        lock.release()
    finally:
        _reap(holder)


def test_named_locks_exclude_only_the_same_name(tmp_path):
    first = NamedLock(tmp_path, "vault-decisions")
    assert first.acquire()
    assert not NamedLock(tmp_path, "vault-decisions").acquire()
    other = NamedLock(tmp_path, "another-name")
    assert other.acquire()
    other.release()
    first.release()


def test_session_lock_is_the_named_lock_of_the_session(tmp_path):
    session_id = uuid7()
    held = SessionLock(tmp_path, session_id)
    assert held.acquire()
    assert not NamedLock(tmp_path, str(session_id)).acquire()
    held.release()


def test_named_lock_held_by_another_process(tmp_path):
    holder = None
    try:
        holder = _python(NAMED_HOLDER, str(tmp_path), "shared")
        assert _first_line(holder) == "held"
        assert not NamedLock(tmp_path, "shared").acquire()
        assert NamedLock(tmp_path, "unrelated").acquire()
    finally:
        _reap(holder)


def test_named_lock_waits_up_to_its_timeout(tmp_path):
    first = NamedLock(tmp_path, "slow")
    assert first.acquire()
    started = time.monotonic()
    assert not NamedLock(tmp_path, "slow").acquire(wait_s=0.3)
    assert time.monotonic() - started >= 0.25
    first.release()


@pytest.mark.parametrize("name", ["", "../x", "a/b", "a\\b", ".hidden", "x" * 129])
def test_named_lock_rejects_names_that_are_not_plain_file_names(tmp_path, name):
    with pytest.raises(ValueError):
        NamedLock(tmp_path, name)


def test_a_lock_error_that_is_not_busy_is_retried_then_raised(tmp_path):
    (tmp_path / "locks" / "broken.lock").mkdir(parents=True)  # cannot be opened as a file
    lock = NamedLock(tmp_path, "broken")
    started = time.monotonic()
    with pytest.raises(sqlite3.OperationalError):
        lock.acquire(wait_s=0.6)
    assert time.monotonic() - started >= 0.5  # retried until the deadline, not reported busy


async def test_a_lock_error_that_is_not_busy_is_retried_then_raised_async(tmp_path):
    (tmp_path / "locks" / "browser.lock").mkdir(parents=True)
    lock = NamedLock(tmp_path, "browser")
    started = time.monotonic()
    with pytest.raises(sqlite3.OperationalError):
        await lock.acquire_within(0.6, poll_s=0.1)
    assert time.monotonic() - started >= 0.5


def _windows_open(monkeypatch):
    """`os.open` as Windows answers it (second Windows run, 2026-11-27): an existing
    directory opened with O_CREAT | O_EXCL is 'permission denied', not 'exists'."""
    import errno
    import os

    from harness.storage import private

    real = os.open

    def opened(path, flags, mode=0o777, *args, **kwargs):
        if flags & os.O_EXCL and os.path.isdir(path):
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return real(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(private.os, "open", opened)


def test_a_lock_error_that_is_not_busy_is_retried_then_raised_where_open_says_denied(
        tmp_path, monkeypatch):
    _windows_open(monkeypatch)
    (tmp_path / "locks" / "broken.lock").mkdir(parents=True)
    lock = NamedLock(tmp_path, "broken")
    started = time.monotonic()
    with pytest.raises(sqlite3.OperationalError):
        lock.acquire(wait_s=0.6)
    assert time.monotonic() - started >= 0.5


async def test_a_lock_error_that_is_not_busy_is_retried_then_raised_where_open_says_denied_async(
        tmp_path, monkeypatch):
    _windows_open(monkeypatch)
    (tmp_path / "locks" / "browser.lock").mkdir(parents=True)
    lock = NamedLock(tmp_path, "browser")
    started = time.monotonic()
    with pytest.raises(sqlite3.OperationalError):
        await lock.acquire_within(0.6, poll_s=0.1)
    assert time.monotonic() - started >= 0.5


def test_second_process_waits_for_the_named_lock_and_gets_it(tmp_path):
    holder = waiter = None
    try:
        holder = _python(NAMED_HOLDER, str(tmp_path), "browser", "1.5")
        assert _first_line(holder) == "held"
        waiter = _python(NAMED_WAITER, str(tmp_path), "20")
        out, err = _output(waiter)
        assert waiter.returncode == 0, err
        verdict, waited = out.split()
        assert verdict == "acquired"
        assert float(waited) >= 0.5  # it really waited for the holder
    finally:
        _reap(waiter, holder)


def test_second_process_gives_up_when_its_deadline_runs_out(tmp_path):
    holder = waiter = None
    try:
        holder = _python(NAMED_HOLDER, str(tmp_path), "browser", "60")
        assert _first_line(holder) == "held"
        waiter = _python(NAMED_WAITER, str(tmp_path), "0.6")
        out, err = _output(waiter)
        assert waiter.returncode == 0, err
        verdict, waited = out.split()
        assert verdict == "busy"
        assert 0.5 <= float(waited) < 5
    finally:
        _reap(waiter, holder)
