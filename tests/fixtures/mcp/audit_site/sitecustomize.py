"""Test-only audit hook, loaded by every Python process whose PYTHONPATH includes this folder.

It records each socket a process creates (`socket.__new__`) and each `socket.bind`, tagging
those made by the standard library's `socketpair` (the event loop's self-pipe on every
platform), into `<AI_HARNESS_TEST_SOCKET_LOG>/sockets-<pid>.json` when the process exits. A
socket that `listen()`s binds itself implicitly without a `bind` event, but it cannot avoid
being created: `socket.__new__` is the event that cannot be skipped.

The harness's MCP session process inherits a copy of the harness's environment, so it is
covered too; MCP servers get a filtered environment and are not.
"""

from __future__ import annotations

import atexit
import json
import os
import sys

_target = os.environ.get("AI_HARNESS_TEST_SOCKET_LOG")
_events: list[dict] = []


def _from_socketpair() -> bool:
    frame = sys._getframe(1)
    while frame is not None:
        code = frame.f_code
        if code.co_name == "socketpair" and code.co_filename.endswith("socket.py"):
            return True
        frame = frame.f_back
    return False


def _hook(event: str, args: tuple) -> None:
    if event == "socket.__new__":
        _events.append({"event": event, "family": int(args[1]), "socketpair": _from_socketpair()})
    elif event == "socket.bind":
        _events.append({"event": event, "address": repr(args[1]),
                        "socketpair": _from_socketpair()})


def _write() -> None:
    try:
        path = os.path.join(_target, f"sockets-{os.getpid()}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"argv": sys.argv[:3], "events": _events}, handle)
    except OSError:
        pass


if _target:
    sys.addaudithook(_hook)
    atexit.register(_write)
