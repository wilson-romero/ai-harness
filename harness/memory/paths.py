"""Path validation and the confined walk over the vault.

The validation functions are pure: they take `PurePath`s or strings and behave the same for
Windows and POSIX inputs on any platform. The walk is the only place that touches the file
system, and it never follows a link.
"""

from __future__ import annotations

import os
import re
import stat
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePath

from harness.core.errors import InvalidProject, ProjectNotFound

FILE_MAX_BYTES = 1024 * 1024
WALK_MAX_FILES = 20_000
NOTE_SUFFIX = ".md"
PROJECTS_DIR = "projects"
ARCHIVE_DIR = "Memoria/Archivo"

_PROJECT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
# Kept as our own list: PurePath.is_reserved() is deprecated and os.path.isreserved does not
# exist on every platform.
_WINDOWS_RESERVED = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)

# Reasons an entry of the vault is not read. Stable strings: they are printed and tested.
SKIP_HIDDEN = "hidden"
SKIP_ARCHIVE = "archive"
SKIP_LINK = "link"
SKIP_HARD_LINK = "hard-link"
SKIP_NOT_REGULAR = "not-regular"
SKIP_NOT_MARKDOWN = "not-markdown"
SKIP_TOO_LARGE = "too-large"
SKIP_OUTSIDE_ROOT = "outside-root"
SKIP_UNREADABLE = "unreadable"
SKIP_CHANGED = "changed"  # replaced between the walk and the read
SKIP_REASONS = (
    SKIP_HIDDEN,
    SKIP_ARCHIVE,
    SKIP_LINK,
    SKIP_HARD_LINK,
    SKIP_NOT_REGULAR,
    SKIP_NOT_MARKDOWN,
    SKIP_TOO_LARGE,
    SKIP_OUTSIDE_ROOT,
    SKIP_UNREADABLE,
    SKIP_CHANGED,
)


# -- pure validation ----------------------------------------------------------------------------


SLUG_MAX_CHARS = 128
SLUG_RULE = (
    "use the plain name of a folder under projects/ (letters, digits, '.', '_' and '-', "
    f"starting with a letter or a digit, at most {SLUG_MAX_CHARS} characters)"
)


def validate_project_slug(raw: str) -> str:
    """Accept only a simple folder name. Same answer and message on every platform.

    The rule is not relaxed for real vaults (memory-format-conformance D3): the identifier is
    stored with the session and written into the decision note's frontmatter, so a project
    folder whose name breaks it (a `vault_slug` of `claude-memory-system` keeps the spaces and
    accents of the path it comes from) is refused, and the message says why.
    """
    if not _is_valid_slug(raw):
        raise InvalidProject(
            f"invalid project identifier {raw!r}: {slug_problem(raw)}; {SLUG_RULE}"
        )
    return raw


def slug_problem(raw: str) -> str:
    """Why `raw` is not a valid project identifier, in words; the same on every platform.

    Only called for a name `_is_valid_slug` refused. The checks go from the most specific
    reason to the most general one, so that each name gets the one that explains it best.
    """
    if not raw:
        return "it is empty"
    if "/" in raw or "\\" in raw:
        return "it contains a path separator"
    if raw in (".", ".."):
        return "it is a relative path part"
    if len(raw) > SLUG_MAX_CHARS:
        return f"it is longer than {SLUG_MAX_CHARS} characters"
    if raw.endswith((".", " ")):
        return "it ends with a dot or a space"
    if not raw[0].isascii() or not raw[0].isalnum():
        return "it does not start with a letter or a digit"
    if " " in raw:
        return "it contains a space"
    if not raw.isascii():
        return "it contains a character that is not ASCII"
    if not _PROJECT_RE.fullmatch(raw):
        return "it contains a character other than letters, digits, '.', '_' and '-'"
    return "it is a reserved Windows device name"


def is_safe_name(raw: str) -> bool:
    """A plain file or folder name that means the same on every platform (no separators,
    no `..`, no trailing dot or space, not a reserved Windows device name)."""
    return _is_valid_slug(raw)


def is_safe_file_name(raw: str) -> bool:
    """A file name the harness may create, legal and with one meaning on Windows and POSIX.

    The rules of `is_safe_name` (letters, digits, `.`, `_`, `-`; no separator, no `..`, no
    trailing dot or space, no reserved device name, at most 128 characters), or a hidden name
    (one leading dot) whose rest follows them.
    """
    return _is_valid_slug(raw[1:] if raw.startswith(".") else raw)


def _is_valid_slug(raw: str) -> bool:
    if not _PROJECT_RE.fullmatch(raw) or raw in (".", ".."):
        return False
    if raw.endswith((".", " ")):
        return False
    stem = raw.split(".", 1)[0].upper()
    return stem not in _WINDOWS_RESERVED


def is_within(path: PurePath, root: PurePath) -> bool:
    """Containment with the path flavour's own rules (case-insensitive for Windows paths).

    Pure paths keep `..` (`C:\\Vault\\..\\x` is "relative to" `C:\\Vault` for pathlib), so a
    path with a `..` part is never inside: callers pass resolved paths, and an unresolved one
    is refused rather than trusted.
    """
    if ".." in path.parts or ".." in root.parts:
        return False
    return path.is_relative_to(root)


# -- file system --------------------------------------------------------------------------------


def resolve_project(root: Path, slug: str) -> Path:
    """Return the project folder. The name must match a real folder exactly, case included."""
    validate_project_slug(slug)
    projects = root / PROJECTS_DIR
    try:
        names = os.listdir(projects)
    except OSError:
        names = []
    folder = projects / slug
    if slug not in names or folder.is_symlink() or folder.is_junction() or not folder.is_dir():
        raise ProjectNotFound(f"project {slug!r} does not exist under projects/")
    return folder


@dataclass(frozen=True)
class VaultFile:
    path: Path  # absolute path inside the real root
    relative: str  # POSIX-style path relative to the root
    size: int
    device: int  # st_dev and st_ino of the lstat taken during the walk: the file's identity
    inode: int


class SkippedRead(Exception):
    """A walked file that was not read after all; `reason` is one of SKIP_REASONS."""

    def __init__(self, relative: str, reason: str) -> None:
        super().__init__(f"{relative}: {reason}")
        self.relative = relative
        self.reason = reason


def read_vault_file(file: VaultFile) -> bytes:
    """The bytes of a walked file, only if it is still the same regular file (SEC-04).

    The walk saw a regular file with this identity; between that and this read another
    process may have put a link, a directory, a pipe or another file in its place, or the
    file may have grown. Opening follows links, so what was opened is checked on the open
    descriptor (`fstat`), which cannot change any more: same device and inode, a regular
    file, and no more than FILE_MAX_BYTES read. Otherwise the file counts as skipped.
    """
    # O_NONBLOCK keeps a pipe swapped in from blocking the open; O_BINARY stops newline
    # translation where it exists. Both are read-only flags, looked up by capability.
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(file.path, flags)
    except OSError:
        raise SkippedRead(file.relative, SKIP_UNREADABLE) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (
            file.device,
            file.inode,
        ):
            raise SkippedRead(file.relative, SKIP_CHANGED)
        chunks: list[bytes] = []
        remaining = FILE_MAX_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError:
        raise SkippedRead(file.relative, SKIP_UNREADABLE) from None
    finally:
        os.close(fd)
    raw = b"".join(chunks)
    if len(raw) > FILE_MAX_BYTES:
        raise SkippedRead(file.relative, SKIP_TOO_LARGE)
    return raw


@dataclass(frozen=True)
class WalkResult:
    files: tuple[VaultFile, ...]
    skipped: tuple[tuple[str, str], ...]  # (relative path, reason), in walk order
    truncated: bool = False
    skipped_counts: Mapping[str, int] = field(default_factory=dict)

    @property
    def skipped_total(self) -> int:
        return len(self.skipped)


def walk_vault(root: Path, max_files: int = WALK_MAX_FILES) -> WalkResult:
    """Every readable Markdown note under `root`, in a deterministic order.

    `root` must already be the real, resolved vault root. Links and junctions are never
    followed or read, files with more than one hard link are skipped, and each accepted file
    must still resolve inside the root.
    """
    files: list[VaultFile] = []
    skipped: list[tuple[str, str]] = []
    truncated = False

    def rel(path: Path) -> str:
        return path.relative_to(root).as_posix()

    def unreadable(error: OSError) -> None:
        # A directory that cannot be listed is reported, not silently left out.
        where = Path(error.filename) if error.filename else root
        skipped.append((rel(where) if where != root else ".", SKIP_UNREADABLE))

    for dirpath, dirnames, filenames in os.walk(
        root, topdown=True, onerror=unreadable, followlinks=False
    ):
        current = Path(dirpath)
        keep: list[str] = []
        for name in sorted(dirnames):
            entry = current / name
            reason = _dir_skip_reason(entry, name, rel(entry))
            if reason:
                skipped.append((rel(entry), reason))
            else:
                keep.append(name)
        dirnames[:] = keep
        for name in sorted(filenames):
            entry = current / name
            reason = _file_skip_reason(entry, name, root)
            if reason:
                skipped.append((rel(entry), reason))
                continue
            if len(files) >= max_files:
                truncated = True
                break
            try:
                info = entry.lstat()
            except OSError:
                skipped.append((rel(entry), SKIP_UNREADABLE))
                continue
            files.append(VaultFile(entry, rel(entry), info.st_size, info.st_dev, info.st_ino))
        if truncated:
            break
    counts = Counter(reason for _, reason in skipped)
    return WalkResult(
        files=tuple(files),
        skipped=tuple(skipped),
        truncated=truncated,
        skipped_counts={reason: counts[reason] for reason in SKIP_REASONS if counts[reason]},
    )


def _dir_skip_reason(entry: Path, name: str, relative: str) -> str | None:
    if entry.is_symlink() or entry.is_junction():
        return SKIP_LINK
    if name.startswith("."):
        return SKIP_HIDDEN
    if relative == ARCHIVE_DIR:
        return SKIP_ARCHIVE
    return None


def _file_skip_reason(entry: Path, name: str, root: Path) -> str | None:
    if entry.is_symlink() or entry.is_junction():
        return SKIP_LINK
    if name.startswith("."):
        return SKIP_HIDDEN
    try:
        info = entry.lstat()
    except OSError:
        return SKIP_UNREADABLE
    if not entry.is_file():
        return SKIP_NOT_REGULAR
    if info.st_nlink > 1:
        return SKIP_HARD_LINK
    if not name.endswith(NOTE_SUFFIX):
        return SKIP_NOT_MARKDOWN
    if info.st_size > FILE_MAX_BYTES:
        return SKIP_TOO_LARGE
    try:
        real = entry.resolve(strict=True)
    except OSError:
        return SKIP_UNREADABLE
    if not is_within(real, root):
        return SKIP_OUTSIDE_ROOT
    return None
