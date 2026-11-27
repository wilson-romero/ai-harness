"""`copilot login`: open the dedicated profile visibly and wait for a person to sign in.

The command never fills, types, presses or clicks anything in the page. It only looks at the
page until it is ready to ask, or until the person closes the window. Once Copilot is ready it
records the shape of the path where that happened (`/chat`, never a conversation id) and, when
that is not the configured address, opens the configured address once more to check that it is
not Copilot's guest page.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page
from playwright.async_api import Error as PlaywrightError

from harness.browser.edge import EdgeLauncher
from harness.browser.errors import GuestAddress, NotSignedIn
from harness.browser.page_state import (
    PageState,
    classify,
    guest_page_advice,
    host_of,
    ready_path,
)
from harness.config import Settings
from harness.providers.copilot_ui import MEASUREMENT_DIR, UiMeasurement, load_measurement
from harness.storage.private import private_dir, private_file

POLL_S = 0.25
CHECK_S = 20.0  # how long the configured address may take to show the chat or the guest page
LOGIN_FILE = "login.json"


def login_path(data_dir: Path) -> Path:
    return data_dir / MEASUREMENT_DIR / LOGIN_FILE


def recorded_ready_path(data_dir: Path) -> str | None:
    """The path shape recorded by the last successful `copilot login`, if any."""
    try:
        value = json.loads(login_path(data_dir).read_text(encoding="utf-8")).get("ready_path")
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and value.startswith("/") else None


def _record_ready_path(data_dir: Path, path: str) -> None:
    target = login_path(data_dir)
    private_dir(target.parent)  # owner-only where the system uses permission bits (F-08)
    private_file(target)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    target.write_text(json.dumps({"ready_path": path, "recorded_at": stamp}) + "\n", "utf-8")


async def manual_login(settings: Settings, launcher: EdgeLauncher | None = None) -> None:
    """Return when Copilot is ready in the dedicated profile; raise NotSignedIn otherwise, or
    GuestAddress when the session is fine but the configured address shows the guest page."""
    url = settings.require_copilot_url()
    measurement = load_measurement(settings.data_dir)
    copilot_host = host_of(url)
    launcher = launcher or EdgeLauncher.from_settings(settings)
    async with launcher.open(wait_s=None) as context:
        page = context.pages[0] if context.pages else await context.new_page()
        with suppress(PlaywrightError):  # the person may close the window while it loads
            await page.goto(url)
        told_about_guest = False
        while True:
            pages = _open_pages(context)
            state = await classify(pages[-1], measurement, copilot_host) if pages else None
            if state is None or state is PageState.CLOSED:
                raise NotSignedIn(
                    "the Edge window was closed, or the browser stopped, before Copilot was "
                    "ready: not signed in. Run `copilot login` again and sign in in that window"
                )
            if state is PageState.READY:
                break
            if state is PageState.GUEST and not told_about_guest:
                told_about_guest = True
                print(
                    "This is Copilot's guest page. Sign in from it; if you are already signed "
                    "in, open the chat in this window (for example "
                    f"{host_of(url)}/chat) and the harness will say which address to configure.",
                    file=sys.stderr,
                )
            await asyncio.sleep(POLL_S)
        shape = ready_path(pages[-1].url)
        if shape is not None:
            _record_ready_path(settings.data_dir, shape)
        if shape is not None and shape != _path_of(url):
            await _check_configured_address(pages[-1], url, measurement, copilot_host, shape)


async def _check_configured_address(
    page: Page, url: str, measurement: UiMeasurement, copilot_host: str, shape: str
) -> None:
    """Copilot was ready somewhere else than the configured address: open that address once
    and refuse it if it is the guest page. Looking only, as everywhere else in this command."""
    with suppress(PlaywrightError):
        await page.goto(url)
    deadline = time.monotonic() + CHECK_S
    while time.monotonic() < deadline:
        state = await classify(page, measurement, copilot_host)
        if state is PageState.READY:
            return
        if state is PageState.GUEST:
            raise GuestAddress(
                "signed in: the session is saved in the dedicated profile. But "
                + guest_page_advice(url, shape)
            )
        if state is PageState.CLOSED:
            return  # the session is saved; the next command will check the address again
        await asyncio.sleep(POLL_S)


def _path_of(url: str) -> str:
    return urlsplit(url).path.rstrip("/") or "/"


def _open_pages(context: BrowserContext) -> list:
    return [page for page in context.pages if not page.is_closed()]
