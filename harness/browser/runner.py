"""Run a browser coroutine so that every way out leaves nothing behind and prints nothing late.

When the Playwright driver dies (a console Ctrl+C reaches it as well as Python, or someone ends
it), Playwright stores "Connection closed while reading from the driver" in a future that nobody
awaits once the run is over. asyncio reports such a future when it is garbage-collected, which
can be after the caller printed its result. This runner retrieves those errors itself, before
returning, so the caller's last line is the last thing printed.
"""

from __future__ import annotations

import asyncio
import gc
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

DRIVER_GONE = "Connection closed while reading from the driver"


def is_driver_leftover(context: dict[str, Any]) -> bool:
    """An error left in a Playwright future after the driver or the browser went away."""
    exc = context.get("exception")
    # By module, so that a command that never drives a browser does not import Playwright.
    if exc is not None and type(exc).__module__.startswith("playwright."):
        return True
    return type(exc) is Exception and str(exc) == DRIVER_GONE


def quiet_handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    if is_driver_leftover(context):
        return  # the run already ended; the caller reports the outcome
    loop.default_exception_handler(context)


def run_browser(main: Coroutine[Any, Any, T]) -> T:
    """`asyncio.run` for code that drives the browser. Ctrl+C still raises KeyboardInterrupt."""
    with asyncio.Runner() as runner:
        runner.get_loop().set_exception_handler(quiet_handler)
        try:
            return runner.run(main)
        finally:
            gc.collect()  # unreferenced Playwright futures report now, to the handler above
