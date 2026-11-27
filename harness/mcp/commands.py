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
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from harness.config import Settings
from harness.core.errors import HarnessError
from harness.mcp.audit import args_key, recover_stale
from harness.mcp.config import LoadedConfig, ServerEntry, load_config
from harness.mcp.gateway import (
    COMPLETED,
    DENIED,
    LOG_ROTATE_BYTES,  # noqa: F401 - re-exported: the name the tests use
    CallReport,
    call_tool,
    server_log,
)
from harness.mcp.policy import USAGE_REASONS, Decision, decide_offered, parse_arguments
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
    """The call runs through `gateway.call_tool`, the one path a plan's steps use too
    (code-mode D10); here only what is printed is decided."""
    parsed = parse_arguments(raw_args)
    conn = open_database(data_dir)
    try:
        key = args_key(data_dir)
        recover_stale(conn, data_dir)
        try:
            report = call_tool(conn, data_dir, config, server, tool, parsed, key,
                               lambda: _server_log(data_dir, server), environ)
        except KeyboardInterrupt as interrupt:
            _warn_if_alive(interrupt.outcome)  # type: ignore[attr-defined]
            raise
    finally:
        conn.close()
    if report.outcome is None:  # denied before anything started
        _print_denied(report.decision)
        return EXIT_USAGE if report.decision.reason in USAGE_REASONS else EXIT_ERROR
    return _finish(report, server, tool, config.servers[server],
                   config.servers[server].tools[tool].max_result_bytes)


def _finish(report: CallReport, server: str, tool: str, entry: ServerEntry, limit: int) -> int:
    outcome = report.outcome
    assert outcome is not None
    _warn_if_alive(outcome)
    if report.status == DENIED:
        _print_denied(report.decision)
        return EXIT_ERROR
    if report.status == COMPLETED:
        assert report.rendered is not None
        print(prefixed(report.rendered.text))
        _summary(server, tool, "completed", outcome, report.rendered.redactions)
        return EXIT_OK
    if report.error_code == "tool_error":
        assert report.rendered is not None
        print("error: the tool reported an error:", file=sys.stderr)
        print(prefixed(report.rendered.text), file=sys.stderr)
        _summary(server, tool, "failed", outcome, report.rendered.redactions)
        return EXIT_ERROR
    print(f"error: {_explain(outcome, entry, limit)}", file=sys.stderr)
    _summary(server, tool, report.status, outcome, 0)
    return EXIT_ERROR


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
    if outcome.stderr_dropped > 0:
        print(f"warning: {outcome.stderr_dropped} of the {outcome.stderr_bytes} bytes the server "
              "wrote on stderr are not in its log; its last line says why", file=sys.stderr)


def _stderr_kill_bytes() -> int:
    from harness.mcp.transport import STDERR_KILL_BYTES

    return STDERR_KILL_BYTES


def _shown(name: str) -> str:
    return repr(safe_foreign_line(name).text[:64])


def _server_log(data_dir: Path, server: str) -> Path | None:
    """`gateway.server_log`, saying so on stderr when the log cannot be written."""
    path = server_log(data_dir, server)
    if path is None:
        print("warning: the server's stderr log cannot be written; it is discarded",
              file=sys.stderr)
    return path
