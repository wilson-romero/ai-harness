"""The session process: one bounded conversation with one MCP server (mcp-gateway D4, D8).

Run by the harness as `python -m harness.mcp.worker` (revised design D4, 2026-11-24). It holds
the SDK and talks to the server; the harness process keeps the policy, the audit row and the
final say, and kills this process and everything it started at its own deadline. Nothing here
has to cooperate for the harness to end on time.

Protocol, one JSON object per line:
1. harness -> here: the request (command, environment, timeouts, tool, arguments, limits).
2. here -> harness: `{"event": "offered", "tools": {...}}` after `tools/list`.
3. harness -> here: `{"go": true}` to send the one `tools/call`, anything else to stop.
4. here -> harness: `{"event": "outcome", ...}`; then this process exits.

The SDK never validates a result against a schema the server sent: the call goes through
`send_request`, not `call_tool`, so no server-supplied pattern or format is ever evaluated
(independent review of 2026-11-24, finding 1). Nothing this process writes to the harness is
ever printed by it without cleaning; its own stderr goes to the null device.
"""

from __future__ import annotations

import atexit
import faulthandler
import json
import logging
import math
import os
import sys
from typing import Any

import anyio
import anyio.to_thread
import mcp_types as types
from mcp import Client, Implementation, MCPError
from pydantic import ValidationError

from harness.mcp.transport import TransportState, bounded_stdio

LIST_MESSAGE_LIMIT = 1024 * 1024  # handshake and tool listing: bytes per message
MAX_LIST_PAGES = 10
MAX_TOOLS = 1000
MAX_REQUEST_BYTES = 1024 * 1024
# The process ends itself this long after its own budget, even if its event loop is stuck:
# faulthandler's timer runs in a C thread that needs no interpreter lock.
SELF_DESTRUCT_EXTRA_S = 15.0
CLIENT_INFO = Implementation(name="ai-harness", version="0.1.0")


class _Channel:
    """The lines to and from the harness (stdin and a private copy of stdout)."""

    def __init__(self) -> None:
        self._out = os.fdopen(os.dup(1), "wb", buffering=0)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)  # nothing printed by a library can reach the harness's channel
        os.close(devnull)
        self._in = sys.stdin.buffer

    def read(self) -> dict[str, Any] | None:
        line = self._in.readline(MAX_REQUEST_BYTES + 1)
        if not line or len(line) > MAX_REQUEST_BYTES:
            return None
        try:
            value = json.loads(line)
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def send(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            self._out.write(data + b"\n")
        except OSError:
            pass


def main() -> None:
    for name in ("mcp", "mcp_types"):  # records can quote what a server sent
        logging.getLogger(name).setLevel(logging.CRITICAL + 1)
    channel = _Channel()
    request = channel.read()
    if request is None:
        os._exit(2)
    budget = float(request["startup_timeout_s"]) + float(request.get("call_timeout_s") or 0)
    devnull = open(os.devnull, "w")  # noqa: SIM115 - kept open until the process ends
    faulthandler.dump_traceback_later(budget + SELF_DESTRUCT_EXTRA_S, exit=True, file=devnull)
    try:
        outcome = anyio.run(_converse, request, channel, backend="asyncio")
    except BaseException:  # noqa: BLE001 - never printed: it may quote what the server sent
        outcome = {"error_code": "internal_error", "phase": "startup"}
    channel.send({"event": "outcome", **outcome})
    atexit._run_exitfuncs()  # what a normal exit runs; then no wait for the thread that is
    os._exit(0)  # still blocked reading the harness's stdin


async def _converse(request: dict[str, Any], channel: _Channel) -> dict[str, Any]:
    outcome: dict[str, Any] = {"phase": "startup", "error_code": None, "error_origin": None}
    state = TransportState(limit=LIST_MESSAGE_LIMIT)
    with anyio.CancelScope() as scope:
        state.on_fault = scope.cancel
        try:
            await _talk(request, channel, state, outcome, scope)
        except Exception as exc:  # noqa: BLE001 - classified, never printed
            outcome["error_code"] = classify(exc, outcome["phase"], state)
    if state.fault == "stderr_too_large" and "result" in outcome:
        # The result was complete before the cap was passed: it stands. The server was stopped
        # all the same, and the harness warns that its stderr was cut (D4, revised 2026-11-25).
        pass
    elif state.fault is not None:
        outcome["error_code"] = state.fault
        outcome["fault_bytes"] = state.fault_bytes
        outcome["fault_bytes_exact"] = state.fault_bytes_exact
    elif scope.cancel_called and outcome["error_code"] is None:
        outcome["error_code"] = "interrupted"  # the harness went away
    outcome["call_bytes"] = state.call_bytes
    outcome["server_stopped"] = state.server_stopped
    outcome["stderr_bytes"] = state.stderr_bytes
    if outcome["error_code"] is None and outcome["phase"] == "shutdown":
        outcome["phase"] = "done"
    return outcome


async def _talk(
    request: dict[str, Any],
    channel: _Channel,
    state: TransportState,
    outcome: dict[str, Any],
    outer: anyio.CancelScope,
) -> None:
    startup = float(request["startup_timeout_s"])
    call_timeout = float(request.get("call_timeout_s") or 0)
    errlog = _open_errlog(request.get("errlog"))
    try:
        with anyio.CancelScope(deadline=anyio.current_time() + startup) as phase:
            transport = bounded_stdio(
                list(request["command"]), dict(request["env"]), request.get("cwd"), errlog, state
            )
            # No sampling, elicitation or roots callbacks: the harness offers none, and the SDK
            # answers a server's request for one with an error (D8). No response cache.
            client = Client(transport, mode="legacy", cache=None, client_info=CLIENT_INFO)
            async with client:
                outcome["phase"] = "list"
                channel.send({"event": "offered", "tools": await _list_tools(client)})
                if request.get("tool") is None:
                    outcome["phase"] = "shutdown"
                    return
                answer = await anyio.to_thread.run_sync(channel.read, abandon_on_cancel=True)
                if not answer or answer.get("go") is not True:
                    outcome["phase"] = "shutdown"
                    return
                async with anyio.create_task_group() as watch:
                    # If the harness goes away, its end of the pipe closes: stop at once.
                    watch.start_soon(_cancel_when_closed, channel, outer)
                    outcome["phase"] = state.phase = "call"
                    state.limit = int(request["max_result_bytes"])
                    phase.deadline = anyio.current_time() + call_timeout
                    outcome["call_sent"] = True
                    # Exactly one tools/call request, and no validation of the result by the
                    # SDK (no `call_tool`): the harness checks the shape itself.
                    result = await client.session.send_request(
                        types.CallToolRequest(params=types.CallToolRequestParams(
                            name=request["tool"], arguments=request.get("arguments"),
                        )),
                        types.CallToolResult,
                        request_read_timeout_seconds=call_timeout,
                    )
                    watch.cancel_scope.cancel()
                outcome["result"] = result.model_dump(mode="json", by_alias=True,
                                                      exclude_none=True)
                outcome["phase"] = state.phase = "shutdown"
                phase.deadline = math.inf
        if phase.cancelled_caught:
            raise TimeoutError  # classified as `timeout`; the phase is in the outcome
    finally:
        if errlog is not None:
            os.close(errlog)


async def _cancel_when_closed(channel: _Channel, scope: anyio.CancelScope) -> None:
    await anyio.to_thread.run_sync(channel.read, abandon_on_cancel=True)
    scope.cancel()


async def _list_tools(client: Client) -> dict[str, dict[str, Any]]:
    offered: dict[str, dict[str, Any]] = {}
    cursor: str | None = None
    for _ in range(MAX_LIST_PAGES):
        page = await client.list_tools(cursor=cursor)
        for tool in page.tools:
            if len(offered) >= MAX_TOOLS:
                return offered
            annotations = (tool.annotations.model_dump(mode="json", by_alias=True,
                                                       exclude_none=True)
                           if tool.annotations is not None else None)
            offered.setdefault(tool.name, {
                "description": tool.description or "",
                "input_schema": tool.input_schema,
                "output_schema": tool.output_schema,
                "annotations": annotations,
            })
        cursor = page.next_cursor
        if cursor is None:
            break
    return offered


def _open_errlog(path: str | None) -> int | None:
    """The server's log, appended to; created readable by its owner only. None: dropped."""
    if not path:
        return None
    try:
        # O_BINARY: the log keeps the server's exact bytes, also on Windows.
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
        return os.open(path, flags, 0o600)
    except OSError:
        return None


def classify(exc: BaseException, phase: str, state: TransportState | None = None) -> str:
    """An error code for an exception from the SDK or the transport. Its text is never used.

    An `MCPError` is the server's own error reply only if the server sent one (the transport
    counted it); otherwise the SDK made it up, for a connection that closed (finding 8).
    """
    leaves = list(_leaves(exc))
    if any(isinstance(leaf, TimeoutError) for leaf in leaves):
        return "timeout"
    for leaf in leaves:
        if isinstance(leaf, MCPError):
            if state is not None and state.error_replies:
                return "server_error"
            return "server_exited" if leaf.code == types.CONNECTION_CLOSED else "protocol_error"
    for leaf in leaves:
        if isinstance(leaf, (anyio.EndOfStream, anyio.ClosedResourceError,
                             anyio.BrokenResourceError, BrokenPipeError, ConnectionError)):
            return "server_exited"
    for leaf in leaves:
        if isinstance(leaf, OSError) and phase == "startup":
            return "spawn_failed"
    for leaf in leaves:
        if isinstance(leaf, ValidationError):
            return "invalid_result" if phase == "call" else "protocol_error"
        if isinstance(leaf, RuntimeError):
            return "protocol_error"
    return "internal_error"


def _leaves(exc: BaseException):
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            yield from _leaves(inner)
    else:
        yield exc
        if exc.__cause__ is not None:
            yield from _leaves(exc.__cause__)


if __name__ == "__main__":
    main()
