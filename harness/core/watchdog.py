"""A last-resort deadline that fires even when the event loop cannot.

The request deadline is enforced by `asyncio.timeout` around the provider, and every browser
cleanup has its own bound. Both need the event loop to run. If something ever blocks the
interpreter's main thread (a call that never returns and never yields), neither can fire, and
neither can Ctrl+C, which asyncio also delivers through the loop.

This watchdog is an ordinary thread with its own monotonic deadline. Python switches threads
even while the main thread runs or waits in a blocking call, so it still gets to run. When the
deadline passes and the guarded work has not finished, it prints one fixed line and ends the
process with `os._exit`. Ending the process is the boundary that can always be enforced:

- the operating system releases the session and browser locks (they are SQLite file locks);
- Playwright's driver loses its pipe to this process and closes the browser it launched, so
  only the harness's own Edge goes away; nothing is looked up or signalled by name or PID;
- the request stays `pending` or `running` in SQLite, and the next command's recovery marks it
  `uncertain` and never resends it, as after any crash.

The alternative, running the browser work in a child process and killing it, was not taken
(design D3, revised 2026-11-25): the prompt, the `on_sent` moment and the remote reference
would have to cross a process boundary as they happen, which adds a protocol and its own
failure points, while the in-process boundary above already ends everything the harness owns.
"""

from __future__ import annotations

import os
import sys
import threading
from types import TracebackType

EXIT_WATCHDOG = 124  # as `timeout(1)`: the command was stopped because a deadline passed


class Watchdog:
    """`with Watchdog(seconds):` ends the process if the block is still running after `seconds`."""

    def __init__(self, seconds: float, what: str = "the request") -> None:
        self._seconds = seconds
        self._what = what
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._watch, name="harness-watchdog", daemon=True)

    def _watch(self) -> None:
        # `Event.wait` measures with the monotonic clock.
        if self._done.wait(self._seconds):
            return
        try:
            sys.stderr.write(
                f"error: {self._what} did not finish {self._seconds:.0f} s after it started, "
                "even after its deadline and cleanup time; the harness stopped itself. "
                "The next command marks an unfinished request as uncertain; nothing is resent\n"
            )
            sys.stderr.flush()
        finally:
            os._exit(EXIT_WATCHDOG)

    def __enter__(self) -> Watchdog:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._done.set()
