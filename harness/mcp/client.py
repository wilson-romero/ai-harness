"""One bounded conversation with one MCP server, run in a session process (mcp-gateway D4).

Revised on 2026-11-24 after an independent review: a server could hang the harness for good
(a regular expression in its output schema, evaluated by the SDK while holding the interpreter
lock, ignored every deadline and Ctrl+C). The SDK no longer runs in the harness process. Here,
the harness:

- starts `python -m harness.mcp.worker` in its own kill scope (process group on POSIX, Job
  Object on Windows; the SDK's helper), and the worker starts the server inside that scope;
- sends it the request, reads what it says in bounded lines, decides on the offered tools;
- measures one deadline itself, on a monotonic clock: startup + call + `CHILD_MARGIN_S`;
- always ends the whole tree when the conversation is over or the deadline passes (SIGTERM,
  2 s, SIGKILL on POSIX; the job on Windows) and records whether the tree was seen to end;
- honours Ctrl+C at any moment: the first one ends the tree and the command exits with 130.

Guaranteed bound for `mcp call` and `mcp tools`: startup + call + `GUARANTEED_EXTRA_S`
seconds, whatever the server or the session process do (measured by the tests in
`tests/integration/test_mcp_review.py`). Nothing the session process sends is printed here
without cleaning.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
import mcp_types as types
from mcp.client.stdio import _close_pipe, _create_platform_compatible_process
from mcp.client.stdio import _terminate_process_tree as _terminate_tree

from harness.mcp.config import ServerEntry
from harness.mcp.policy import Decision, matches_shape
from harness.mcp.worker import LIST_MESSAGE_LIMIT

RECURSION_MARKER = "AI_HARNESS_MCP_CHILD"
# Copied from the harness's environment when present, on every platform (a name a platform
# does not use is simply absent). The SDK's own default lists for POSIX and Windows, plus the
# variables a Windows process needs to find its system directory, its command interpreter and
# its temporary directory. Nothing else reaches a server unless its entry names it.
BASE_ENV_NAMES = (
    "HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER",
    "APPDATA", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "PATHEXT", "PROCESSOR_ARCHITECTURE",
    "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "USERNAME", "USERPROFILE",
    "TMP", "TMPDIR", "WINDIR", "COMSPEC",
)
# How the session process is started: `sys.executable` followed by these (a test replaces
# them with a stand-in that hangs).
WORKER_ARGS = ["-m", "harness.mcp.worker"]
PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # where `-m harness...` is found
# Interpreter start, the worker's own shutdown of the server (0.5 + 2 + 2 s) and slack: the
# session process normally reports well within startup + call + this.
CHILD_MARGIN_S = 10.0
# Ending the tree after the deadline: SIGTERM, 2 s, SIGKILL, up to 2 s to see it gone.
TREE_END_S = 4.0
GUARANTEED_EXTRA_S = 15.0  # CHILD_MARGIN_S + TREE_END_S, rounded up
CHANNEL_LINE_LIMIT = 32 * 1024 * 1024  # one message of the session process
EXIT_POLL_S = 0.01
TICK_S = 0.1
WORKER_EXIT_WAIT_S = 2.0  # after the outcome, for the session process to exit on its own


def build_server_env(entry: ServerEntry, environ: Mapping[str, str]) -> dict[str, str]:
    """The base names and the entry's declared names, copied from `environ`, plus the marker."""
    env: dict[str, str] = {}
    for name in (*BASE_ENV_NAMES, *entry.env):
        value = environ.get(name)
        if value is not None and not value.startswith("()"):  # never a shell function
            env[name] = value
    env[RECURSION_MARKER] = "1"
    return env


def is_mcp_child(environ: Mapping[str, str]) -> bool:
    return bool(environ.get(RECURSION_MARKER))


@dataclass(frozen=True)
class OfferedTool:
    """A tool as the server describes it. Untrusted: compared, never printed without cleaning."""

    name: str
    description: str
    input_schema: Any
    output_schema: Any = None
    annotations: Any = None


@dataclass(frozen=True)
class SessionRequest:
    entry: ServerEntry
    errlog: Path | None  # where the server's stderr goes; None: dropped
    tool: str | None = None  # None: list the tools only
    arguments: dict[str, Any] | None = None
    max_result_bytes: int = 0
    # Called with the offered tools before the call; the call is sent only if it allows it.
    check_offered: Callable[[Mapping[str, OfferedTool]], Decision] | None = None


@dataclass
class Outcome:
    phase: str = "startup"  # where it stopped: startup, list, call, shutdown, done
    offered: dict[str, OfferedTool] | None = None
    decision: Decision | None = None
    result: types.CallToolResult | None = None
    error_code: str | None = None
    fault_bytes: int | None = None
    fault_bytes_exact: bool = True
    call_bytes: int = 0
    server_stopped: bool | None = None
    interrupted: bool = False
    killed_at_deadline: bool = False  # the harness's own deadline, not a phase deadline
    stderr_bytes: int = 0  # everything the server wrote on stderr in this session
    call_sent: bool = False
    duration_ms: int = 0


class _Interrupts:
    """Ctrl+C while the session runs: the first one cancels, the others are ignored."""

    def __init__(self) -> None:
        self.pressed = False
        self._cancel: Callable[[], None] | None = None
        self._previous: Any = None
        self._installed = False

    def install(self, cancel: Callable[[], None]) -> None:
        self._cancel = cancel
        if threading.current_thread() is threading.main_thread():
            self._previous = signal.signal(signal.SIGINT, self._handle)
            self._installed = True

    def _handle(self, signum: int, frame: object) -> None:
        if not self.pressed and self._cancel is not None:
            self.pressed = True
            self._cancel()

    def restore(self) -> None:
        if self._installed:
            signal.signal(signal.SIGINT, self._previous)
            self._installed = False


def run_session(request: SessionRequest, environ: Mapping[str, str]) -> Outcome:
    """Run the conversation in a session process; return within the bound, whatever happens.

    Raises KeyboardInterrupt after the tree is ended, if the person interrupted (the outcome
    is attached to the exception as `.outcome`).
    """
    logging.getLogger("mcp").setLevel(logging.CRITICAL + 1)
    started = time.monotonic()
    interrupts = _Interrupts()
    try:
        outcome = anyio.run(_supervise, request, dict(environ), started, interrupts,
                            backend="asyncio")
    finally:
        interrupts.restore()
    outcome.duration_ms = int((time.monotonic() - started) * 1000)
    if interrupts.pressed:
        outcome.interrupted = True
        outcome.error_code = "interrupted"
        error = KeyboardInterrupt()
        error.outcome = outcome  # type: ignore[attr-defined]
        raise error
    return outcome


async def _supervise(
    request: SessionRequest, environ: dict[str, str], started: float, interrupts: _Interrupts
) -> Outcome:
    entry = request.entry
    outcome = Outcome()
    budget = entry.startup_timeout_s + (entry.call_timeout_s if request.tool else 0)
    deadline = anyio.current_time() + budget + CHILD_MARGIN_S - (time.monotonic() - started)
    loop = _running_loop()
    with anyio.CancelScope(deadline=deadline) as scope:
        interrupts.install(lambda: loop.call_soon_threadsafe(scope.cancel))
        devnull = open(os.devnull, "w")  # noqa: SIM115 - the session process's own stderr
        try:
            process = await _create_platform_compatible_process(
                command=sys.executable, args=list(WORKER_ARGS), env=environ, errlog=devnull,
                cwd=PACKAGE_ROOT,
            )
        except OSError:
            devnull.close()
            outcome.error_code = "internal_error"
            return outcome
        try:
            async with anyio.create_task_group() as group:
                group.start_soon(_tick)
                await _guarded(_converse(process, request, environ, outcome), outcome)
                group.cancel_scope.cancel()
        finally:
            with anyio.CancelScope(shield=True):
                outcome.server_stopped = await _end_tree(process)
            devnull.close()
            # Inside the loop: the event loop's runner restores its own handler when it ends.
            interrupts.restore()
    if interrupts.pressed:
        outcome.error_code = "interrupted"
        outcome.result = None
    elif scope.cancelled_caught:
        outcome.error_code = "timeout"
        outcome.killed_at_deadline = True
        outcome.result = None
    return outcome


async def _tick() -> None:
    """Wake the loop often: a Python signal handler (Ctrl+C) only runs when the main thread
    runs Python code, and an event loop waiting for I/O may not be woken by the signal (on
    Windows it never is)."""
    while True:
        await anyio.sleep(TICK_S)


async def _guarded(conversation: Any, outcome: Outcome) -> None:
    try:
        await conversation
    except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError,
            anyio.EndOfStream, ValueError):
        if outcome.error_code is None:
            outcome.error_code = "internal_error"


async def _converse(
    process: Any, request: SessionRequest, environ: Mapping[str, str], outcome: Outcome
) -> None:
    entry = request.entry
    lines = _Lines(process.stdout)
    await _send(process, {
        "command": list(entry.command),
        "env": build_server_env(entry, environ),
        "cwd": entry.cwd or os.getcwd(),
        "startup_timeout_s": entry.startup_timeout_s,
        "call_timeout_s": entry.call_timeout_s if request.tool else 0,
        "tool": request.tool,
        "arguments": request.arguments,
        "max_result_bytes": request.max_result_bytes,
        "errlog": str(request.errlog) if request.errlog is not None else None,
    })
    message = await lines.next()
    if message.get("event") == "offered":
        outcome.phase = "list"
        outcome.offered = _offered(message.get("tools"))
        if request.tool is not None and request.check_offered is not None:
            outcome.decision = request.check_offered(outcome.offered)
            go = outcome.decision.allowed
            if go:
                outcome.phase = "call"
                outcome.call_sent = True
            await _send(process, {"go": go})
        message = await lines.next()
    if message.get("event") != "outcome":
        outcome.error_code = "internal_error"
        return
    _absorb(message, outcome, request)
    await _let_it_exit(process)


async def _let_it_exit(process: Any) -> None:
    """After its outcome the session process ends by itself (its exit handlers run); give it
    a moment before the tree is ended, never past the command's own deadline."""
    with anyio.CancelScope() as scope:
        remaining = anyio.current_effective_deadline() - anyio.current_time()
        scope.deadline = anyio.current_time() + min(WORKER_EXIT_WAIT_S, remaining - 0.1)
        while process.returncode is None:
            await anyio.sleep(EXIT_POLL_S)


def _absorb(message: dict[str, Any], outcome: Outcome, request: SessionRequest) -> None:
    phase = message.get("phase")
    if isinstance(phase, str) and phase in ("startup", "list", "call", "shutdown", "done"):
        outcome.phase = phase
    code = message.get("error_code")
    outcome.error_code = code if isinstance(code, str) and code.isidentifier() else None
    if code is not None and outcome.error_code is None:
        outcome.error_code = "internal_error"
    outcome.fault_bytes = _int(message.get("fault_bytes"))
    outcome.fault_bytes_exact = message.get("fault_bytes_exact") is not False
    outcome.call_bytes = _int(message.get("call_bytes")) or 0
    outcome.stderr_bytes = _int(message.get("stderr_bytes")) or 0
    raw = message.get("result")
    if outcome.error_code is None and raw is not None:
        try:
            result = types.CallToolResult.model_validate(raw)
        except ValueError:
            outcome.error_code = "invalid_result"
            return
        if not result.is_error and not _shape_ok(result, outcome, request):
            outcome.error_code = "invalid_result"
            return
        outcome.result = result


def _shape_ok(result: types.CallToolResult, outcome: Outcome, request: SessionRequest) -> bool:
    """The harness's own check of a structured result against the tool's output schema: types,
    `required`, `properties`, `items`, `additionalProperties: false` only; never a pattern."""
    tool = (outcome.offered or {}).get(request.tool or "")
    schema = tool.output_schema if tool is not None else None
    if not isinstance(schema, dict):
        return True
    if result.structured_content is None:
        return False  # a tool with an output schema must return structured content
    return matches_shape(schema, result.structured_content)


def _offered(raw: Any) -> dict[str, OfferedTool]:
    offered: dict[str, OfferedTool] = {}
    if not isinstance(raw, dict):
        return offered
    for name, tool in raw.items():
        if not isinstance(name, str) or not isinstance(tool, dict):
            continue
        description = tool.get("description")
        offered[name] = OfferedTool(
            name, description if isinstance(description, str) else "",
            tool.get("input_schema"), tool.get("output_schema"), tool.get("annotations"),
        )
    return offered


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


async def _send(process: Any, message: dict[str, Any]) -> None:
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    await process.stdin.send(data + b"\n")


class _Lines:
    """Bounded JSON lines from the session process."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._buffer = bytearray()
        self._scanned = 0

    async def next(self) -> dict[str, Any]:
        while (newline := self._buffer.find(b"\n", self._scanned)) < 0:
            self._scanned = len(self._buffer)
            if len(self._buffer) > CHANNEL_LINE_LIMIT:
                raise ValueError("message too large")
            self._buffer += await self._stream.receive()
        line = bytes(self._buffer[:newline])
        del self._buffer[: newline + 1]
        self._scanned = 0
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("not an object")
        return value


async def _end_tree(process: Any) -> bool:
    """End the session process and everything in its kill scope; True if seen to end."""
    await _close_pipe(process.stdin)
    await _terminate_tree(process)
    with anyio.move_on_after(TREE_END_S / 2):
        while process.returncode is None:
            await anyio.sleep(EXIT_POLL_S)
    stopped = process.returncode is not None
    if stopped and hasattr(os, "killpg"):
        # POSIX: the group is gone only once every member is (the SDK's own probe).
        from mcp.os.posix.utilities import _group_alive

        with anyio.move_on_after(TREE_END_S / 2):
            while _group_alive(process.pid):
                await anyio.sleep(EXIT_POLL_S)
        stopped = not _group_alive(process.pid)
    from mcp.os.win32.utilities import close_process_job

    close_process_job(process)
    await _close_pipe(process.stdout)
    transport = getattr(getattr(process, "_process", None), "_transport", None)
    if callable(getattr(transport, "close", None)):
        transport.close()
    return stopped


def _running_loop() -> Any:
    import asyncio

    return asyncio.get_running_loop()


def session_budget_s(entry: ServerEntry, with_call: bool) -> float:
    """The longest a session can take, by construction (what the tests measure against)."""
    return entry.startup_timeout_s + (entry.call_timeout_s if with_call else 0) + \
        GUARANTEED_EXTRA_S
