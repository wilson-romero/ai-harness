"""`mcp list`, `mcp tools` and `mcp call` (mcp-gateway D10).

Results go to stdout; denials, errors, warnings and the one-line summary go to stderr. Exit
codes: 0 completed, 1 denied or failed, 2 misuse of `--args`, 130 interrupted.

Every line of a tool's own text (its result on stdout, its error message on stderr) is printed
after `RESULT_PREFIX` ("| "; an empty line is "|"), so that nothing a tool returns can pass for
a line of the harness (independent review of 2026-11-24, finding 7).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from harness.config import Settings
from harness.core.errors import HarnessError
from harness.mcp.audit import (
    CallRow,
    args_key,
    call_lock,
    forget_lock,
    new_call_id,
    record_denied,
    record_denied_after_listing,
    record_finished,
    record_running,
    recover_stale,
)
from harness.mcp.config import LoadedConfig, ServerEntry, load_config
from harness.mcp.policy import (
    USAGE_REASONS,
    Decision,
    decide_before_start,
    decide_offered,
    parse_arguments,
)
from harness.storage.database import open_database
from harness.text.safe_text import safe_foreign_line

if TYPE_CHECKING:
    from harness.mcp.client import OfferedTool, Outcome

# The SDK (and with it web-server modules it imports) is loaded only by `mcp tools` and
# `mcp call`, not by every command of the harness.
RECURSION_MARKER = "AI_HARNESS_MCP_CHILD"  # the same name as client.RECURSION_MARKER

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
LOG_ROTATE_BYTES = 1024 * 1024
RESULT_PREFIX = "| "


class RecursionRefused(HarnessError):
    pass


def add_mcp_parser(commands: argparse._SubParsersAction) -> None:
    mcp = commands.add_parser("mcp", help="use tools of the allowlisted local MCP servers")
    mcp_commands = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_commands.add_parser("list", help="list the allowlisted servers and tools (starts nothing)")
    tools = mcp_commands.add_parser("tools", help="start a server, list its tools, stop it")
    tools.add_argument("server")
    call = mcp_commands.add_parser("call", help="call one allowed read tool, once")
    call.add_argument("server")
    call.add_argument("tool")
    call.add_argument("--args", default="{}", help="the tool's arguments as a JSON object")


def run_mcp_command(args: argparse.Namespace, environ: Mapping[str, str] | None = None) -> int:
    environ = os.environ if environ is None else environ
    if environ.get(RECURSION_MARKER):
        # Before anything is read: a process started by the MCP client cannot use it (D8).
        raise RecursionRefused(
            "recursion: this process was started by the harness's MCP client and cannot use it"
        )
    config = load_config(environ)
    if args.mcp_command == "list":
        return _list(config)
    settings = Settings.from_env(environ)
    if args.mcp_command == "tools":
        return _tools(config, args.server, settings.data_dir, environ)
    return _call(config, args.server, args.tool, args.args, settings.data_dir, environ)


# -- list --------------------------------------------------------------------------------------


def _list(config: LoadedConfig) -> int:
    if not config.servers:
        print("No MCP servers configured.")
        return EXIT_OK
    for name in sorted(config.servers):
        entry = config.servers[name]
        print(f"{name}\texternal\t{len(entry.tools)} tool(s)")  # never the command or a path
        for tool in sorted(entry.tools):
            print(f"  {tool}\t{entry.tools[tool].operation}")
    return EXIT_OK


# -- tools -------------------------------------------------------------------------------------


def _tools(config: LoadedConfig, server: str, data_dir: Path, environ: Mapping[str, str]) -> int:
    entry = config.servers.get(server)
    if entry is None:
        print(f"error: denied: server_not_allowed: server {_shown(server)} is not allowed",
              file=sys.stderr)
        return EXIT_ERROR
    from harness.mcp.client import SessionRequest, run_session

    outcome = run_session(SessionRequest(entry, _server_log(data_dir, server)), environ)
    _warn_if_alive(outcome)
    if outcome.error_code is not None or outcome.offered is None:
        print(f"error: {_explain(outcome, entry, None)}", file=sys.stderr)
        return EXIT_ERROR
    offered = outcome.offered
    for name in sorted(set(entry.tools) | set(offered)):
        print("\t".join(_tool_line(entry, name, offered)))
    print(f"tools: {server}, {len(offered)} offered by the server, {len(entry.tools)} declared",
          file=sys.stderr)
    return EXIT_OK


def _tool_line(entry: ServerEntry, name: str, offered: Mapping[str, OfferedTool]) -> list[str]:
    from harness.mcp.render import clean_description, clean_name

    declared = entry.tools.get(name)
    tool = offered.get(name)
    description = clean_description(tool.description) if tool is not None else ""
    if declared is None:
        return [clean_name(name), "-", "denied:tool_not_allowed", description]
    if tool is None:
        return [name, declared.operation, "absent", ""]
    decision = decide_offered(declared, tool.input_schema, name, tool.annotations)
    if not decision.allowed:
        status = f"denied:{decision.reason}"
    elif declared.operation != "read":
        status = "denied:write_requires_approval"
    else:
        status = "allowed"
    return [name, declared.operation, status, description]


# -- call --------------------------------------------------------------------------------------


def _call(
    config: LoadedConfig,
    server: str,
    tool: str,
    raw_args: str,
    data_dir: Path,
    environ: Mapping[str, str],
) -> int:
    from harness.mcp.client import Outcome, SessionRequest, run_session

    parsed = parse_arguments(raw_args)
    conn = open_database(data_dir)
    try:
        key = args_key(data_dir)
        recover_stale(conn, data_dir)
        decision = decide_before_start(config, server, tool, parsed)
        if not decision.allowed:
            record_denied(conn, server, tool, decision.reason, decision.operation,
                          parsed.canonical, parsed.size, key)
            _print_denied(decision)
            return EXIT_USAGE if decision.reason in USAGE_REASONS else EXIT_ERROR
        entry = config.servers[server]
        declared = entry.tools[tool]
        call_id = new_call_id()
        lock = call_lock(data_dir, call_id)
        lock.acquire()  # a new name: nobody else can hold it
        try:
            row = record_running(conn, call_id, server, tool, declared.operation,
                                 parsed.canonical, key)

            def check(offered: Mapping[str, OfferedTool]) -> Decision:
                found = offered.get(tool)
                if found is None:
                    return decide_offered(declared, None, tool)
                return decide_offered(declared, found.input_schema, tool, found.annotations)

            request = SessionRequest(
                entry, _server_log(data_dir, server), tool, parsed.value,
                declared.max_result_bytes, check,
            )
            try:
                outcome = run_session(request, environ)
            except KeyboardInterrupt as interrupt:
                outcome = getattr(interrupt, "outcome", Outcome(error_code="interrupted"))
                record_finished(conn, row, "failed", "interrupted", outcome.server_stopped,
                                None, outcome.duration_ms)
                _warn_if_alive(outcome)
                raise
            return _finish(conn, row, server, tool, entry, declared.max_result_bytes, outcome)
        finally:
            lock.release()
            forget_lock(data_dir, call_id)
    finally:
        conn.close()


def _finish(
    conn: sqlite3.Connection,
    row: CallRow,
    server: str,
    tool: str,
    entry: ServerEntry,
    limit: int,
    outcome: Outcome,
) -> int:
    from harness.mcp.render import render_error, render_result

    _warn_if_alive(outcome)
    if outcome.decision is not None and not outcome.decision.allowed:
        record_denied_after_listing(conn, row, outcome.decision.reason, outcome.server_stopped,
                                    outcome.duration_ms)
        _print_denied(outcome.decision)
        return EXIT_ERROR
    result = outcome.result
    if outcome.error_code is not None or result is None:
        code = outcome.error_code or "internal_error"
        status = "timeout" if code == "timeout" else "failed"
        record_finished(conn, row, status, code, outcome.server_stopped, outcome.call_bytes or None,
                        outcome.duration_ms)
        print(f"error: {_explain(outcome, entry, limit)}", file=sys.stderr)
        _summary(server, tool, status, outcome, 0)
        return EXIT_ERROR
    if result.is_error:
        message = render_error(result)
        record_finished(conn, row, "failed", "tool_error", outcome.server_stopped,
                        outcome.call_bytes, outcome.duration_ms)
        print("error: the tool reported an error:", file=sys.stderr)
        print(prefixed(message.text), file=sys.stderr)
        _summary(server, tool, "failed", outcome, message.redactions)
        return EXIT_ERROR
    rendered = render_result(result)
    record_finished(conn, row, "completed", None, outcome.server_stopped, outcome.call_bytes,
                    outcome.duration_ms)
    print(prefixed(rendered.text))
    _summary(server, tool, "completed", outcome, rendered.redactions)
    return EXIT_OK


def prefixed(text: str) -> str:
    """Every line of a tool's text after `RESULT_PREFIX` (an empty line: the bare bar)."""
    bare = RESULT_PREFIX.rstrip()
    return "\n".join(RESULT_PREFIX + line if line else bare for line in text.split("\n"))


# -- messages ----------------------------------------------------------------------------------


def _print_denied(decision: Decision) -> None:
    detail = f": {decision.detail}" if decision.detail else ""
    print(f"error: denied: {decision.reason}{detail}", file=sys.stderr)


def _explain(outcome: Outcome, entry: ServerEntry, limit: int | None) -> str:
    from harness.mcp.client import LIST_MESSAGE_LIMIT

    code = outcome.error_code
    phase = {"startup": "start and handshake", "list": "tool listing", "call": "call"}.get(
        outcome.phase, outcome.phase
    )
    if code == "timeout":
        seconds = entry.call_timeout_s if outcome.phase == "call" else entry.startup_timeout_s
        if outcome.killed_at_deadline:
            return (f"timeout: the MCP session did not end in time ({phase}); the harness "
                    "killed it and everything it started")
        return f"timeout: the server did not answer in time ({phase}, {seconds} s)"
    if code in ("result_too_large", "message_too_large"):
        size = outcome.fault_bytes or 0
        bound = limit if code == "result_too_large" and limit else LIST_MESSAGE_LIMIT
        amount = f"{size} bytes" if outcome.fault_bytes_exact else f"at least {size} bytes"
        return f"{code}: the server sent {amount} in one message; the limit is {bound} bytes"
    return {
        "server_exited": "server_exited: the server process ended before answering",
        "server_error": "server_error: the server answered the request with an error; its "
        "message is not shown",
        "stderr_too_large": "stderr_too_large: the server wrote more than "
        f"{_stderr_kill_bytes()} bytes on stderr; it was stopped",
        "protocol_error": "protocol_error: the server sent something that is not a valid MCP "
        "message; the session was closed",
        "invalid_result": "invalid_result: the structured result does not match the tool's "
        "output schema; it is not shown",
        "spawn_failed": "spawn_failed: the server could not be started; check its command in "
        "the MCP configuration",
        "interrupted": "interrupted",
    }.get(code or "", "internal_error: unexpected failure while talking to the server")


def _summary(server: str, tool: str, status: str, outcome: Outcome, redactions: int) -> None:
    print(
        f"call: {server}/{tool} {status} in {outcome.duration_ms} ms, "
        f"{outcome.call_bytes} bytes, {redactions} credential(s) redacted",
        file=sys.stderr,
    )


def _warn_if_alive(outcome: Outcome) -> None:
    if outcome.server_stopped is False:
        print("warning: a process of the MCP session was still alive after the kill",
              file=sys.stderr)
    from harness.mcp.transport import STDERR_KEEP_BYTES

    if outcome.stderr_bytes > STDERR_KEEP_BYTES:
        print(f"warning: the server wrote {outcome.stderr_bytes} bytes on stderr; only the "
              f"first {STDERR_KEEP_BYTES} were kept in its log", file=sys.stderr)


def _stderr_kill_bytes() -> int:
    from harness.mcp.transport import STDERR_KILL_BYTES

    return STDERR_KILL_BYTES


def _shown(name: str) -> str:
    return repr(safe_foreign_line(name).text[:64])


def _server_log(data_dir: Path, server: str) -> Path | None:
    """`<data>/logs/mcp/<server>.stderr.log`; None if unusable.

    Each session appends at most `transport.STDERR_KEEP_BYTES` (1 MiB) to it; before a session
    a file past `LOG_ROTATE_BYTES` (1 MiB) becomes `.1`, replacing the previous one. So the two
    files of a server never hold more than about 4 MiB. The directory and the files are
    readable by their owner only where the system has mode bits.
    """
    directory = data_dir / "logs" / "mcp"
    path = directory / f"{server}.stderr.log"
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if hasattr(os, "getuid"):
            os.chmod(directory, 0o700)
            if path.exists():
                os.chmod(path, 0o600)
        if path.exists() and path.stat().st_size > LOG_ROTATE_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))
    except OSError:
        print("warning: the server's stderr log cannot be written; it is discarded",
              file=sys.stderr)
        return None
    return path
