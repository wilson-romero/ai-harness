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


def _frame_line(frame) -> str:
    """One frame, without any path: base name, function, module, and which of the classifier's
    file tests it passes (`S`: the standard library's socket.py, `L`: its asyncio loop files)."""
    where = _file(frame)
    marks = ("S" if where == _SOCKET_PY else "") + ("L" if where in _LOOP_FILES else "")
    module = frame.f_globals.get("__name__", "?")
    return (f"{os.path.basename(frame.f_code.co_filename)}:{frame.f_code.co_name}"
            f" [{module}]{' ' + marks if marks else ''}")


def classify(frame) -> dict:
    """`{"self_pipe": bool, "why": str, "stack": [...]}` for the event raised under `frame`.

    Revised on 2026-11-26: on one Windows machine the loop's own pair was reported as foreign,
    on another not, with the same CPython code on this path in 3.14.3 and 3.14.10. So a report
    carries what is needed to tell why without a second run: the reason, and every frame up to
    24 with its module and the file tests it passed. Files are named by base name only, so a
    report holds no path of the machine."""
    stack = []
    walk = frame
    while walk is not None and len(stack) < 24:
        stack.append(_frame_line(walk))
        walk = walk.f_back
    names = set()
    while frame is not None and _file(frame) == _SOCKET_PY:
        names.add(frame.f_code.co_name)
        frame = frame.f_back
    if not names & _PAIR:
        why = "no socketpair frame in the standard library's socket.py"
    elif frame is None:
        why = "nothing called socketpair"
    elif frame.f_code.co_name != "_make_self_pipe":
        why = f"socketpair called by {frame.f_code.co_name}, not _make_self_pipe"
    elif _file(frame) not in _LOOP_FILES:
        why = "_make_self_pipe is not in the standard library's asyncio"
    else:
        why = SELF_PIPE
    return {"self_pipe": why == SELF_PIPE, "why": why, "stack": stack}


SELF_PIPE = "the event loop's own pair"


def environment() -> dict:
    """What a report needs to rule in or out something wrapping `socket` in every process."""
    import sys

    stdlib = set(sys.stdlib_module_names)
    return {
        "python": sys.version.split()[0],
        "socketpair": getattr(socket.socketpair, "__name__", repr(socket.socketpair)),
        "socket_class_module": socket.socket.__module__,
        "socket_init_file": os.path.basename(socket.socket.__init__.__code__.co_filename),
        "outside_stdlib": sorted({m.split(".")[0] for m in list(sys.modules)} - stdlib
                                 - {"__main__", "sitecustomize", "socket_origin"}),
    }
