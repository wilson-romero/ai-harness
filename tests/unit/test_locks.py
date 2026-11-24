import sqlite3
import subprocess
import sys
import threading
import time
from uuid import uuid7

import pytest

from harness.storage.locks import NamedLock, SessionLock
from tests.conftest import REPO_ROOT

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


def test_lock_is_exclusive_and_reusable(tmp_path):
    session_id = uuid7()
    first = SessionLock(tmp_path, session_id)
    second = SessionLock(tmp_path, session_id)
    assert first.acquire()
    assert not second.acquire()
    assert SessionLock(tmp_path, uuid7()).acquire()  # another session is independent
    first.release()
    assert second.acquire()
    second.release()


def test_lock_is_freed_when_the_owner_process_is_killed(tmp_path):
    session_id = uuid7()
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(tmp_path), str(session_id)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        lock = SessionLock(tmp_path, session_id)
        assert not lock.acquire()
        holder.kill()
        holder.wait(timeout=10)
        deadline = time.monotonic() + 5
        while not lock.acquire():
            assert time.monotonic() < deadline, "the lock was not released after the kill"
            time.sleep(0.05)
        lock.release()
    finally:
        holder.kill()
        holder.wait(timeout=10)


NAMED_HOLDER = """
import sys, time
from pathlib import Path
from harness.storage.locks import NamedLock
lock = NamedLock(Path(sys.argv[1]), "browser")
assert lock.acquire()
print("held", flush=True)
time.sleep(float(sys.argv[2]))
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
# No step of these tests may block the suite for longer than this, on any platform.
STEP_LIMIT_S = 30


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


def _reap(*procs: subprocess.Popen[str]) -> None:
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


def test_named_lock_is_independent_from_session_locks(tmp_path):
    browser = NamedLock(tmp_path, "browser")
    assert browser.acquire()
    other = NamedLock(tmp_path, "browser")
    assert not other.acquire()
    assert other.last_error == "SQLITE_BUSY"
    assert SessionLock(tmp_path, uuid7()).acquire()
    browser.release()


def test_named_lock_rejects_names_that_could_be_paths_or_sessions(tmp_path):
    for name in ("../browser", "Browser", "", str(uuid7()), "a" * 40):
        with pytest.raises(ValueError):
            NamedLock(tmp_path, name)


async def test_a_lock_error_that_is_not_busy_is_retried_then_raised(tmp_path):
    (tmp_path / "locks" / "browser.lock").mkdir(parents=True)  # cannot be opened as a file
    lock = NamedLock(tmp_path, "browser")
    started = time.monotonic()
    with pytest.raises(sqlite3.OperationalError):
        await lock.acquire_within(0.6, poll_s=0.1)
    assert time.monotonic() - started >= 0.5  # retried until the deadline, not reported busy


def test_second_process_waits_for_the_named_lock_and_gets_it(tmp_path):
    holder = waiter = None
    try:
        holder = _python(NAMED_HOLDER, str(tmp_path), "1.5")
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
        holder = _python(NAMED_HOLDER, str(tmp_path), "60")
        assert _first_line(holder) == "held"
        waiter = _python(NAMED_WAITER, str(tmp_path), "0.6")
        out, err = _output(waiter)
        assert waiter.returncode == 0, err
        verdict, waited = out.split()
        assert verdict == "busy"
        assert 0.5 <= float(waited) < 5
    finally:
        _reap(waiter, holder)
