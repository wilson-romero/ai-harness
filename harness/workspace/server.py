"""The work folder as an internal server of the plan catalogue (workspace-tools D6, D7, B2).

`read` and `list` become tools of a server named `workspace` that the harness itself is: a
literal table in code, under the same policy (`decide_before_start`), the same entry hash
(`policy.entry_sha256`, which here binds a keyed hash of the folder) and the same `tool_calls`
audit as an MCP server, and never started as a process. It exists only while the person has
set a work folder for the session (`/workspace <path>`): without one, no `workspace` server is
in the catalogue and a plan that names it is `server_not_allowed`.

The `path` argument counts as bounded under the loop's rule (code-mode A3-12): a pattern and at
most 64 characters (`BOUNDED_STRING_MAX_LENGTH`), on top of the confinement of D2 and the
fixed rules of D3, which still decide every path. So inside `/agent` the reads run by rule;
see design B2-2 for why that is acceptable and what still leaves the machine.

What a call returns is foreign text made visible, redacted and bounded by `tools`, every file
line or listed name after `| `; the harness's own line goes first and never holds file text.
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from harness.mcp.audit import PlanLink
from harness.mcp.config import BOUNDED_STRING_MAX_LENGTH, InternalServer, ToolEntry
from harness.mcp.policy import ParsedArguments
from harness.workspace.audit import SERVER, record_call
from harness.workspace.codes import OK, WorkspaceRefused
from harness.workspace.paths import Root
from harness.workspace.render import prefixed
from harness.workspace.tools import (
    LIST_MAX_DEPTH,
    READ_DEFAULT_LINES,
    READ_MAX_LINES,
    READ_MAX_OUTPUT_BYTES,
    list_folder,
    read_file,
)

# A relative path the model may name: components of ASCII letters, digits, `.`, `_` and `-`,
# none `.` or `..` (each starts with an optional dot and then a letter, a digit or `_`), `/`
# between them. A name outside it (a space, an accent) cannot be read by a plan in this
# version; `main.py workspace read` reads any name the confinement accepts.
PATH_PATTERN = r"\.?[A-Za-z0-9_][A-Za-z0-9._-]*(/\.?[A-Za-z0-9_][A-Za-z0-9._-]*)*"
PATH_MAX_CHARS = BOUNDED_STRING_MAX_LENGTH
MAX_OFFSET = 1_000_000
RESULT_MAX_BYTES = READ_MAX_OUTPUT_BYTES + 1024  # the rows plus the harness's two lines
FOLDER_DOMAIN = b"ai-harness/workspace-folder/v1\n"

_PATH = {"type": "string", "max_length": PATH_MAX_CHARS, "pattern": PATH_PATTERN}
TOOLS: dict[str, ToolEntry] = {
    "list": ToolEntry.model_validate({
        "operation": "read",
        "auto_read": True,
        "max_result_bytes": RESULT_MAX_BYTES,
        "description": "names in a folder of the work folder (path relative to it, none for "
                       "its top); links and denied names are marked",
        "arguments": {
            "path": {**_PATH, "required": False},
            "depth": {"type": "integer", "minimum": 1, "maximum": LIST_MAX_DEPTH},
        },
    }),
    "read": ToolEntry.model_validate({
        "operation": "read",
        "auto_read": True,
        "max_result_bytes": RESULT_MAX_BYTES,
        "description": "numbered lines of one text file of the work folder (path relative to "
                       f"it), {READ_DEFAULT_LINES} unless limit says otherwise",
        "arguments": {
            "path": {**_PATH, "required": True},
            "offset": {"type": "integer", "minimum": 1, "maximum": MAX_OFFSET},
            "limit": {"type": "integer", "minimum": 1, "maximum": READ_MAX_LINES},
        },
    }),
}


def folder_hmac(key: bytes, root: Root) -> str:
    """The folder as a keyed hash of its resolved path and its identity: what the consent
    and the plan's entry hash bind, never the path itself (D7, D14)."""
    data = f"{root.path}\n{root.device}:{root.inode}".encode("utf-8", errors="surrogatepass")
    return hmac.new(key, FOLDER_DOMAIN + data, hashlib.sha256).hexdigest()


class Folder:
    """The work folder of one conversation, shared by every policy view built from it. Once
    a call finds the folder replaced (`workspace_changed`), it stays suspended, even if the
    same folder comes back, until the person chooses one again (D1)."""

    def __init__(self, root: Root) -> None:
        self.root = root
        self.suspended = False


@dataclass(frozen=True)
class Answer:
    code: str
    text: str
    redactions: int = 0
    relative: str | None = None


def run_tool(root: Root, tool: str, arguments: dict[str, Any]) -> Answer:
    """One call of the table, as text for a plan's result block. Raises nothing it expects:
    a refusal is an `Answer` with its code and the harness's reason."""
    relative = arguments.get("path")
    try:
        if tool == "read":
            result = read_file(root, relative, arguments.get("offset", 1),
                               arguments.get("limit", READ_DEFAULT_LINES))
            span = (f"lines {result.first}-{result.last} of {result.total}" if result.rows
                    else f"no lines of {result.total}")
            lines = [f"read: {result.relative}, {span}, sha256 {result.sha256[:12]}, newline "
                     f"{result.newline}, bom {'yes' if result.bom else 'no'}",
                     *(prefixed(row) for row in result.rows)]
            if result.output_cut:
                lines.append(f"[output cut at {READ_MAX_OUTPUT_BYTES} bytes; continue with "
                             f"offset {result.last + 1}]")
            return Answer(OK, "\n".join(lines), result.redactions, relative)
        listed = list_folder(root, relative, arguments.get("depth", 1))
        marks = ", ".join(f"{count} {name}" for name, count in sorted(listed.marks.items()))
        head = (f"list: {listed.relative}, {len(listed.rows)} entries"
                f"{', ' + marks if marks else ''}")
        rows, used, cut = [], len(head.encode("utf-8")) + 1, False
        for row in listed.rows:
            line = prefixed(row)
            size = len(line.encode("utf-8")) + 1
            if used + size > READ_MAX_OUTPUT_BYTES:
                cut = True
                break
            rows.append(line)
            used += size
        tail = []
        if cut:
            tail.append(f"[listing cut at {READ_MAX_OUTPUT_BYTES} bytes after {len(rows)} "
                        "entries; list a subfolder]")
        elif listed.stopped:
            tail.append("[listing stopped at 500 entries]")
        return Answer(OK, "\n".join([head, *rows, *tail]), listed.redactions, relative)
    except WorkspaceRefused as refused:
        detail = f": {refused.detail}" if refused.detail else ""
        return Answer(refused.code, f"refused: {refused.code}{detail}", 0, relative)


class WorkspaceServer(InternalServer):
    """The `workspace` server of one session's work folder."""

    tools = TOOLS

    def __init__(self, folder: Folder, key: bytes) -> None:
        self.state = folder
        self.folder = folder_hmac(key, folder.root)

    def bound(self) -> dict[str, Any]:
        return {"internal": SERVER, "folder": self.folder}

    def call(self, conn: sqlite3.Connection, key: bytes, tool: str, parsed: ParsedArguments,
             plan: PlanLink | None):
        from harness.mcp.client import Outcome
        from harness.mcp.gateway import COMPLETED, FAILED, CallReport
        from harness.mcp.policy import Decision
        from harness.mcp.render import Rendered

        started = time.monotonic()
        try:
            if self.state.suspended:
                raise WorkspaceRefused("workspace_changed", "the work folder is suspended since "
                                       "it was found replaced; choose it again with /workspace")
            # `locate` checks the root first (`check_root_unchanged`): a replaced folder gives
            # `workspace_changed`, which suspends it below.
            answer = run_tool(self.state.root, tool, dict(parsed.value))
        except WorkspaceRefused as refused:
            answer = Answer(refused.code, f"refused: {refused.code}: {refused.detail}")
        if answer.code == "workspace_changed":
            self.state.suspended = True
        data = answer.text.encode("utf-8")
        duration = int((time.monotonic() - started) * 1000)
        call_id = record_call(
            conn, key, tool=tool, canonical_args=parsed.canonical, code=answer.code,
            relative=answer.relative, result_bytes=len(data) if answer.code == OK else None,
            duration_ms=duration, root_refused=answer.code == "workspace_changed", plan=plan)
        outcome = Outcome(phase="done", call_bytes=len(data), duration_ms=duration,
                          call_sent=True)
        allowed = Decision(True, "allowed", operation="read")
        rendered = Rendered(answer.text, answer.redactions)
        if answer.code == OK:
            return CallReport(COMPLETED, allowed, outcome, None, rendered, call_id)
        return CallReport(FAILED, allowed, outcome, "tool_error", rendered, call_id)
