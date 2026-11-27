"""Classify the Copilot page as ready, login or unknown, using only the measurement.

Looking is all this module does: it reads the page URL's host name and whether the measured
controls are visible. It never fills, types, presses or reads the value of a field.
"""

from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

from harness.providers.copilot_ui import UiMeasurement


class PageState(StrEnum):
    READY = "ready"
    LOGIN = "login"
    GUEST = "guest"  # on the Copilot host, but the page offers to sign in
    UNKNOWN = "unknown"
    CLOSED = "closed"


# Visible elements whose id, class or data-* attribute names a sign-in or a signed-out state
# (`unauth…`, `sign-in`, `login`, camelCase split first). Only attribute names and values the
# page's authors wrote are read, never the page's text.
SIGNED_OUT_HINTS_JS = r"""
() => {
  const HINT = /(^|[^a-z])(unauth\w*|sign[-_ ]?in|log[-_ ]?in)([^a-z]|$)/i;
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none"; };
  let n = 0;
  for (const el of document.querySelectorAll("*")) {
    if (!visible(el)) continue;
    for (const a of el.attributes) {
      if (!(a.name === "id" || a.name === "class" || a.name.startsWith("data-"))) continue;
      if (HINT.test(a.value.replace(/([a-z])([A-Z])/g, "$1 $2"))) { n += 1; break; }
    }
  }
  return n;
}
"""

_PLAIN_SEGMENT = re.compile(r"[a-z][a-z-]{0,30}")


async def signed_out_hints(page: Page) -> int:
    return int(await page.evaluate(SIGNED_OUT_HINTS_JS))


def ready_path(url: str) -> str | None:
    """The shape of the path where Copilot was ready: its first segment when it is a plain
    word (`/chat`), else the root. Deeper segments name a conversation and are never kept."""
    first = next((s for s in urlsplit(url).path.split("/") if s), "")
    if not first:
        return "/"
    return f"/{first}" if _PLAIN_SEGMENT.fullmatch(first) else None


def address(url: str, path: str | None = None) -> str:
    """Scheme, host and path of an address, without query or fragment."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path if path is None else path}"


def guest_page_advice(configured_url: str, chat_path: str | None) -> str:
    """What to do when the configured address shows Copilot's guest page."""
    here = address(configured_url)
    if chat_path and chat_path != (urlsplit(configured_url).path.rstrip("/") or "/"):
        fix = f"set HARNESS_COPILOT_URL={address(configured_url, chat_path)}"
        where = f"the chat was ready at {chat_path} when this profile signed in"
    else:
        example = address(configured_url, "/chat")
        fix = f"set HARNESS_COPILOT_URL to the address where the chat appears (for example {example})"
        where = "the signed-in chat usually lives under a path of the same host"
    return (
        f"HARNESS_COPILOT_URL ({here}) opens Copilot's guest page, which offers to sign in "
        f"even when the profile has a valid session: {where}. To fix it, {fix}"
    )


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
            if await signed_out_hints(page):
                return PageState.GUEST  # a guest prompt box is not the chat
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
