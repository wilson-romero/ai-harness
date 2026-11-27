"""The dedicated Edge profile and its marker.

A directory is accepted only if it does not exist, is empty, or carries the marker the harness
writes when it creates it. A personal or everyday work profile is never empty and never has the
marker, so it cannot be used by mistake, and no platform-specific default path is needed.

The directory holds the session cookies. With the basic password store (design D3) they are
encrypted with a fixed key, so whoever can read the directory can use the session: it is made
readable by its owner only (mode 0700) where the system has mode bits. On Windows `os.chmod`
only clears a read-only flag; there the directory inherits the ACL of its parent, which is why
the data directory belongs on a local disk of the user.
"""

from __future__ import annotations

import os
from pathlib import Path

from harness.browser.errors import ProfileRejected
from harness.storage.private import private_dir

PROFILE_MARKER = "ai-harness-profile.txt"
MARKER_TEXT = (
    "This directory is a dedicated Microsoft Edge profile created by ai-harness.\n"
    "Do not point it at a personal or work profile.\n"
)


def prepare_profile(path: Path) -> Path:
    """Return the profile directory, creating it with its marker if needed."""
    marker = path / PROFILE_MARKER
    if path.exists() and not path.is_dir():
        raise ProfileRejected(f"{path} is not a directory; HARNESS_EDGE_PROFILE must be one")
    if path.is_dir() and not marker.is_file() and any(path.iterdir()):
        raise ProfileRejected(
            f"{path} is not an ai-harness Edge profile: it has files and no {PROFILE_MARKER}. "
            "Set HARNESS_EDGE_PROFILE to a new or empty directory"
        )
    private_dir(path)  # and its missing parents (security review 2026-11-27, F-08)
    os.chmod(path, 0o700)  # mkdir's mode yields to the umask, and an older profile may be wider
    if not marker.is_file():
        marker.write_text(MARKER_TEXT, encoding="utf-8")
    return path
