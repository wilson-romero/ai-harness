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
lock = NamedLock(Path(sys.argv[1]), sys.argv[2])
assert lock.acquire()
print("held", flush=True)
time.sleep(120)
"""


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
    holder = subprocess.Popen(
        [sys.executable, "-c", NAMED_HOLDER, str(tmp_path), "shared"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        assert not NamedLock(tmp_path, "shared").acquire()
        assert NamedLock(tmp_path, "unrelated").acquire()
    finally:
        holder.kill()
        holder.wait(timeout=10)


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
