"""Vault root, profile, the data directory binding and the work-profile location checks.

Nothing here is read unless a command needs the memory (`memory ...` or `ask --project`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePath

from harness.core.errors import (
    MemoryNotConfigured,
    ProfileBindingMismatch,
    SyncedLocationRefused,
)
from harness.memory.paths import is_network_path, is_within
from harness.storage import repositories as repo
from harness.storage.database import transaction

PROFILE_WORK = "work"
PROFILE_PERSONAL = "personal"
PROFILES = (PROFILE_WORK, PROFILE_PERSONAL)

CONTEXT_DEFAULT_BYTES = 8192
CONTEXT_MIN_BYTES = 1024
CONTEXT_MAX_BYTES = 65536

VAULT_ROOT_ENV = "HARNESS_VAULT_ROOT"
PROFILE_ENV = "HARNESS_PROFILE"
CONTEXT_BYTES_ENV = "HARNESS_MEMORY_CONTEXT_MAX_BYTES"

# Recognised sync folders (D3). Compared case-insensitively against each path component.
SYNC_COMPONENTS = ("cloudstorage", "mobile documents")
SYNC_COMPONENT_PREFIXES = ("onedrive", "dropbox", "google drive", "icloud drive")
SYNC_ROOT_VARIABLES = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")
SYNC_MARKERS = (".dropbox", ".stfolder", ".sync")
GIT_REMOTE_MARKER = ".git (with a remote)"


@dataclass(frozen=True)
class MemorySettings:
    vault_root: Path  # the real, resolved root
    profile: str
    context_max_bytes: int


def load_memory_settings(env: Mapping[str, str], data_dir: Path) -> MemorySettings:
    """Validate the memory configuration and, for `work`, where the vault and data live.

    Raises before any note is read. The order matters: everything that needs no file system
    access is checked first, so a refused path is refused by its reason, not by its absence.
    """
    raw_root = (env.get(VAULT_ROOT_ENV) or "").strip()
    if not raw_root:
        raise MemoryNotConfigured(f"{VAULT_ROOT_ENV} is not set; point it at the vault folder")
    profile = (env.get(PROFILE_ENV) or "").strip() or PROFILE_WORK
    if profile not in PROFILES:
        raise MemoryNotConfigured(
            f"{PROFILE_ENV} must be one of {', '.join(PROFILES)}, got {profile!r}"
        )
    max_bytes = _context_max_bytes(env)
    root = Path(raw_root)
    if not root.is_absolute():
        raise MemoryNotConfigured(f"{VAULT_ROOT_ENV} must be an absolute path")

    if profile == PROFILE_WORK:
        _refuse_if_synced("vault", root, {}, env)
    if not root.is_dir():
        raise MemoryNotConfigured(f"{VAULT_ROOT_ENV} does not exist or is not a directory")
    real_root = root.resolve(strict=True)
    if profile == PROFILE_WORK:
        _refuse_if_synced("vault", real_root, collect_markers(real_root), env)
        data_real = data_dir.resolve()
        _refuse_if_synced("data directory", data_dir.absolute(), {}, env)
        _refuse_if_synced("data directory", data_real, collect_markers(data_real), env)
    return MemorySettings(vault_root=real_root, profile=profile, context_max_bytes=max_bytes)


def _context_max_bytes(env: Mapping[str, str]) -> int:
    raw = (env.get(CONTEXT_BYTES_ENV) or "").strip()
    if not raw:
        return CONTEXT_DEFAULT_BYTES
    try:
        value = int(raw)
    except ValueError:
        raise MemoryNotConfigured(f"{CONTEXT_BYTES_ENV} must be an integer, got {raw!r}") from None
    if not CONTEXT_MIN_BYTES <= value <= CONTEXT_MAX_BYTES:
        raise MemoryNotConfigured(
            f"{CONTEXT_BYTES_ENV} must be between {CONTEXT_MIN_BYTES} and {CONTEXT_MAX_BYTES}"
        )
    return value


# -- data directory binding (D2) ----------------------------------------------------------------


def bind_data_dir(conn: sqlite3.Connection, settings: MemorySettings) -> None:
    """Bind the data directory to this profile and vault on first use; refuse a change later."""
    vault_root = str(settings.vault_root)
    with transaction(conn):
        bound = repo.get_memory_binding(conn)
        if bound is None:
            repo.insert_memory_binding(conn, settings.profile, vault_root)
            return
    _compare_binding(bound, settings.profile, vault_root)


def _compare_binding(bound: tuple[str, str], profile_now: str, vault_root: str) -> None:
    profile, bound_root = bound
    if profile != profile_now:
        raise ProfileBindingMismatch(
            f"this data directory is bound to the {profile!r} profile; "
            "use another HARNESS_DATA_DIR for a different profile"
        )
    if bound_root != vault_root:
        raise ProfileBindingMismatch(
            "this data directory is bound to another vault root; "
            "use another HARNESS_DATA_DIR for a different vault"
        )


# -- sync and network locations (D3) ------------------------------------------------------------


def location_refusal(
    path: PurePath,
    markers: Mapping[PurePath, frozenset[str]],
    env: Mapping[str, str],
) -> str | None:
    """Why a work vault or data directory may not live at `path`, or None if it may.

    Pure: `markers` says which sync markers exist in `path` and its ancestors (see
    `collect_markers`), and `env` is the environment to read the OneDrive variables from.
    """
    if is_network_path(path):
        return "it is a network path"
    for part in path.parts[1:] if path.anchor else path.parts:
        folded = part.casefold()
        if folded in SYNC_COMPONENTS or folded.startswith(SYNC_COMPONENT_PREFIXES):
            return f"the folder {part!r} is a recognised sync folder"
    for name in SYNC_ROOT_VARIABLES:
        value = (env.get(name) or "").strip()
        if not value:
            continue
        sync_root = type(path)(value)
        if sync_root.is_absolute() and is_within(path, sync_root):
            return f"it is under the folder named by the {name} variable"
    for directory in [path, *path.parents]:
        for marker in sorted(markers.get(directory, frozenset())):
            return f"{marker} in {directory.name or str(directory)!r} marks a synced folder"
    return None


def collect_markers(path: Path) -> dict[PurePath, frozenset[str]]:
    """Which sync markers exist in `path` and each of its ancestors. Reads, never writes."""
    found: dict[PurePath, frozenset[str]] = {}
    for directory in [path, *path.parents]:
        names = {marker for marker in SYNC_MARKERS if (directory / marker).exists()}
        if _git_has_remote(directory / ".git"):
            names.add(GIT_REMOTE_MARKER)
        if names:
            found[directory] = frozenset(names)
    return found


def _git_has_remote(dot_git: Path) -> bool:
    configs: list[Path] = []
    try:
        if dot_git.is_dir():
            configs.append(dot_git / "config")
        elif dot_git.is_file():
            # A worktree or submodule: `.git` names the real git directory.
            for line in dot_git.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("gitdir:"):
                    gitdir = Path(line.removeprefix("gitdir:").strip())
                    if not gitdir.is_absolute():
                        gitdir = dot_git.parent / gitdir
                    configs.append(gitdir / "config")
                    common = gitdir / "commondir"
                    if common.is_file():
                        shared = Path(common.read_text(encoding="utf-8").strip())
                        common_dir = shared if shared.is_absolute() else gitdir / shared
                        configs.append(common_dir / "config")
        for config in configs:
            if config.is_file() and "[remote" in config.read_text(
                encoding="utf-8", errors="replace"
            ):
                return True
    except OSError:
        return False
    return False


def _refuse_if_synced(
    what: str, path: PurePath, markers: Mapping[PurePath, frozenset[str]], env: Mapping[str, str]
) -> None:
    reason = location_refusal(path, markers, env)
    if reason:
        raise SyncedLocationRefused(
            f"the work profile does not use a {what} in a synced or network location: {reason}"
        )
