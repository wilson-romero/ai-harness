import subprocess
import sys
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


def _python(*args: str, stdout=subprocess.PIPE) -> subprocess.Popen[str]:
    return subprocess.Popen([sys.executable, "-c", *args], cwd=REPO_ROOT, stdout=stdout, text=True)


def test_named_lock_is_independent_from_session_locks(tmp_path):
    browser = NamedLock(tmp_path, "browser")
    assert browser.acquire()
    assert not NamedLock(tmp_path, "browser").acquire()
    assert SessionLock(tmp_path, uuid7()).acquire()
    browser.release()


def test_named_lock_rejects_names_that_could_be_paths_or_sessions(tmp_path):
    for name in ("../browser", "Browser", "", str(uuid7()), "a" * 40):
        with pytest.raises(ValueError):
            NamedLock(tmp_path, name)


def test_second_process_waits_for_the_named_lock_and_gets_it(tmp_path):
    holder = _python(NAMED_HOLDER, str(tmp_path), "1.5")
    try:
        assert holder.stdout.readline().strip() == "held"
        waiter = _python(NAMED_WAITER, str(tmp_path), "20")
        verdict, waited = waiter.communicate(timeout=30)[0].split()
        assert verdict == "acquired"
        assert float(waited) >= 0.5  # it really waited for the holder
    finally:
        holder.kill()
        holder.wait(timeout=10)


def test_second_process_gives_up_when_its_deadline_runs_out(tmp_path):
    holder = _python(NAMED_HOLDER, str(tmp_path), "60")
    try:
        assert holder.stdout.readline().strip() == "held"
        waiter = _python(NAMED_WAITER, str(tmp_path), "0.6")
        verdict, waited = waiter.communicate(timeout=30)[0].split()
        assert verdict == "busy"
        assert 0.5 <= float(waited) < 5
    finally:
        holder.kill()
        holder.wait(timeout=10)
