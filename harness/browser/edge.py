"""Launch the installed Microsoft Edge on the dedicated profile, one browser at a time.

Playwright drives the Edge that is already installed (`channel="msedge"`); nothing is
downloaded. No recording option of any kind is passed: no screenshots, traces, HAR or video.
The harness only ever closes the context it obtained from Playwright. It never looks for,
signals or kills browser processes by name or by PID.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import BrowserContext, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

from harness.browser.errors import BrowserBusy, BrowserLaunchFailed, ProfileInUse
from harness.browser.profile import prepare_profile
from harness.config import Settings
from harness.storage.locks import NamedLock

BROWSER_LOCK = "browser"
EDGE_CHANNEL = "msedge"
LAUNCH_TIMEOUT_MS = 60_000
CLOSE_TIMEOUT_S = 10.0
LOCK_POLL_S = 0.25
# Measured (P8, macOS arm64, Edge 158): a second launch on a profile already open fails at
# once with this text in Playwright's error.
PROFILE_IN_USE_MARKERS = ("ProcessSingleton", "profile is already in use")


class EdgeLauncher:
    """Opens Edge on the dedicated profile while holding the `browser` lock."""

    def __init__(
        self,
        data_dir: Path,
        profile_dir: Path,
        *,
        headless: bool = False,
        channel: str = EDGE_CHANNEL,
    ) -> None:
        self.data_dir = data_dir
        self.profile_dir = profile_dir
        self.headless = headless
        self.channel = channel
        # Contexts this launcher has open right now, and the most browsers it ever had
        # starting or open at the same time.
        self.contexts: list[BrowserContext] = []
        self.peak_open = 0
        self._starting_or_open = 0

    @classmethod
    def from_settings(cls, settings: Settings) -> EdgeLauncher:
        profile = settings.edge_profile or settings.data_dir / "edge-profile"
        return cls(settings.data_dir, profile, headless=settings.browser_headless)

    @asynccontextmanager
    async def open(self, *, wait_s: float | None = None) -> AsyncIterator[BrowserContext]:
        """Yield a browser context on the dedicated profile and always close it afterwards.

        With `wait_s=None` a busy browser fails at once; otherwise the lock is polled until
        `wait_s` runs out. The profile is checked before anything else happens.
        """
        profile = prepare_profile(self.profile_dir)
        lock = NamedLock(self.data_dir, BROWSER_LOCK)
        acquired = lock.acquire() if wait_s is None else await lock.acquire_within(wait_s, LOCK_POLL_S)
        if not acquired:
            raise BrowserBusy(
                "the harness browser is in use by another command; wait for it to finish"
            )
        try:
            self._starting_or_open += 1
            self.peak_open = max(self.peak_open, self._starting_or_open)
            async with async_playwright() as playwright:
                context = await self._launch(playwright, profile)
                self.contexts.append(context)
                try:
                    yield context
                finally:
                    self.contexts.remove(context)
                    await close_owned(context)
        finally:
            self._starting_or_open -= 1
            lock.release()

    async def _launch(self, playwright: Playwright, profile: Path) -> BrowserContext:
        try:
            return await playwright.chromium.launch_persistent_context(
                str(profile),
                channel=self.channel,
                headless=self.headless,
                timeout=LAUNCH_TIMEOUT_MS,
            )
        except PlaywrightError as exc:
            raise launch_error(exc, profile) from None


def launch_error(exc: PlaywrightError, profile: Path) -> ProfileInUse | BrowserLaunchFailed:
    message = str(exc)
    if any(marker in message for marker in PROFILE_IN_USE_MARKERS):
        return ProfileInUse(
            "the dedicated Edge profile is already open in another Edge window; "
            "close that window and try again"
        )
    # Only the first line: the rest is Playwright's call log, with the full command line.
    first_line = message.splitlines()[0] if message else type(exc).__name__
    return BrowserLaunchFailed(
        f"Microsoft Edge could not be started: {first_line.replace(str(profile), '<profile>')}"
    )


def edge_version(context: BrowserContext) -> str | None:
    browser = context.browser
    return browser.version if browser is not None else None


async def close_owned(context: BrowserContext) -> None:
    """Close the context this command opened, within its own deadline, even if the caller is
    being cancelled. A browser that is already gone is not an error."""
    closing = asyncio.ensure_future(_close_quietly(context))
    try:
        await asyncio.shield(closing)
    except asyncio.CancelledError:
        await asyncio.wait({closing}, timeout=CLOSE_TIMEOUT_S)
        raise


async def _close_quietly(context: BrowserContext) -> None:
    try:
        async with asyncio.timeout(CLOSE_TIMEOUT_S):
            await context.close()
    except PlaywrightError, TimeoutError:
        pass  # already closed or crashed; leaving the Playwright block stops its driver anyway
