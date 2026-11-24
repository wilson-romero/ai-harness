"""Refuse a local file that Git could version (the repository is public).

A file that holds local paths or names (the MCP allowlist) must never be one `git add` away
from a public commit. The check asks Git itself, so `.gitignore`, `info/exclude` and the global
excludes all count. Git runs with no pipes (every stream to the null device) and a bounded
wait, so no descendant can hold a pipe open and stall the wait (the Windows lesson of
2026-11-24). Without a usable `git`, the parent directories are searched for a `.git` entry and
any work tree found is refused, since whether it ignores the file cannot be asked.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

GIT_TIMEOUT_S = 10.0


class VersionableFile(Exception):
    """The file is inside a Git work tree and not ignored (or that cannot be ruled out)."""


def ensure_not_versionable(path: Path) -> None:
    """Raise `VersionableFile` unless Git could not version `path` (absolute and resolved)."""
    directory = path.parent
    inside = _git(["rev-parse", "--show-toplevel"], directory)
    if inside is None:
        if _has_git_entry_above(directory):
            raise VersionableFile("it is inside a Git work tree and Git is not available to check it")
        return
    if inside != 0:
        return  # not inside a work tree
    ignored = _git(["check-ignore", "-q", "--", path.name], directory)
    if ignored != 0:
        raise VersionableFile("it is inside a Git work tree and not ignored")


def _git(arguments: list[str], cwd: Path) -> int | None:
    """Exit code of `git <arguments>` in `cwd`, or None if Git cannot be run or does not end."""
    try:
        process = subprocess.Popen(
            ["git", "-c", "core.fsmonitor=false", *arguments],
            cwd=cwd,
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    deadline = time.monotonic() + GIT_TIMEOUT_S
    try:
        while (code := process.poll()) is None:
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.02)
        return code
    finally:
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass


def _has_git_entry_above(directory: Path) -> bool:
    for candidate in (directory, *directory.parents):
        if (candidate / ".git").exists():
            return True
    return False
