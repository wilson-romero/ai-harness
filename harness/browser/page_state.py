"""Classify the Copilot page as ready, login or unknown, using only the measurement.

Looking is all this module does: it reads the page URL's host name and whether the measured
controls are visible. It never fills, types, presses or reads the value of a field.
"""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from harness.providers.copilot_ui import UiMeasurement


class PageState(StrEnum):
    READY = "ready"
    LOGIN = "login"
    UNKNOWN = "unknown"
    CLOSED = "closed"


def is_target_gone(exc: PlaywrightError) -> bool:
    """The page, context or browser is gone: closed, or the driver behind it died.

    After the driver dies a page still says `is_closed() == False`, but every call raises
    Playwright's TargetClosedError, which `playwright.async_api` does not export by name.
    """
    return type(exc).__name__ == "TargetClosedError"


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


async def classify(page: Page, measurement: UiMeasurement, copilot_host: str) -> PageState:
    """One look at the page, without waiting."""
    if page.is_closed():
        return PageState.CLOSED
    try:
        await page.locator("html").count()  # a round trip: fails if the browser or driver is gone
        host = host_of(page.url)
        if host == copilot_host.lower():
            composer = measurement.locators.composer.resolve(page).first
            if await composer.is_visible() and await composer.is_enabled():
                return PageState.READY
        login = measurement.login
        if login is not None and host in login.hosts:
            return PageState.LOGIN
        indicator = measurement.locators.login_indicator
        if indicator is not None and await indicator.resolve(page).first.is_visible():
            return PageState.LOGIN
    except PlaywrightError as exc:
        return PageState.CLOSED if page.is_closed() or is_target_gone(exc) else PageState.UNKNOWN
    return PageState.UNKNOWN
