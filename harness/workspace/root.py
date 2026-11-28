"""Choosing the work folder (workspace-tools D1, B1-1, B1-2).

A folder is refused when it is a network or device path (it starts with two separators: a
UNC share, a device path, `//x`), is not absolute, is itself a link or a junction, is not a directory, or when its
resolved form is, is inside or contains the harness's repository, the data directory or the
vault; when it is or contains the home folder; when it is a file-system root; and when it is a
mount point (its st_dev differs from its parent's). Containment is decided three ways, and any
"yes" refuses the folder:

- by names (NFC and casefolded parts of the resolved paths);
- by identity (st_dev, st_ino) of every ancestor;
- by a second path (review of d0a65d8, finding 1): the same directories can be reachable under
  another name, which neither of the two above sees. On macOS `/System/Volumes/Data/Users` is
  `/Users` (an APFS firmlink: same st_dev and st_ino, and `/System/Volumes/Data` has the same
  st_dev as `/`, so it is no mount point by st_dev either); on Linux a bind mount does the
  same. So the candidate and its subfolders down to `MIRROR_SEARCH_DEPTH` levels are searched,
  without following links, for each tail of a protected folder's path (`Users/<name>/...`,
  `<name>/...`, ...) whose identity is the protected folder's. At most `MIRROR_SEARCH_DIRS`
  folders are listed: past that the search stops and says nothing (a limit, written in
  design B1-6).
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


# How far and how wide the search for a second path goes (B1-6). `/System` reaches the
# repository through `Volumes/Data/Users/...`: the tail's first name is found two levels down.
MIRROR_SEARCH_DEPTH = 2
MIRROR_SEARCH_DIRS = 2000
_SEPARATORS = "/\\"


def _children(folder: Path) -> list[os.DirEntry]:
    try:
        with os.scandir(folder) as entries:
            return sorted(entries, key=lambda entry: entry.name)
    except OSError:
        return []


def _real_folder(entry: os.DirEntry) -> bool:
    try:
        return entry.is_dir(follow_symlinks=False) and not is_link(Path(entry.path))
    except OSError:
        return False


def _second_path(candidate: Path, protected: list[tuple[str, Path]]) -> str | None:
    """The code of a protected folder that the candidate reaches under another name: a path
    `D/<tail>` where D is the candidate or one of its subfolders and <tail> is the end of the
    protected folder's own path, with the protected folder's identity."""
    tails: dict[str, list[tuple[tuple[str, ...], tuple[int, int], str]]] = {}
    for code, folder in protected:
        identity = _identity(folder)
        if identity is None:
            continue
        parts = folder.parts[1:]  # without the anchor
        for start in range(len(parts)):
            tail = parts[start:]
            tails.setdefault(fold(tail[0]), []).append((tail, identity, code))
    if not tails:
        return None
    pending, listed = [(candidate, 0)], 0
    while pending and listed < MIRROR_SEARCH_DIRS:
        folder, level = pending.pop(0)
        listed += 1
        for entry in _children(folder):
            if not _real_folder(entry):
                continue
            for tail, identity, code in tails.get(fold(entry.name), ()):
                if _identity(folder.joinpath(*tail)) == identity:
                    return code
            if level < MIRROR_SEARCH_DEPTH:
                pending.append((Path(entry.path), level + 1))
    return None


def _network_or_device(text: str) -> bool:
    """A path that starts with two separators, `/` or `\\` in any mix: a UNC share
    (`\\\\server\\share`, `\\\\localhost\\C$`), a device path (`\\\\?\\GLOBALROOT\\...`,
    `\\\\.\\...`) or `//x`. Through them the same volume is reachable under another name, so
    none is a work folder. The long form of a local drive (`\\\\?\\C:\\...`, which `resolve`
    may give for a long path on Windows) is not one."""
    if len(text) < 2 or text[0] not in _SEPARATORS or text[1] not in _SEPARATORS:
        return False
    rest = text[2:]
    return not (len(rest) >= 4 and rest[0] == "?" and rest[1] in _SEPARATORS
                and rest[2].isascii() and rest[2].isalpha() and rest[3] == ":")


def _contains(candidate: Path, inner: Path) -> bool:
    """`candidate` contains `inner`, by name or by identity of `inner`'s ancestors."""
    if _inside_by_name(inner, candidate):
        return True
    mine = _identity(candidate)
    return mine is not None and mine in _ancestor_identities(inner)


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
    if raw and _network_or_device(raw):
        raise WorkspaceRefused("device_path", "a network share or a device path is not a work "
                                              "folder; choose a folder of a local drive")
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
    if _network_or_device(str(resolved)):
        raise WorkspaceRefused("device_path", "the work folder resolves to a network share or a "
                                              "device path; choose a folder of a local drive")
    protected = protected_folders(data_dir, environ)
    for code, folder in protected:
        if _overlaps(resolved, folder):
            raise WorkspaceRefused(code, "the work folder must not be, be inside or contain "
                                         f"{_LABELS[code]}")
    if resolved.parent == resolved:
        raise WorkspaceRefused("filesystem_root", "a file-system root is not a work folder")
    home = _resolved(Path.home())
    if _same(resolved, home) or _contains(resolved, home):
        raise WorkspaceRefused("home", "choose a folder inside your home folder, not the home "
                                       "folder itself or one that contains it")
    reached = _second_path(resolved, [*protected, ("home", home)])
    if reached is not None:
        raise WorkspaceRefused(reached, "the work folder reaches "
                                        f"{_LABELS.get(reached, 'the home folder')} under "
                                        "another path (a mirror of the same folders)")
    mine, parent = _identity(resolved), _identity(resolved.parent)
    if mine is not None and parent is not None and mine[0] != parent[0]:
        raise WorkspaceRefused("mount_point", "the work folder is a mount point (a volume of its "
                                              "own); choose a folder inside it")
    final = os.stat(resolved)
    return Root(resolved, final.st_dev, final.st_ino)
