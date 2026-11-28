"""A relative path inside the work folder, confined in three phases (workspace-tools D2).

1. `check_relative`: a pure function of the string, the same answer on every platform.
2. `locate`: component by component from the root, each one exactly a name its directory
   lists (case, NFC/NFD, Windows short names), none a link or a junction.
3. `read_located`: open without following a link and check, on the descriptor, that it is
   still the same regular file with one hard link, then that it still resolves inside.

Residual race (design D2, `docs/security/known-debt.md`): between phase 2 and the open another
process with the person's account can swap an intermediate directory for a link. Phase 3
catches it for the file itself (identity, resolution) but there is no portable `openat`
(`os.supports_dir_fd` lacks `os.open` on Windows), so the window is not closed. The attacker of
this design is the folder's content, not a concurrent local process.

No branch by platform: flags are looked up by capability (`getattr(os, ..., 0)`).
"""

from __future__ import annotations

import os
import stat
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from harness.memory.paths import is_within
from harness.skills.approvals import is_invisible
from harness.workspace.codes import WorkspaceRefused
from harness.workspace.rules import FILE_MAX_BYTES

MAX_PATH_CHARS = 1024
MAX_COMPONENT_BYTES = 255
# Device names Windows reserves whatever the extension (`con.txt` is the console); kept as a
# literal list, as `harness/memory/paths.py` does, plus the console aliases and the
# superscript-digit ports Windows also reserves.
WINDOWS_RESERVED = frozenset(
    ["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"]
    + [f"COM{i}" for i in (*range(1, 10), "¹", "²", "³")]
    + [f"LPT{i}" for i in (*range(1, 10), "¹", "²", "³")]
)
WINDOWS_FORBIDDEN = frozenset('<>"|?*')
LINE_SEPARATORS = frozenset("  \x85")
READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_BINARY", 0)
)


def check_relative(text: str) -> tuple[str, ...]:
    """The components of a relative path, or `WorkspaceRefused` with the first rule broken."""
    if not text:
        raise WorkspaceRefused("empty_path", "the path is empty")
    if len(text) > MAX_PATH_CHARS:
        raise WorkspaceRefused("path_too_long", f"paths are at most {MAX_PATH_CHARS} characters")
    if "\x00" in text:
        raise WorkspaceRefused("forbidden_character", "the path contains NUL")
    # `is_invisible` keeps "\n" (it ends lines of approved text); a path has no line end.
    if any(is_invisible(c) or c in LINE_SEPARATORS or c == "\n" for c in text):
        raise WorkspaceRefused("invisible_character",
                               "the path contains an invisible or control character")
    if unicodedata.normalize("NFC", text) != text:
        raise WorkspaceRefused("not_nfc", "the path is not in Unicode NFC form")
    windows = PureWindowsPath(text)
    if text.startswith(("/", "\\")) or windows.drive or windows.anchor:
        raise WorkspaceRefused("absolute", "paths are relative to the work folder")
    if "\\" in text:
        raise WorkspaceRefused("backslash", "use / as the separator")
    if ":" in text:
        raise WorkspaceRefused("colon", "':' is refused (drives and alternate data streams)")
    if any(c in WINDOWS_FORBIDDEN for c in text):
        raise WorkspaceRefused("forbidden_character", 'the path contains one of <>"|?*')
    parts = tuple(text.split("/"))
    for part in parts:
        if part == "":
            raise WorkspaceRefused("empty_component", "the path has an empty component")
        if part in (".", ".."):
            raise WorkspaceRefused("dot_component", "'.' and '..' are refused")
        if len(part.encode("utf-8")) > MAX_COMPONENT_BYTES:
            raise WorkspaceRefused("component_too_long",
                                   f"a component is at most {MAX_COMPONENT_BYTES} bytes")
        if part.endswith((".", " ")):
            raise WorkspaceRefused("trailing_dot_or_space",
                                   "a component ends in a dot or a space")
        if part.split(".", 1)[0].rstrip(" ").upper() in WINDOWS_RESERVED:
            raise WorkspaceRefused("reserved_name", "a component is a reserved Windows name")
    return parts


def fold(name: str) -> str:
    """The form under which two names may be the same entry on some file system."""
    return unicodedata.normalize("NFC", name).casefold()


def is_link(path: Path) -> bool:
    """A symbolic link or a Windows directory junction (`is_junction` is False elsewhere)."""
    return path.is_symlink() or path.is_junction()


@dataclass(frozen=True)
class Root:
    path: Path  # resolved, absolute
    device: int
    inode: int


@dataclass(frozen=True)
class Located:
    path: Path
    relative: str  # POSIX form, as given
    info: os.stat_result  # the lstat taken while walking


# A test hook between the walk and the open (the TOCTOU test swaps the file here).
before_open: Callable[[Path], None] | None = None


def check_root_unchanged(root: Root) -> None:
    try:
        info = os.lstat(root.path)
    except OSError:
        raise WorkspaceRefused("workspace_changed", "the work folder is gone") from None
    if (
        is_link(root.path)
        or not stat.S_ISDIR(info.st_mode)
        or (info.st_dev, info.st_ino) != (root.device, root.inode)
    ):
        raise WorkspaceRefused("workspace_changed",
                               "the work folder was replaced since it was chosen")


def locate(root: Root, parts: tuple[str, ...]) -> Located:
    """Walk `parts` from the root without following anything (phase 2)."""
    check_root_unchanged(root)
    current = root.path
    info = os.lstat(current)
    for position, name in enumerate(parts):
        try:
            names = os.listdir(current)
        except OSError:
            raise WorkspaceRefused("unreadable", "a folder on the path cannot be listed") from None
        if name not in names:
            # Never looked up under another spelling: a short name or another case is not
            # followed even where the file system would resolve it.
            wanted = fold(name)
            if any(fold(entry) == wanted for entry in names):
                raise WorkspaceRefused("name_not_exact",
                                       "the name differs from the listed one (case or form)")
            raise WorkspaceRefused("not_found", "no such entry in the work folder")
        entry = current / name
        try:
            info = os.lstat(entry)
        except OSError:
            raise WorkspaceRefused("unreadable", "an entry on the path cannot be read") from None
        if stat.S_ISLNK(info.st_mode) or is_link(entry):
            raise WorkspaceRefused("link", "links and junctions are never followed")
        if position < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise WorkspaceRefused("not_a_directory", "a component on the path is not a folder")
        current = entry
    return Located(current, "/".join(parts), info)


def read_located(root: Root, located: Located, max_bytes: int = FILE_MAX_BYTES) -> bytes:
    """The bytes of a located regular file, checked on its descriptor (phase 3)."""
    info = located.info
    if not stat.S_ISREG(info.st_mode):
        raise WorkspaceRefused("not_regular", "only regular files are read")
    if info.st_nlink > 1:
        raise WorkspaceRefused("hard_link", "a file with more than one hard link is not read")
    if info.st_size > max_bytes:
        raise WorkspaceRefused("too_large", f"files over {max_bytes} bytes are not read")
    if before_open is not None:
        before_open(located.path)
    try:
        fd = os.open(located.path, READ_FLAGS)
    except OSError:
        # A link put in its place (O_NOFOLLOW refuses it) or a file gone since the walk.
        raise WorkspaceRefused("changed", "the file changed between the check and the open") \
            from None
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            info.st_dev, info.st_ino
        ):
            raise WorkspaceRefused("changed", "the file changed between the check and the open")
        if opened.st_nlink > 1:
            raise WorkspaceRefused("hard_link", "a file with more than one hard link is not read")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError:
        raise WorkspaceRefused("unreadable", "the file cannot be read") from None
    finally:
        os.close(fd)
    try:
        real = located.path.resolve(strict=True)
    except OSError:
        raise WorkspaceRefused("changed", "the file changed while it was read") from None
    if not is_within(real, root.path):
        raise WorkspaceRefused("outside_root", "the file resolves outside the work folder")
    raw = b"".join(chunks)
    if len(raw) > max_bytes:
        raise WorkspaceRefused("too_large", f"files over {max_bytes} bytes are not read")
    return raw
