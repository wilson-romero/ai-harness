"""Choosing the work folder (workspace-tools D1, B1-1, B1-2).

A folder is refused when it is not absolute, is itself a link or a junction, is not a
directory, or when its resolved form is, is inside or contains the harness's repository, the
data directory or the vault; and when it is the home folder itself or a file-system root.
Containment is decided twice, by names (NFC and casefolded parts of the resolved paths) and by
identity (st_dev, st_ino of every ancestor): either says "yes" and the folder is refused.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from pathlib import Path

import harness
from harness.workspace.codes import WorkspaceRefused
from harness.workspace.paths import Root, fold, is_link

HARNESS_REPO = Path(harness.__file__).resolve().parent.parent
_LABELS = {"harness_repo": "the harness's repository", "data_dir": "the data directory",
           "vault": "the vault"}


def _resolved(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return Path(os.path.abspath(path))


def _folded_parts(path: Path) -> tuple[str, ...]:
    return tuple(fold(part) for part in path.parts)


def _inside_by_name(inner: Path, outer: Path) -> bool:
    a, b = _folded_parts(inner), _folded_parts(outer)
    return len(a) >= len(b) and a[: len(b)] == b


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_dev, info.st_ino)


def _ancestor_identities(path: Path) -> set[tuple[int, int]]:
    found = set()
    for each in (path, *path.parents):
        identity = _identity(each)
        if identity is not None:
            found.add(identity)
    return found


def _overlaps(candidate: Path, protected: Path) -> bool:
    """`candidate` is, is inside or contains `protected`, by name or by identity."""
    if _inside_by_name(candidate, protected) or _inside_by_name(protected, candidate):
        return True
    mine, theirs = _identity(candidate), _identity(protected)
    if theirs is not None and theirs in _ancestor_identities(candidate):
        return True
    return mine is not None and mine in _ancestor_identities(protected)


def _same(candidate: Path, other: Path) -> bool:
    if _folded_parts(candidate) == _folded_parts(other):
        return True
    mine = _identity(candidate)
    return mine is not None and mine == _identity(other)


def protected_folders(data_dir: Path, environ: Mapping[str, str]) -> list[tuple[str, Path]]:
    folders = [("harness_repo", HARNESS_REPO), ("data_dir", _resolved(data_dir))]
    vault = (environ.get("HARNESS_VAULT_ROOT") or "").strip()
    if vault:
        folders.append(("vault", _resolved(Path(vault))))
    return folders


def check_root(raw: str, *, data_dir: Path, environ: Mapping[str, str]) -> Root:
    """The accepted work folder, or `WorkspaceRefused` with the first rule it breaks."""
    if not raw or "\x00" in raw or not Path(raw).is_absolute():
        raise WorkspaceRefused("not_absolute", "the work folder must be an absolute path")
    given = Path(raw)
    try:
        info = os.lstat(given)
    except OSError:
        raise WorkspaceRefused("root_not_found", "the work folder does not exist") from None
    if stat.S_ISLNK(info.st_mode) or is_link(given):
        raise WorkspaceRefused("link", "the work folder must not be a link or a junction")
    if not stat.S_ISDIR(info.st_mode):
        raise WorkspaceRefused("not_a_directory", "the work folder must be a folder")
    try:
        resolved = given.resolve(strict=True)
    except OSError:
        raise WorkspaceRefused("root_not_found", "the work folder cannot be resolved") from None
    for code, folder in protected_folders(data_dir, environ):
        if _overlaps(resolved, folder):
            raise WorkspaceRefused(code, "the work folder must not be, be inside or contain "
                                         f"{_LABELS[code]}")
    if _same(resolved, _resolved(Path.home())):
        raise WorkspaceRefused("home", "choose a folder inside your home folder, not the home "
                                       "folder itself")
    if resolved.parent == resolved:
        raise WorkspaceRefused("filesystem_root", "a file-system root is not a work folder")
    final = os.stat(resolved)
    return Root(resolved, final.st_dev, final.st_ino)
