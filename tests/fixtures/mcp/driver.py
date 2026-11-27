"""Runs the harness CLI in this process with a probe around it, for the tests that must not
risk the pytest process itself.

Usage: python driver.py MODE STATE_DIR ARGV...
- `interrupt`: once the synthetic server has logged the call, deliver Ctrl+C to the main thread
  (`_thread.interrupt_main`, the same on every platform).
- `sockets`: record every `socket.bind` audit event (SDK import included) in STATE_DIR, each
  with whether its call stack is the event loop's own socket pair (`audit_site/socket_origin`).
  `AI_HARNESS_TEST_FALLBACK_SOCKETPAIR=1` forces the pure-Python `socketpair` Windows uses.
- `interrupt-stuck`: replace the harness's session process with `stuck_worker.py` (it hangs
  in C code holding the GIL) and deliver Ctrl+C once it has started.
The exit code is the CLI's.
"""

from __future__ import annotations

import _thread
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent / "audit_site"))

import socket_origin  # noqa: E402 - test-only, next to this file

mode, state = sys.argv[1], Path(sys.argv[2])
argv = sys.argv[3:]
binds: list[dict] = []


def _socket_hook(event: str, args: tuple) -> None:
    if event != "socket.bind":
        return
    binds.append({"address": repr(args[1]), **socket_origin.classify(sys._getframe(1))})


def _interrupt_when_called() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if (state / "calls.log").exists():
            time.sleep(0.3)
            _thread.interrupt_main()
            return
        time.sleep(0.05)


def _interrupt_when_stuck() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if (state / "stuck.log").exists():
            time.sleep(0.5)
            _thread.interrupt_main()
            return
        time.sleep(0.05)


if mode == "sockets":
    socket_origin.force_fallback()
    sys.addaudithook(_socket_hook)
elif mode == "interrupt-stuck":
    import harness.mcp.client as client_module

    stuck = Path(__file__).resolve().parent / "stuck_worker.py"
    client_module.WORKER_ARGS = [str(stuck), str(state)]
    threading.Thread(target=_interrupt_when_stuck, daemon=True).start()
elif mode == "interrupt":
    threading.Thread(target=_interrupt_when_called, daemon=True).start()

from harness.cli import main  # noqa: E402 - after the hook, so the SDK import is covered

code = main(argv)
if mode == "sockets":
    (state / "binds.json").write_text(json.dumps(binds), encoding="utf-8")
    (state / "binds-environment.json").write_text(json.dumps(socket_origin.environment()),
                                                  encoding="utf-8")
sys.exit(code)
