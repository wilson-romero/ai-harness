"""The audit of a work-folder call: one `tool_calls` row and one `workspace_events` row.

Design B1-5. No column holds a path, a name or any text of a file: the arguments are kept as
the HMAC of their canonical JSON (the same key and function as `mcp call`), the relative path
as an HMAC under its own domain. Reads have no effect to reconcile, so the rows are written
once, finished, in one transaction (no `running` state).
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3

from harness.mcp.audit import PlanLink, new_call_id
from harness.storage.database import transaction, utc_now
from harness.workspace.codes import CALL_CODES, CODES, OK, STRING_CODES

SERVER = "workspace"
PATH_DOMAIN = b"ai-harness/workspace-path/v1\n"


def _hmac(key: bytes, data: bytes) -> str:
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def path_hmac(key: bytes, relative: str) -> str:
    return _hmac(key, PATH_DOMAIN + relative.encode("utf-8", errors="surrogatepass"))


def record_call(
    conn: sqlite3.Connection,
    key: bytes,
    *,
    tool: str,
    canonical_args: bytes,
    code: str,
    relative: str | None,
    result_bytes: int | None,
    duration_ms: int,
    root_refused: bool = False,
    plan: PlanLink | None = None,
) -> str:
    """Write the two rows of one call and return its id. `plan` is the plan the call is a
    step of (B2: `/plan` and `/agent`), None for the CLI."""
    assert code in CODES
    call_id = new_call_id()
    now = utc_now()
    args_hmac = _hmac(key, canonical_args) if canonical_args else None
    if code == OK:
        decision, reason, status, error = "allowed", "allowed", "completed", None
    elif root_refused:  # the CLI's `--root` refused before any call (B1-5)
        decision, reason, status, error = "denied", "server_not_allowed", "denied", None
    elif code in CALL_CODES:  # cut by its timeout or by the stop (B2-9)
        decision, reason = "allowed", "allowed"
        status, error = ("timeout", "timeout") if code == "timeout" else ("failed", "interrupted")
    elif code in STRING_CODES:
        decision, reason, status, error = "denied", "argument_invalid", "denied", None
    else:
        decision, reason, status, error = "allowed", "allowed", "failed", "tool_error"
    with transaction(conn):
        conn.execute(
            "INSERT INTO tool_calls (call_id, server, tool, operation, decision, reason, "
            "args_hmac, args_bytes, status, error_code, result_bytes, duration_ms, "
            "created_at, finished_at, plan_id, plan_step) "
            "VALUES (?, ?, ?, 'read', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (call_id, SERVER, tool, decision, reason, args_hmac, len(canonical_args), status,
             error, result_bytes, duration_ms, now, now,
             plan.plan_id if plan is not None else None,
             plan.position if plan is not None else None),
        )
        conn.execute(
            "INSERT INTO workspace_events (call_id, code, path_hmac, created_at) "
            "VALUES (?, ?, ?, ?)",
            (call_id, code, path_hmac(key, relative) if relative else None, now),
        )
    return call_id
