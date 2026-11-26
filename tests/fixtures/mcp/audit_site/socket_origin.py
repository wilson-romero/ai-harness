"""Test-only: tells the event loop's own socket pair apart from any other socket, by call stack.

Every asyncio event loop makes a "self-pipe" when it starts: `_make_self_pipe` in
`asyncio/selector_events.py` or `asyncio/proactor_events.py` calls `socket.socketpair()`.
Where `_socket` has no native `socketpair` (Windows), `socket.socketpair` IS
`socket._fallback_socketpair`, which creates a listening TCP socket on loopback port 0,
connects to it once, accepts that one connection, checks both ends' addresses and closes the
listener before returning. So on Windows the loop's start shows a `socket.bind` to
`('127.0.0.1', 0)` (hotfix 0.2.1: v0.2.0 matched the frame name `socketpair` only, and missed
`_fallback_socketpair`).

An event is the self-pipe only when, walking up from the code that raised it, every frame is
in the standard library's `socket.py` until the first one that is not, at least one of those is
`socketpair` or `_fallback_socketpair`, and the first frame outside `socket.py` is
`_make_self_pipe` in the standard library's asyncio. The address alone proves nothing: the
same `_fallback_socketpair` called from anywhere else is reported as a foreign socket.

`AI_HARNESS_TEST_FALLBACK_SOCKETPAIR=1` makes `socket.socketpair` the pure-Python fallback in
this process (CPython keeps it "so that it can be patched in for testing purposes"): Windows's
condition, on any system.
"""

from __future__ import annotations

import os
import socket

_SOCKET_PY = os.path.normcase(os.path.abspath(socket.__file__))
_STDLIB = os.path.dirname(_SOCKET_PY)
_LOOP_FILES = {
    os.path.normcase(os.path.join(_STDLIB, "asyncio", name))
    for name in ("selector_events.py", "proactor_events.py")
}
_PAIR = {"socketpair", "_fallback_socketpair"}
LOOPBACK_PORT_ZERO = {"('127.0.0.1', 0)", "('::1', 0)"}


def force_fallback() -> None:
    if os.environ.get("AI_HARNESS_TEST_FALLBACK_SOCKETPAIR") == "1":
        socket.socketpair = socket._fallback_socketpair


def _file(frame) -> str:
    return os.path.normcase(os.path.abspath(frame.f_code.co_filename))


def classify(frame) -> dict:
    """`{"self_pipe": bool, "stack": [...]}` for the event raised under `frame`. The stack names
    files by base name only, so a report holds no path of the machine."""
    stack = []
    walk = frame
    while walk is not None and len(stack) < 8:
        stack.append(f"{os.path.basename(walk.f_code.co_filename)}:{walk.f_code.co_name}")
        walk = walk.f_back
    names = set()
    while frame is not None and _file(frame) == _SOCKET_PY:
        names.add(frame.f_code.co_name)
        frame = frame.f_back
    self_pipe = (
        bool(names & _PAIR)
        and frame is not None
        and frame.f_code.co_name == "_make_self_pipe"
        and _file(frame) in _LOOP_FILES
    )
    return {"self_pipe": self_pipe, "stack": stack}
