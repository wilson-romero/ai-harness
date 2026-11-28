"""`read` and `list` over the work folder (workspace-tools D4).

Nothing here prints, stores or sends: each tool returns the harness's summary fields and the
foreign rows, already made visible, redacted and bounded (`render.shown_line`).
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field

from harness.workspace.codes import WorkspaceRefused
from harness.workspace.paths import Root, check_relative, is_link, locate, read_located
from harness.workspace.render import shown_line
from harness.workspace.rules import check_names, decode_checked, name_refusal

READ_DEFAULT_LINES = 200
READ_MAX_LINES = 400
LINE_MAX_CHARS = 500
READ_MAX_OUTPUT_BYTES = 16 * 1024
LINE_CUT = " … [line cut at 500 characters]"
LIST_DEFAULT_DEPTH = 1
LIST_MAX_DEPTH = 3
LIST_MAX_ENTRIES = 500
# Past LIST_MAX_ENTRIES the walk goes on only to count what was left out (D4), up to this many.
LIST_COUNT_MAX = 5000


@dataclass(frozen=True)
class ReadResult:
    relative: str
    first: int
    last: int
    total: int
    sha256: str
    newline: str  # lf, crlf, mixed or none
    bom: bool
    rows: tuple[str, ...]
    output_cut: bool
    redactions: int


def newline_style(text: str) -> str:
    crlf = text.count("\r\n")
    lone_cr = text.count("\r") - crlf
    lf = text.count("\n") - crlf
    if crlf == 0 and lone_cr == 0:
        return "lf" if lf else "none"
    if lf == 0 and lone_cr == 0:
        return "crlf"
    return "mixed"


def read_file(root: Root, relative: str, offset: int = 1,
              limit: int = READ_DEFAULT_LINES) -> ReadResult:
    if offset < 1 or not 1 <= limit <= READ_MAX_LINES:
        raise ValueError("offset starts at 1 and limit is between 1 and 400")
    parts = check_relative(relative)
    check_names(parts)
    located = locate(root, parts)
    raw = read_located(root, located)
    decoded = decode_checked(raw)
    view = decoded.text.replace("\r\n", "\n")
    lines = view.split("\n")
    if view.endswith("\n"):
        lines.pop()
    if view == "":
        lines = []
    total = len(lines)
    if offset > max(total, 1):
        raise WorkspaceRefused("offset_out_of_range", f"the file has {total} lines")
    rows: list[str] = []
    used = 0
    redactions = 0
    cut = False
    last = offset - 1
    for number in range(offset, min(total, offset + limit - 1) + 1):
        text, masked = shown_line(lines[number - 1], LINE_MAX_CHARS, LINE_CUT)
        row = f"{number:>6}  {text}"
        size = len(row.encode("utf-8")) + 1
        if used + size > READ_MAX_OUTPUT_BYTES:
            cut = True
            break
        rows.append(row)
        used += size
        redactions += masked
        last = number
    return ReadResult(
        relative=located.relative,
        first=offset if rows else 0,
        last=last if rows else 0,
        total=total,
        sha256=hashlib.sha256(raw).hexdigest(),
        newline=newline_style(decoded.text),
        bom=decoded.bom,
        rows=tuple(rows),
        output_cut=cut,
        redactions=redactions,
    )


@dataclass(frozen=True)
class ListResult:
    relative: str
    rows: tuple[str, ...]
    stopped: bool  # LIST_MAX_ENTRIES reached
    redactions: int = 0
    marks: dict[str, int] = field(default_factory=dict)
    missing: int = 0  # entries left out past LIST_MAX_ENTRIES (at most LIST_COUNT_MAX)
    missing_capped: bool = False  # there were more than LIST_COUNT_MAX of them


def list_folder(root: Root, relative: str | None = None,
                depth: int = LIST_DEFAULT_DEPTH) -> ListResult:
    if not 1 <= depth <= LIST_MAX_DEPTH:
        raise ValueError("depth is between 1 and 3")
    parts: tuple[str, ...] = ()
    if relative not in (None, "", "."):
        parts = check_relative(relative)
        check_names(parts)
    located = locate(root, parts)
    if not stat.S_ISDIR(located.info.st_mode):
        raise WorkspaceRefused("not_a_directory", "list takes a folder")
    rows: list[str] = []
    marks: dict[str, int] = {}
    redactions = 0
    stopped = False
    missing = 0
    pending = [(located.path, parts, 1)]
    while pending and missing < LIST_COUNT_MAX:
        folder, prefix, level = pending.pop(0)
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            if not stopped:
                rows.append(_row(prefix[:-1], prefix[-1] if prefix else ".", "[unreadable]")[0])
            continue
        for name in names:
            if len(rows) >= LIST_MAX_ENTRIES:
                stopped = True
            if stopped:  # only counted from here on, never shown
                if missing >= LIST_COUNT_MAX:
                    break
                missing += 1
                mark, descend = _classify(folder / name, (*prefix, name))
            else:
                mark, descend = _classify(folder / name, (*prefix, name))
                row, masked = _row(prefix, name, mark, folder=descend)
                rows.append(row)
                redactions += masked
                if mark:
                    key = mark.split(":")[0].strip("[] ")
                    marks[key] = marks.get(key, 0) + 1
            if descend and level < depth:
                pending.append((folder / name, (*prefix, name), level + 1))
    capped = missing >= LIST_COUNT_MAX and bool(pending or stopped)
    return ListResult("/".join(parts) or ".", tuple(rows), stopped, redactions, marks,
                      missing, capped)


def _classify(path, parts: tuple[str, ...]) -> tuple[str, bool]:
    """(mark, descend) for one listed entry; never opens it."""
    try:
        check_relative(parts[-1])
    except WorkspaceRefused as refused:
        return f"[unusable name: {refused.code}]", False
    try:
        info = os.lstat(path)
    except OSError:
        return "[unreadable]", False
    if stat.S_ISLNK(info.st_mode) or is_link(path):
        return "[link]", False
    code = name_refusal(parts)
    if code is not None:
        return f"[denied: {code}]", False
    if stat.S_ISDIR(info.st_mode):
        return "", True
    if not stat.S_ISREG(info.st_mode):
        return "[not a regular file]", False
    return "", False


def _row(prefix: tuple[str, ...], name: str, mark: str, folder: bool = False) -> tuple[str, int]:
    # The names come from the file system: foreign text, made visible and redacted.
    shown, masked = shown_line("/".join((*prefix, name)), 1024, " … [name cut]")
    return f"{shown}{'/' if folder else ''}{(' ' + mark) if mark else ''}", masked
