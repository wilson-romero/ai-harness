"""`copilot login`: open the dedicated profile visibly and wait for a person to sign in.

The command never fills, types, presses or clicks anything in the page. It only looks at the
page until it is ready to ask, or until the person closes the window.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

from playwright.async_api import BrowserContext
from playwright.async_api import Error as PlaywrightError

from harness.browser.edge import EdgeLauncher
from harness.browser.errors import NotSignedIn
from harness.browser.page_state import PageState, classify, host_of
from harness.config import Settings
from harness.providers.copilot_ui import load_measurement

POLL_S = 0.25


async def manual_login(settings: Settings, launcher: EdgeLauncher | None = None) -> None:
    """Return when Copilot is ready in the dedicated profile; raise NotSignedIn otherwise."""
    url = settings.require_copilot_url()
    measurement = load_measurement(settings.data_dir)
    copilot_host = host_of(url)
    launcher = launcher or EdgeLauncher.from_settings(settings)
    async with launcher.open(wait_s=None) as context:
        page = context.pages[0] if context.pages else await context.new_page()
        with suppress(PlaywrightError):  # the person may close the window while it loads
            await page.goto(url)
        while True:
            pages = _open_pages(context)
            state = await classify(pages[-1], measurement, copilot_host) if pages else None
            if state is None or state is PageState.CLOSED:
                raise NotSignedIn(
                    "the Edge window was closed, or the browser stopped, before Copilot was "
                    "ready: not signed in. Run `copilot login` again and sign in in that window"
                )
            if state is PageState.READY:
                return
            await asyncio.sleep(POLL_S)


def _open_pages(context: BrowserContext) -> list:
    return [page for page in context.pages if not page.is_closed()]
