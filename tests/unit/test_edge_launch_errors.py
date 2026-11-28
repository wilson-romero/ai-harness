"""How a failed Edge launch is reported (copilot-web-provider P8, revised 2026-11-27).

The shapes are the ones each system gave for a second launch on a profile another Edge holds:
macOS names the process singleton; Windows hands the command line to the Edge that holds the
profile, and Playwright only sees the browser close at once. Both are fed here on every
system, with the lock artefacts a held profile carries on either system.
"""

from __future__ import annotations

import pytest
from playwright.async_api import Error as PlaywrightError

from harness.browser.edge import launch_error
from harness.browser.errors import BrowserLaunchFailed, ProfileInUse
from tests.conftest import make_symlink

CALL_LOG = ("\nCall log:\n  - <launching> msedge --no-first-run --user-data-dir={profile} "
            "--remote-debugging-pipe about:blank\n")
# macOS arm64, Edge 158 (P8, 2026-11-24): the first line of Playwright's error.
MACOS_SINGLETON = ("BrowserType.launch_persistent_context: Failed to create a ProcessSingleton "
                   "for your profile directory. This usually means that the profile is already "
                   "in use by another instance of Chromium.")
# Playwright's own wording when the browser log says it went to the running browser.
EXISTING_SESSION = ("BrowserType.launch_persistent_context: Opening in existing browser session. "
                    "This usually means that the profile is already in use by another instance "
                    "of Chromium.")
# Windows 11, develop 79cde60 (2026-11-27), two runs.
WINDOWS_CLOSED = ("BrowserType.launch_persistent_context: Target page, context or browser has "
                  "been closed")
OTHER_FAILURE = ("BrowserType.launch_persistent_context: Chromium distribution 'msedge' is not "
                 "found at /opt/USER/msedge")


class TargetClosedError(PlaywrightError):
    """The shape of Playwright's own class (not exported by `playwright.async_api`)."""


def _error(text: str, profile, cls=PlaywrightError) -> PlaywrightError:
    return cls(text + CALL_LOG.format(profile=profile))


def _hold(profile, artefact: str) -> None:
    if artefact == "lockfile":
        (profile / "lockfile").write_bytes(b"")  # Windows: kept open by the holder
    elif artefact == "SingletonLock link":
        make_symlink(profile / "SingletonLock", profile / "host-12345")  # POSIX: a dangling link
    elif artefact == "SingletonLock file":
        (profile / "SingletonLock").write_bytes(b"")


@pytest.fixture
def profile(tmp_path):
    path = tmp_path / "edge-profile"
    path.mkdir()
    return path


def _in_use(error, profile) -> None:
    assert isinstance(error, ProfileInUse)
    assert "already open" in str(error)
    assert str(profile) not in str(error)


@pytest.mark.parametrize("text", [MACOS_SINGLETON, EXISTING_SESSION])
def test_a_named_singleton_failure_is_in_use_with_or_without_artefacts(profile, text):
    _in_use(launch_error(_error(text, profile), profile), profile)


@pytest.mark.parametrize("artefact", ["lockfile", "SingletonLock link", "SingletonLock file"])
@pytest.mark.parametrize("cls", [PlaywrightError, TargetClosedError])
def test_an_immediate_close_on_a_held_profile_is_in_use(profile, artefact, cls):
    _hold(profile, artefact)
    _in_use(launch_error(_error(WINDOWS_CLOSED, profile, cls), profile), profile)


def test_an_immediate_close_on_a_free_profile_is_a_launch_failure(profile):
    """Negative control: the close alone is not enough."""
    (profile / "ai-harness-profile.txt").write_text("marker\n", encoding="utf-8")
    error = launch_error(_error(WINDOWS_CLOSED, profile, TargetClosedError), profile)
    assert isinstance(error, BrowserLaunchFailed)
    assert "has been closed" in str(error) and str(profile) not in str(error)


@pytest.mark.parametrize("artefact", ["lockfile", "SingletonLock file"])
def test_another_failure_on_a_held_profile_is_a_launch_failure(profile, artefact):
    """Negative control: the artefact alone is not enough either."""
    _hold(profile, artefact)
    error = launch_error(_error(OTHER_FAILURE, profile), profile)
    assert isinstance(error, BrowserLaunchFailed)
    assert "is not found" in str(error)


@pytest.mark.parametrize("artefact", ["lockfile", "SingletonLock link"])
def test_in_use_by_an_immediate_close_keeps_edges_message_and_names_a_stale_lock(
        profile, artefact):
    """A lock left by an Edge that crashed, with an unrelated close at launch, also reads as
    'in use': the report says so and keeps what Playwright said (review of 2026-11-27)."""
    _hold(profile, artefact)
    error = launch_error(_error(WINDOWS_CLOSED, profile, TargetClosedError), profile)
    _in_use(error, profile)
    assert "Target page, context or browser has been closed" in str(error)
    assert "crashed" in str(error)


def test_in_use_by_a_named_singleton_keeps_edges_message(profile):
    error = launch_error(_error(MACOS_SINGLETON, profile), profile)
    _in_use(error, profile)
    assert "Failed to create a ProcessSingleton" in str(error)
