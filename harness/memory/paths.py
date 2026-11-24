"""Path validation and the confined walk over the vault.

The validation functions are pure: they take `PurePath`s or strings and behave the same for
Windows and POSIX inputs on any platform. The walk is the only place that touches the file
system, and it never follows a link.
"""

from __future__ import annotations

import os
import re
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
)


# -- pure validation ----------------------------------------------------------------------------


def validate_project_slug(raw: str) -> str:
    """Accept only a simple folder name. Same answer and message on every platform."""
    if not _is_valid_slug(raw):
        raise InvalidProject(
            f"invalid project identifier {raw!r}: use the plain name of a folder under projects/"
        )
    return raw


def _is_valid_slug(raw: str) -> bool:
    if not _PROJECT_RE.fullmatch(raw) or raw in (".", ".."):
        return False
    if raw.endswith((".", " ")):
        return False
    stem = raw.split(".", 1)[0].upper()
    return stem not in _WINDOWS_RESERVED


def is_within(path: PurePath, root: PurePath) -> bool:
    """Containment with the path flavour's own rules (case-insensitive for Windows paths)."""
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

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
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
            files.append(VaultFile(entry, rel(entry), entry.lstat().st_size))
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
