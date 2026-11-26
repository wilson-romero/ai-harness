"""Helpers for the MCP tests: synthetic allowlists, bounded process runs, liveness checks.

Liveness is checked without any platform branch and without signals (`os.kill(pid, 0)` would
kill the process on Windows): the synthetic server rewrites a heartbeat file every 100 ms
while it lives, so a heartbeat that stops changing means the process is gone.

Revised on 2026-11-25 (a flaky test on a loaded machine): "stopped" needs the beat to stay
still for `QUIET_S` (ten missed beats), and "alive" only needs one change within `ALIVE_S`. A
live process on a busy machine can pause for half a second; it does not pause for three.
"""

from __future__ import annotations

import faulthandler
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.conftest import HARNESS_VARS, REPO_ROOT

SERVER = REPO_ROOT / "tests" / "fixtures" / "mcp" / "synthetic_server.py"
PROJECT_ARG = {"type": "string", "max_length": 64, "pattern": "[a-z0-9][a-z0-9-]*",
               "required": True}
# An absolute program path that is valid on every platform. A literal such as
# "/opt/x/server" is absolute on POSIX only: on Windows it has no drive, the allowlist
# rejects it and the module fails at import time.
ABSOLUTE_PROGRAM = sys.executable

DEFAULT_TOOLS = {
    "get_project_metadata": {"operation": "read", "arguments": {"project": PROJECT_ARG}},
    "set_project_metadata": {
        "operation": "write",
        "arguments": {"project": PROJECT_ARG,
                      "status": {"type": "enum", "values": ["activo", "pausado"]}},
    },
    "echo_env": {"operation": "read",
                 "arguments": {"name": {"type": "string", "max_length": 128, "required": True}}},
    "env_names": {"operation": "read"},
    "echo_argv": {"operation": "read"},
    # Declared here, not offered by the server.
    "archive_project": {"operation": "read", "arguments": {"project": PROJECT_ARG}},
    # Offered with a schema that has no `project`.
    "rename_project": {"operation": "read", "arguments": {"project": {**PROJECT_ARG, "required": False}}},
}
# A hung test aborts with a traceback in two minutes instead of hanging the run for hours.
HANG_GUARD_S = 120
QUIET_S = 1.0  # a heartbeat unchanged this long: the process is gone
ALIVE_S = 3.0  # a heartbeat that changes within this: the process lives
POLL_S = 0.1


def _read_beat(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def heartbeat_stopped(path: Path, within_s: float = 5.0) -> bool:
    """True once the file has not changed for `QUIET_S`, if that happens within `within_s`.
    A file that does not exist counts as stopped: callers that need it to exist check that."""
    deadline = time.monotonic() + within_s
    previous = _read_beat(path)
    still_since = time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(POLL_S)
        current = _read_beat(path)
        if current != previous:
            previous, still_since = current, time.monotonic()
        elif time.monotonic() - still_since >= QUIET_S:
            return True
    return False


def heartbeat_alive(path: Path, within_s: float = ALIVE_S) -> bool:
    """True if the file changes at least once within `within_s`."""
    deadline = time.monotonic() + within_s
    first = _read_beat(path)
    while time.monotonic() < deadline:
        time.sleep(POLL_S)
        if _read_beat(path) != first:
            return True
    return False


@pytest.fixture
def hang_guard() -> Iterator[None]:
    faulthandler.dump_traceback_later(HANG_GUARD_S, exit=True, file=sys.__stderr__)
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()


def server_entry(
    state: Path,
    mode: str = "ok",
    *,
    extra: tuple[str, ...] = (),
    env: tuple[str, ...] = (),
    startup: int = 5,
    call: int = 5,
    tools: dict | None = None,
) -> dict:
    command = [sys.executable, str(SERVER), "--state", str(state), "--mode", mode,
               "--repo", str(REPO_ROOT), *extra]
    return {
        "command": command,
        "env": list(env),
        "startup_timeout_s": startup,
        "call_timeout_s": call,
        "tools": DEFAULT_TOOLS if tools is None else tools,
    }


def write_config(path: Path, servers: dict) -> Path:
    path.write_text(json.dumps({"format": "ai-harness/mcp/1", "servers": servers}, indent=2),
                    encoding="utf-8")
    return path


class Server:
    """The state directory of one synthetic server instance."""

    def __init__(self, state: Path) -> None:
        self.state = state

    @property
    def started(self) -> bool:
        return (self.state / "starts.log").exists()

    def starts(self) -> int:
        path = self.state / "starts.log"
        return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0

    def calls(self) -> list[str]:
        path = self.state / "calls.log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def stopped(self, within_s: float = 5.0) -> bool:
        """True once the heartbeat has stayed still for `QUIET_S`, within the bound."""
        if not self.started:
            return True
        return heartbeat_stopped(self.state / "heartbeat", within_s)

    def alive(self) -> bool:
        # Not "stopped within ALIVE_S": a dead server answers in QUIET_S, a live one in ALIVE_S.
        return self.started and not heartbeat_stopped(self.state / "heartbeat", ALIVE_S)


def kill_survivors(server: Server) -> None:
    """Test cleanup only: a server whose heartbeat still moves is killed by the pid it logged."""
    if not server.alive():
        return
    for line in (server.state / "starts.log").read_text(encoding="utf-8").splitlines():
        pid = int(line.rsplit(" ", 1)[-1])
        try:
            os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except OSError:
            pass


def result_lines(out: str) -> str:
    """A tool result as printed on stdout, without the `| ` line prefix (review finding 7).
    Fails if any line lacks the prefix."""
    lines = []
    for line in out.splitlines():
        assert line.startswith("|"), f"unprefixed result line: {line!r}"
        lines.append(line[2:])
    return "\n".join(lines)


# The only addresses the event loop's own socket pair binds when it is the pure-Python
# emulation (Windows): loopback, ephemeral port (hotfix 0.2.1).
LOOPBACK_PORT_ZERO = {"('127.0.0.1', 0)", "('::1', 0)"}


def unexpected_sockets(report: dict, events: list[dict]) -> str:
    """The failure message of the socket oracle (revised on 2026-11-26): the process and its
    environment, then every unexpected event in full (what, address, why it is not the event
    loop's own pair, its whole stack), so one failing run says what happened."""
    lines = [f"process {report.get('argv')}: {report.get('environment')}"]
    for event in events:
        what = event["event"] + (f" {event['address']}" if "address" in event else "")
        if "family" in event:
            what += f" family={event['family']}"
        lines.append(f"- {what}: {event.get('why', '?')}")
        lines.extend(f"    {frame}" for frame in event.get("stack", []))
    return "\n".join(lines)


def child_env(**extra: str) -> dict[str, str]:
    """The environment of a harness process run by a test: a copy of this one, never built."""
    env = {k: v for k, v in os.environ.items() if k not in HARNESS_VARS}
    env["PYTHONUTF8"] = "1"
    env.update(extra)
    return env


def run_bounded(
    args: list[str], env: dict[str, str], work: Path, deadline_s: float = 90.0
) -> tuple[int | None, str, str, float]:
    """Run a process with its output in files (no pipe a grandchild could hold open), waiting
    up to a monotonic deadline measured here; killed and reaped in `finally`.

    Returns (exit code or None if it had to be killed, stdout, stderr, seconds).
    """
    work.mkdir(parents=True, exist_ok=True)
    out_path, err_path = work / "stdout.txt", work / "stderr.txt"
    started = time.monotonic()
    with out_path.open("wb") as out, err_path.open("wb") as err:
        process = subprocess.Popen(args, cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=err)
        try:
            while process.poll() is None and time.monotonic() - started < deadline_s:
                time.sleep(0.05)
            code = process.poll()
        finally:
            if process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
    elapsed = time.monotonic() - started
    return (
        code,
        out_path.read_text(encoding="utf-8", errors="replace"),
        err_path.read_text(encoding="utf-8", errors="replace"),
        elapsed,
    )


def run_main_bounded(env: dict[str, str], work: Path, *args: str,
                     deadline_s: float = 90.0) -> tuple[int | None, str, str, float]:
    return run_bounded([sys.executable, "main.py", *args], env, work, deadline_s)
