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


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


async def classify(page: Page, measurement: UiMeasurement, copilot_host: str) -> PageState:
    """One look at the page, without waiting."""
    if page.is_closed():
        return PageState.CLOSED
    try:
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
    except PlaywrightError:
        return PageState.CLOSED if page.is_closed() else PageState.UNKNOWN
    return PageState.UNKNOWN
