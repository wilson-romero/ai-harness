"""`workspace check|read|list --root <folder>` (workspace-tools slice B1).

The only way to reach the work-folder tools in this slice: no conversation command, no plan
catalogue, no loop. Like `mcp call`, the file's own text goes to stdout, every line after
`| `; the harness's lines (summary, refusal, warning) go to stderr and never hold file text.
Exit codes: 0 done, 1 refused, 2 misuse of the command line.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Mapping

from harness.config import Settings
from harness.mcp.audit import args_key
from harness.mcp.policy import canonical_json
from harness.storage.database import open_database
from harness.text.safe_text import terminal_safe
from harness.workspace.audit import record_call
from harness.workspace.codes import OK, WorkspaceRefused
from harness.workspace.render import prefixed
from harness.workspace.root import check_root
from harness.workspace.tools import (
    LIST_DEFAULT_DEPTH,
    LIST_MAX_DEPTH,
    READ_DEFAULT_LINES,
    READ_MAX_LINES,
    READ_MAX_OUTPUT_BYTES,
    list_folder,
    read_file,
)

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2


def add_workspace_parser(commands: argparse._SubParsersAction) -> None:
    workspace = commands.add_parser(
        "workspace", help="read files inside a work folder you choose (read-only in this build)"
    )
    sub = workspace.add_subparsers(dest="workspace_command", required=True)
    check = sub.add_parser("check", help="say whether a folder is accepted as the work folder")
    check.add_argument("--root", required=True, help="the work folder (an absolute path)")
    read = sub.add_parser("read", help="print lines of one file of the work folder")
    read.add_argument("path", help="relative to the work folder, with / as the separator")
    read.add_argument("--root", required=True, help="the work folder (an absolute path)")
    read.add_argument("--offset", type=int, default=1, help="first line, from 1")
    read.add_argument("--limit", type=int, default=READ_DEFAULT_LINES,
                      help=f"lines to print, at most {READ_MAX_LINES}")
    listing = sub.add_parser("list", help="list a folder of the work folder (no link followed)")
    listing.add_argument("path", nargs="?", default=None, help="relative folder (default: root)")
    listing.add_argument("--root", required=True, help="the work folder (an absolute path)")
    listing.add_argument("--depth", type=int, default=LIST_DEFAULT_DEPTH,
                         help=f"levels to list, at most {LIST_MAX_DEPTH}")


def _refused(refusal: WorkspaceRefused) -> int:
    detail = f": {refusal.detail}" if refusal.detail else ""
    print(f"error: refused: {refusal.code}{detail}", file=sys.stderr)
    return EXIT_REFUSED


def _shown_path(text: str | None) -> str:
    return terminal_safe(text or ".")[:200]


def run_workspace_command(args: argparse.Namespace,
                          environ: Mapping[str, str] | None = None) -> int:
    environ = os.environ if environ is None else environ
    if args.workspace_command == "read" and (
        args.offset < 1 or not 1 <= args.limit <= READ_MAX_LINES
    ):
        print(f"error: --offset starts at 1 and --limit is between 1 and {READ_MAX_LINES}",
              file=sys.stderr)
        return EXIT_USAGE
    if args.workspace_command == "list" and not 1 <= args.depth <= LIST_MAX_DEPTH:
        print(f"error: --depth is between 1 and {LIST_MAX_DEPTH}", file=sys.stderr)
        return EXIT_USAGE
    settings = Settings.from_env(environ)
    if args.workspace_command == "check":
        try:
            root = check_root(args.root, data_dir=settings.data_dir, environ=environ)
        except WorkspaceRefused as refusal:
            return _refused(refusal)
        print(f"workspace: accepted {terminal_safe(str(root.path))}", file=sys.stderr)
        return EXIT_OK

    conn = open_database(settings.data_dir)
    try:
        key = args_key(settings.data_dir)
        tool = args.workspace_command
        if tool == "read":
            arguments = {"path": args.path, "offset": args.offset, "limit": args.limit}
        else:
            arguments = {"path": args.path or ".", "depth": args.depth}
        try:
            canonical = canonical_json(arguments)
        except UnicodeEncodeError:  # undecodable command-line bytes: refused below anyway
            canonical = json.dumps(arguments, sort_keys=True).encode("ascii")
        started = time.monotonic()

        def audit(code: str, result_bytes: int | None = None, root_refused: bool = False) -> None:
            record_call(conn, key, tool=tool, canonical_args=canonical, code=code,
                        relative=args.path, result_bytes=result_bytes,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        root_refused=root_refused)

        try:
            root = check_root(args.root, data_dir=settings.data_dir, environ=environ)
        except WorkspaceRefused as refusal:
            audit(refusal.code, root_refused=True)
            return _refused(refusal)
        try:
            if tool == "read":
                result = read_file(root, args.path, args.offset, args.limit)
            else:
                listed = list_folder(root, args.path, args.depth)
        except WorkspaceRefused as refusal:
            audit(refusal.code)
            return _refused(refusal)
        if tool == "read":
            text = "\n".join(prefixed(row) for row in result.rows)
            if text:
                print(text)
            audit(OK, result_bytes=len(text.encode("utf-8")))
            span = f"lines {result.first}-{result.last} of {result.total}" if result.rows \
                else f"no lines of {result.total}"
            print(
                f"read: {_shown_path(result.relative)} {span}, sha256 {result.sha256[:12]}, "
                f"newline {result.newline}, bom {'yes' if result.bom else 'no'}",
                file=sys.stderr,
            )
            if result.output_cut:
                print(f"warning: output cut at {READ_MAX_OUTPUT_BYTES} bytes; continue with "
                      f"--offset {result.last + 1}", file=sys.stderr)
            if result.redactions:
                print(f"warning: {result.redactions} credential(s) masked", file=sys.stderr)
            return EXIT_OK
        text = "\n".join(prefixed(row) for row in listed.rows)
        if text:
            print(text)
        audit(OK, result_bytes=len(text.encode("utf-8")))
        marks = ", ".join(f"{count} {name}" for name, count in sorted(listed.marks.items()))
        print(f"list: {_shown_path(listed.relative)}, {len(listed.rows)} entries"
              f"{', ' + marks if marks else ''}", file=sys.stderr)
        if listed.stopped:
            print("warning: listing stopped at 500 entries", file=sys.stderr)
        return EXIT_OK
    finally:
        conn.close()
