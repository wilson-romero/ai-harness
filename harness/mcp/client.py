"""One bounded conversation with one MCP server (mcp-gateway D3, D4, D8).

The whole conversation (start, handshake, `list_tools`, at most one `call_tool`, shutdown) runs
in a worker thread with its own event loop. The main thread only waits, in short slices, up to
a deadline it measures itself with a monotonic clock. Inside, every phase has its own deadline;
the shutdown is the SDK's (close stdin, 2 s, kill the process tree, every wait bounded). If the
worker has still not returned at the command's deadline, the main thread asks it to cancel; if
it has not returned a few seconds later, the session is abandoned and the caller ends the
process. No wait in this module depends on the server cooperating.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import threading
import time
from collections.abc import Callable, Mapping

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
import mcp_types as types
from mcp import Client, Implementation, MCPError
from pydantic import ValidationError

from harness.mcp.config import ServerEntry
from harness.mcp.policy import Decision
from harness.mcp.transport import TransportState, bounded_stdio

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
LIST_MESSAGE_LIMIT = 1024 * 1024  # handshake and tool listing: bytes per message
MAX_LIST_PAGES = 10
MAX_TOOLS = 1000
CANCEL_MARGIN_S = 15.0  # after startup + call: ask the worker to cancel
ABANDON_MARGIN_S = 20.0  # after startup + call: give up on the worker
INTERRUPT_GRACE_S = 15.0  # after Ctrl+C: time for the shutdown to finish
WAIT_SLICE_S = 0.1
CLIENT_INFO = Implementation(name="ai-harness", version="0.1.0")


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


@dataclass(frozen=True)
class SessionRequest:
    entry: ServerEntry
    errlog: Path | None  # where the server's stderr goes; None: the null device
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
    abandoned: bool = False
    call_sent: bool = False
    duration_ms: int = 0


class _Control:
    """Lets the main thread cancel the worker's conversation, at any moment, from outside."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._scope: anyio.CancelScope | None = None
        self.reason: str | None = None

    def attach(self, loop: asyncio.AbstractEventLoop, scope: anyio.CancelScope) -> None:
        with self._lock:
            self._loop, self._scope = loop, scope
            if self.reason is not None:
                scope.cancel()

    def cancel(self, reason: str) -> None:
        with self._lock:
            if self.reason is None:
                self.reason = reason
            if self._loop is not None and self._scope is not None:
                try:
                    self._loop.call_soon_threadsafe(self._scope.cancel)
                except RuntimeError:
                    pass  # the loop already ended


def run_session(request: SessionRequest, environ: Mapping[str, str]) -> Outcome:
    """Run the conversation in a worker thread; return within the deadline, whatever happens.

    Raises KeyboardInterrupt after the shutdown, if the person interrupted (the outcome is
    attached to the exception as `.outcome`).
    """
    _silence_sdk_logs()
    entry = request.entry
    control = _Control()
    env = build_server_env(entry, environ)
    box: list[Outcome] = []
    started = time.monotonic()

    def worker() -> None:
        try:
            box.append(anyio.run(_converse, request, env, control, backend="asyncio"))
        except BaseException:  # never printed: it may quote what the server sent
            box.append(Outcome(error_code="internal_error"))

    thread = threading.Thread(target=worker, name="mcp-session", daemon=True)
    thread.start()
    budget = entry.startup_timeout_s + (entry.call_timeout_s if request.tool else 0)
    interrupted = False
    try:
        _join(thread, started + budget + CANCEL_MARGIN_S)
    except KeyboardInterrupt:
        interrupted = True
        control.cancel("interrupted")
        _join_ignoring_interrupts(thread, time.monotonic() + INTERRUPT_GRACE_S)
    if thread.is_alive() and not interrupted:
        control.cancel("timeout")
        _join_ignoring_interrupts(thread, started + budget + ABANDON_MARGIN_S)
    if thread.is_alive():
        outcome = Outcome(error_code="abandoned", abandoned=True)
    else:
        outcome = box[0]
    outcome.interrupted = interrupted
    outcome.duration_ms = int((time.monotonic() - started) * 1000)
    if interrupted:
        error = KeyboardInterrupt()
        error.outcome = outcome  # type: ignore[attr-defined]
        raise error
    return outcome


def _join(thread: threading.Thread, deadline: float) -> None:
    while thread.is_alive() and (remaining := deadline - time.monotonic()) > 0:
        thread.join(timeout=min(WAIT_SLICE_S, remaining))


def _join_ignoring_interrupts(thread: threading.Thread, deadline: float) -> None:
    while thread.is_alive() and time.monotonic() < deadline:
        try:
            _join(thread, deadline)
        except KeyboardInterrupt:
            continue  # a second Ctrl+C does not skip the bounded shutdown


def _silence_sdk_logs() -> None:
    # The SDK's log records can quote what a server sent; Python's last-resort handler would
    # print them unsanitised on stderr.
    for name in ("mcp", "mcp_types"):
        logging.getLogger(name).setLevel(logging.CRITICAL + 1)


async def _converse(
    request: SessionRequest, env: dict[str, str], control: _Control
) -> Outcome:
    outcome = Outcome()
    state = TransportState(limit=LIST_MESSAGE_LIMIT)
    with anyio.CancelScope() as scope:
        state.on_fault = scope.cancel
        control.attach(asyncio.get_running_loop(), scope)
        try:
            await _talk(request, env, state, outcome)
        except Exception as exc:  # noqa: BLE001 - classified, never printed
            outcome.error_code = _classify(exc, outcome.phase)
    if state.fault is not None:
        outcome.error_code = state.fault
        outcome.fault_bytes, outcome.fault_bytes_exact = state.fault_bytes, state.fault_bytes_exact
    elif scope.cancel_called:
        # Only the main thread (interrupt, deadline) or a fault cancels this scope.
        outcome.error_code = control.reason or outcome.error_code or "interrupted"
    outcome.call_bytes = state.call_bytes
    outcome.server_stopped = state.server_stopped
    if outcome.error_code is None and outcome.phase == "shutdown":
        outcome.phase = "done"
    return outcome


async def _talk(
    request: SessionRequest, env: dict[str, str], state: TransportState, outcome: Outcome
) -> None:
    entry = request.entry
    # One scope for the whole session whose deadline moves from phase to phase: the client's
    # task group must be entered and left inside the same scope. The shutdown is shielded.
    with anyio.CancelScope(deadline=anyio.current_time() + entry.startup_timeout_s) as phase:
        with _open_errlog(request.errlog) as errlog:
            transport = bounded_stdio(list(entry.command), env, entry.cwd, errlog, state)
            # No sampling, elicitation or roots callbacks: the harness offers none, and the SDK
            # answers a server's request for one with an error (D8). No response cache.
            client = Client(transport, mode="legacy", cache=None, client_info=CLIENT_INFO)
            async with client:
                outcome.phase = "list"
                outcome.offered = await _list_tools(client)
                if request.tool is None or request.check_offered is None:
                    outcome.phase = "shutdown"
                    return
                outcome.decision = request.check_offered(outcome.offered)
                if not outcome.decision.allowed:
                    outcome.phase = "shutdown"
                    return
                outcome.phase = state.phase = "call"
                state.limit = request.max_result_bytes
                phase.deadline = anyio.current_time() + entry.call_timeout_s
                outcome.call_sent = True
                # The session's call_tool, not the Client's: the Client's re-sends the call by
                # itself (input-required rounds, a re-list after a header mismatch). Exactly
                # one tools/call request leaves here.
                outcome.result = await client.session.call_tool(
                    request.tool, request.arguments, read_timeout_seconds=entry.call_timeout_s
                )
                outcome.phase = state.phase = "shutdown"
                phase.deadline = math.inf
    if phase.cancelled_caught:
        raise TimeoutError  # classified as `timeout`; outcome.phase names the phase


async def _list_tools(client: Client) -> dict[str, OfferedTool]:
    offered: dict[str, OfferedTool] = {}
    cursor: str | None = None
    for _ in range(MAX_LIST_PAGES):
        page = await client.list_tools(cursor=cursor)
        for tool in page.tools:
            if len(offered) >= MAX_TOOLS:
                return offered
            offered.setdefault(
                tool.name, OfferedTool(tool.name, tool.description or "", tool.input_schema)
            )
        cursor = page.next_cursor
        if cursor is None:
            break
    return offered


class _open_errlog:  # noqa: N801 - a context manager used like a function
    """The server's stderr goes to its own log file, never to the harness's terminal."""

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._handle: Any = None

    def __enter__(self) -> Any:
        if self._path is not None:
            try:
                self._handle = self._path.open("a", encoding="utf-8")
            except OSError:
                self._handle = None
        if self._handle is None:
            self._handle = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
        return self._handle

    def __exit__(self, *exc_info: object) -> None:
        self._handle.close()


def _classify(exc: BaseException, phase: str) -> str:
    """An error code for an exception from the SDK or the transport. Its text is never used."""
    leaves = list(_leaves(exc))
    if any(isinstance(leaf, TimeoutError) for leaf in leaves):
        return "timeout"
    for leaf in leaves:
        if isinstance(leaf, MCPError):
            return "server_exited" if leaf.code == types.CONNECTION_CLOSED else "protocol_error"
    for leaf in leaves:
        if isinstance(leaf, (anyio.EndOfStream, anyio.ClosedResourceError,
                             anyio.BrokenResourceError, BrokenPipeError, ConnectionError)):
            return "server_exited"
    for leaf in leaves:
        if isinstance(leaf, OSError) and phase == "startup":
            return "spawn_failed"
    for leaf in leaves:
        if isinstance(leaf, RuntimeError) and _is_schema_failure(leaf):
            return "invalid_result"
        if isinstance(leaf, ValidationError):
            return "invalid_result" if phase == "call" else "protocol_error"
        if isinstance(leaf, RuntimeError):
            return "protocol_error"
    return "internal_error"


def _is_schema_failure(exc: RuntimeError) -> bool:
    # The SDK's two messages for a structured result that breaks the tool's output schema
    # (mcp 2.3.0, ClientSession.validate_tool_result). Only the prefix is compared.
    text = str(exc.args[0]) if exc.args else ""
    return text.startswith("Invalid structured content") or "has an output schema" in text[:200]


def _leaves(exc: BaseException):
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            yield from _leaves(inner)
    else:
        yield exc
        if exc.__cause__ is not None:
            yield from _leaves(exc.__cause__)
