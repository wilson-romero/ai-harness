"""The dedicated Edge profile and its marker.

A directory is accepted only if it does not exist, is empty, or carries the marker the harness
writes when it creates it. A personal or everyday work profile is never empty and never has the
marker, so it cannot be used by mistake, and no platform-specific default path is needed.
"""

from __future__ import annotations

from pathlib import Path

from harness.browser.errors import ProfileRejected

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
    path.mkdir(parents=True, exist_ok=True)
    if not marker.is_file():
        marker.write_text(MARKER_TEXT, encoding="utf-8")
    return path
