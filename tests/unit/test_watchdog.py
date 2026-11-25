"""The last-resort deadline ends the process even when its main thread never yields."""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from harness.core.watchdog import EXIT_WATCHDOG
from tests.conftest import REPO_ROOT

BLOCKERS = {
    # A blocking call in the main thread, as a stuck I/O call would be.
    "sleeping": "time.sleep(60)",
    # A busy loop: the main thread never waits, never awaits, never returns.
    "spinning": "while True:\n        pass",
}


def child(blocker: str, guarded: bool) -> str:
    body = BLOCKERS[blocker]
    guard = "with Watchdog(1.0, 'the test work'):" if guarded else "if True:"
    return (
        "import time\n"
        "from harness.core.watchdog import Watchdog\n"
        f"{guard}\n"
        f"    {body}\n"
    )


@pytest.mark.parametrize("blocker", sorted(BLOCKERS))
def test_watchdog_ends_a_blocked_process(blocker):
    started = time.monotonic()
    done = subprocess.run(
        [sys.executable, "-c", child(blocker, guarded=True)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    elapsed = time.monotonic() - started
    assert done.returncode == EXIT_WATCHDOG
    assert "the test work did not finish" in done.stderr and "nothing is resent" in done.stderr
    assert elapsed < 10


@pytest.mark.parametrize("blocker", sorted(BLOCKERS))
def test_without_the_watchdog_the_process_stays_blocked(blocker):
    """Negative control: the same child without the watchdog is still running."""
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(
            [sys.executable, "-c", child(blocker, guarded=False)],
            cwd=REPO_ROOT,
            capture_output=True,
            timeout=4,
        )


def test_finished_work_disarms_the_watchdog():
    code = (
        "import time\n"
        "from harness.core.watchdog import Watchdog\n"
        "with Watchdog(1.0):\n"
        "    pass\n"
        "time.sleep(2)\n"
        "print('still here')\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30
    )
    assert done.returncode == 0 and done.stdout.strip() == "still here"
