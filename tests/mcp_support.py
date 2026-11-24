"""Helpers for the MCP tests: synthetic allowlists, bounded process runs, liveness checks.

Liveness is checked without any platform branch and without signals (`os.kill(pid, 0)` would
kill the process on Windows): the synthetic server rewrites a heartbeat file every 100 ms
while it lives, so a heartbeat that stops changing means the process is gone.
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

    def _beat(self) -> str | None:
        try:
            return (self.state / "heartbeat").read_text(encoding="utf-8")
        except OSError:
            return None

    def stopped(self, within_s: float = 3.0) -> bool:
        """True once the heartbeat has not changed for 0.5 s, if that happens within the bound."""
        if not self.started:
            return True
        deadline = time.monotonic() + within_s
        previous = self._beat()
        while time.monotonic() < deadline:
            time.sleep(0.5)
            current = self._beat()
            if current == previous:
                return True
            previous = current
        return False

    def alive(self) -> bool:
        return self.started and not self.stopped(within_s=1.2)


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
