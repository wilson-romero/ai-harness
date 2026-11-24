import subprocess
import sys
import time
from uuid import uuid7

from harness.storage.locks import SessionLock
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
