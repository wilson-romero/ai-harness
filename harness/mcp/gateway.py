"""One tool call through the gateway, without printing (code-mode D10).

This is the body `mcp call` always had, taken out of `commands._call` so that a step of an
approved plan goes through exactly the same path: the policy before anything starts
(`decide_before_start`), the `running` row committed before the session process starts, the
session with the server's own deadlines and result limit, the check of the offered tools
(`decide_offered`) before the one `tools/call`, and the row finished with what happened. Only
what is done with the result differs: `mcp call` prints it, a plan shows it in its blocks.

Nothing here prints. Every text a `CallReport` holds of a tool (its result or its error
message) has been cleaned and redacted by `render`; the rest is harness text.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from harness.mcp.audit import (
    PlanLink,
    call_lock,
    forget_lock,
    new_call_id,
    record_denied,
    record_denied_after_listing,
    record_finished,
    record_running,
)
from harness.mcp.config import InternalServer, LoadedConfig
from harness.mcp.policy import Decision, ParsedArguments, decide_before_start, decide_offered
from harness.storage.private import private_dir

if TYPE_CHECKING:
    from harness.mcp.client import OfferedTool, Outcome, StopSignal
    from harness.mcp.render import Rendered

COMPLETED = "completed"
DENIED = "denied"  # by the policy, before the start or after the listing
FAILED = "failed"  # the session or the tool failed (`error_code` says how)
TIMEOUT = "timeout"
LOG_ROTATE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class CallReport:
    """What one call came to. `decision` is the policy's last word on it (before the start,
    or after the listing when the server's offer refused it); `outcome` is None when nothing
    was started. `rendered` is the cleaned result (completed) or the tool's own error message
    (`error_code` "tool_error"), never anything else."""

    status: str
    decision: Decision
    outcome: Outcome | None = None
    error_code: str | None = None
    rendered: Rendered | None = None
    call_id: str | None = None


def call_tool(
    conn: sqlite3.Connection,
    data_dir: Path,
    config: LoadedConfig,
    server: str,
    tool: str,
    parsed: ParsedArguments,
    key: bytes,
    errlog: Callable[[], Path | None],
    environ: Mapping[str, str],
    *,
    plan: PlanLink | None = None,
    stop: StopSignal | None = None,
) -> CallReport:
    """Decide, record, run and record one call. Raises KeyboardInterrupt (with `.outcome`)
    after recording the row `failed`/`interrupted`, exactly as `mcp call` always did; the
    caller decides what an interruption means for it. The caller holds the database open and
    has run `recover_stale` once. `errlog` names the server's log; it is asked only once the
    call is allowed, so a denied call creates nothing."""
    from harness.mcp.client import Outcome, SessionRequest, run_session
    from harness.mcp.render import render_error, render_result

    decision = decide_before_start(config, server, tool, parsed)
    if not decision.allowed:
        row = record_denied(conn, server, tool, decision.reason, decision.operation,
                            parsed.canonical, parsed.size, key, plan)
        return CallReport(DENIED, decision, call_id=row.call_id)
    entry = config.servers[server]
    if isinstance(entry, InternalServer):
        # The harness's own server (workspace-tools D7): the same policy above and the same
        # `tool_calls` table, but no process; it records its own finished row.
        return entry.call(conn, key, tool, parsed, plan)
    declared = entry.tools[tool]
    call_id = new_call_id()
    lock = call_lock(data_dir, call_id)
    lock.acquire()  # a new name: nobody else can hold it
    try:
        row = record_running(conn, call_id, server, tool, declared.operation,
                             parsed.canonical, key, plan)

        def check(offered: Mapping[str, OfferedTool]) -> Decision:
            found = offered.get(tool)
            if found is None:
                return decide_offered(declared, None, tool)
            return decide_offered(declared, found.input_schema, tool, found.annotations)

        request = SessionRequest(
            entry, errlog(), tool, parsed.value, declared.max_result_bytes, check, stop,
        )
        try:
            outcome = run_session(request, environ)
        except KeyboardInterrupt as interrupt:
            outcome = getattr(interrupt, "outcome", Outcome(error_code="interrupted"))
            interrupt.outcome = outcome  # type: ignore[attr-defined]
            record_finished(conn, row, "failed", "interrupted", outcome.server_stopped,
                            None, outcome.duration_ms)
            raise
        if outcome.decision is not None and not outcome.decision.allowed:
            record_denied_after_listing(conn, row, outcome.decision.reason,
                                        outcome.server_stopped, outcome.duration_ms)
            return CallReport(DENIED, outcome.decision, outcome, call_id=call_id)
        result = outcome.result
        if outcome.error_code is not None or result is None:
            code = outcome.error_code or "internal_error"
            status = TIMEOUT if code == "timeout" else FAILED
            record_finished(conn, row, status, code, outcome.server_stopped,
                            outcome.call_bytes or None, outcome.duration_ms)
            return CallReport(status, decision, outcome, code, call_id=call_id)
        if result.is_error:
            message = render_error(result)
            record_finished(conn, row, "failed", "tool_error", outcome.server_stopped,
                            outcome.call_bytes, outcome.duration_ms)
            return CallReport(FAILED, decision, outcome, "tool_error", message, call_id)
        rendered = render_result(result)
        record_finished(conn, row, COMPLETED, None, outcome.server_stopped, outcome.call_bytes,
                        outcome.duration_ms)
        return CallReport(COMPLETED, decision, outcome, None, rendered, call_id)
    finally:
        lock.release()
        forget_lock(data_dir, call_id)



def server_log(data_dir: Path, server: str) -> Path | None:
    """`<data>/logs/mcp/<server>.stderr.log`; None if unusable (the caller says so or not).

    Each session appends at most `transport.STDERR_KEEP_BYTES` (1 MiB) to it; before a session
    a file past `LOG_ROTATE_BYTES` (1 MiB) becomes `.1`, replacing the previous one. So the two
    files of a server never hold more than about 4 MiB. The directory and the files are
    readable by their owner only where the system has mode bits.
    """
    directory = data_dir / "logs" / "mcp"
    path = directory / f"{server}.stderr.log"
    try:
        private_dir(directory)  # and its missing parents (security review 2026-11-27, F-08)
        if hasattr(os, "getuid"):
            os.chmod(directory, 0o700)
            if path.exists():
                os.chmod(path, 0o600)
        if path.exists() and path.stat().st_size > LOG_ROTATE_BYTES:
            try:
                os.replace(path, path.with_name(path.name + ".1"))
            except PermissionError:
                # Revised on 2026-11-26: another session still writes it, and the system does
                # not replace an open file (Windows, WinError 32). Append now, rotate next time.
                pass
    except OSError:
        return None
    return path
