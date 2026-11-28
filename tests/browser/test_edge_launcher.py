"""The launcher: installed Edge, dedicated profile, one browser at a time, only its own closed."""

import asyncio
import os
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from harness.browser.edge import (
    DROPPED_DEFAULT_ARGS,
    PROFILE_LOCK_ARTEFACTS,
    EdgeLauncher,
    edge_version,
)
from harness.browser.errors import BrowserBusy, BrowserLaunchFailed, ProfileInUse, ProfileRejected
from harness.storage.locks import NamedLock
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.edge

# Stands for "the user's own Edge": another process, another profile, launched separately.
OTHER_EDGE = """
import asyncio, os, sys
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            os.environ["OTHER_EDGE_PROFILE"], channel="msedge", headless=True)
        page = context.pages[0] if context.pages else await context.new_page()
        print("ready", flush=True)
        await asyncio.to_thread(sys.stdin.readline)
        try:
            alive = await page.evaluate("1 + 1") == 2
        except Exception:
            alive = False
        print("alive" if alive else "gone", flush=True)
        try:
            await context.close()
        except Exception:
            pass

asyncio.run(main())
"""


@pytest.fixture
def launcher(tmp_path) -> EdgeLauncher:
    return EdgeLauncher(tmp_path / "data", tmp_path / "edge-profile", headless=True)


def spy_launches(monkeypatch) -> list[Path]:
    calls: list[Path] = []
    original = EdgeLauncher._launch

    async def spy(self, playwright, profile):
        calls.append(profile)
        return await original(self, playwright, profile)

    monkeypatch.setattr(EdgeLauncher, "_launch", spy)
    return calls


async def test_installed_edge_opens_a_synthetic_page_and_reads_its_title(launcher, copilot_app):
    async with launcher.open() as context:
        page = context.pages[0]
        await page.goto(copilot_app.url())
        assert (await page.title()).startswith("Synthetic chat")
        assert edge_version(context)
    assert launcher.contexts == []


async def command_line(launcher) -> list[str]:
    """The browser's own version page reports the command line it was started with."""
    async with launcher.open() as context:
        page = context.pages[0]
        await page.goto("edge://version")
        switches = (await page.locator("#command_line").inner_text()).split()
    assert any(s.startswith("--remote-debugging-pipe") for s in switches)  # it is ours
    return switches


async def test_edge_runs_with_its_sandbox_on(launcher):
    """Playwright starts Chromium-family browsers with `--no-sandbox` unless told otherwise."""
    assert "--no-sandbox" not in await command_line(launcher)


async def test_background_protections_are_not_switched_off(launcher):
    """The Playwright defaults the harness drops are really gone, and only those: the rest of
    Playwright's switches are still there, so the filter is exact."""
    switches = await command_line(launcher)
    for dropped in DROPPED_DEFAULT_ARGS:
        assert dropped not in switches
    assert "--no-first-run" in switches  # an untouched Playwright default


async def test_unknown_channel_fails_with_a_controlled_error(tmp_path):
    broken = EdgeLauncher(
        tmp_path / "data", tmp_path / "edge-profile", headless=True, channel="msedge-nonexistent"
    )
    started = time.monotonic()
    with pytest.raises(BrowserLaunchFailed, match="could not be started") as error:
        async with asyncio.timeout(60):
            async with broken.open():
                pass
    assert time.monotonic() - started < 30
    assert str(tmp_path) not in str(error.value)


async def test_foreign_profile_is_rejected_before_edge_is_launched(tmp_path, monkeypatch):
    calls = spy_launches(monkeypatch)
    profile = tmp_path / "someone-elses-profile"
    profile.mkdir()
    (profile / "Local State").write_text("{}", encoding="utf-8")
    foreign = EdgeLauncher(tmp_path / "data", profile, headless=True)
    with pytest.raises(ProfileRejected):
        async with foreign.open():
            pass
    assert calls == []


async def test_two_concurrent_opens_never_have_two_browsers(launcher, monkeypatch):
    calls = spy_launches(monkeypatch)

    async def use_browser() -> None:
        async with launcher.open(wait_s=60):
            await asyncio.sleep(1.0)

    await asyncio.gather(use_browser(), use_browser())
    assert len(calls) == 2  # both got the browser, one after the other
    assert launcher.peak_open == 1
    assert launcher.contexts == []


async def test_busy_browser_fails_at_once_without_waiting(launcher, monkeypatch):
    calls = spy_launches(monkeypatch)
    holder = NamedLock(launcher.data_dir, "browser")
    assert holder.acquire()
    try:
        started = time.monotonic()
        with pytest.raises(BrowserBusy, match="in use"):
            async with launcher.open():
                pass
        assert time.monotonic() - started < 1
        with pytest.raises(BrowserBusy):
            async with launcher.open(wait_s=0.6):
                pass
        assert 0.5 <= time.monotonic() - started < 5
    finally:
        holder.release()
    assert calls == []


async def test_profile_open_in_another_edge_is_reported_as_in_use(launcher):
    async with launcher.open():
        pass  # create the dedicated profile with its marker
    async with async_playwright() as playwright:
        by_hand = await playwright.chromium.launch_persistent_context(
            str(launcher.profile_dir), channel="msedge", headless=True
        )
        try:
            with pytest.raises(ProfileInUse, match="already open") as error:
                async with launcher.open():
                    pass
            assert str(launcher.profile_dir) not in str(error.value)
        finally:
            await by_hand.close()


async def test_a_held_profile_carries_a_lock_artefact(launcher):
    """The premise of the launcher's 'in use' rule (P8, revised 2026-11-27): while an Edge
    holds the profile, at least one of the artefacts the rule looks for is in it, and none is
    left once that Edge has closed. The names found are printed for the Windows receipt."""
    async with launcher.open():
        pass
    held = lambda: [name for name in PROFILE_LOCK_ARTEFACTS  # noqa: E731
                    if os.path.lexists(launcher.profile_dir / name)]
    async with async_playwright() as playwright:
        by_hand = await playwright.chromium.launch_persistent_context(
            str(launcher.profile_dir), channel="msedge", headless=True
        )
        try:
            while_open = held()
        finally:
            await by_hand.close()
    print(f"lock artefacts while open: {while_open}")
    assert while_open
    for _ in range(50):  # the holder may take a moment to remove its artefact
        if not held():
            break
        await asyncio.sleep(0.1)
    assert held() == []


async def test_users_edge_survives_when_the_harness_loses_its_own(
    launcher, copilot_app, tmp_path_factory
):
    other_profile = tmp_path_factory.mktemp("users-edge-profile")
    other = subprocess.Popen(
        [sys.executable, "-c", OTHER_EDGE],
        cwd=REPO_ROOT,
        env={**os.environ, "OTHER_EDGE_PROFILE": str(other_profile)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert other.stdout.readline().strip() == "ready"
        async with launcher.open() as context:
            page = context.pages[0]
            await page.goto(copilot_app.url())
            cdp = await context.new_cdp_session(page)
            with suppress(Exception):
                await cdp.send("Browser.close")  # our browser goes away under our feet
            for _ in range(50):
                if page.is_closed():
                    break
                await asyncio.sleep(0.1)
            assert page.is_closed()
        assert launcher.contexts == []
        other.stdin.write("check\n")
        other.stdin.flush()
        assert other.stdout.readline().strip() == "alive"
        async with launcher.open():  # and the dedicated profile is free again
            pass
    finally:
        other.kill()
        other.wait(timeout=30)


async def test_cancelled_use_closes_the_browser_and_frees_the_profile(launcher):
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(1.0):
            async with launcher.open():
                await asyncio.sleep(30)
    assert launcher.contexts == []
    async with launcher.open():
        pass
