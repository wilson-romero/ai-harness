"""The structure reported when the Copilot page is not ready in time, and the reason that
travels with a cancellation (Windows parity 3, review findings 2 and 5). Stub pages, no
browser: the order of events is explicit."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from playwright.async_api import Error as PlaywrightError

from harness.browser.page_state import PageState
from harness.config import Settings
from harness.core.contracts import LLMRequest
from harness.providers import copilot_web
from harness.providers.base import ProviderTimeout, timeout_on_its_way
from harness.providers.copilot_ui import measurement_path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "copilot_ui"
HANG_S = 30.0


class Element:
    def __init__(self, *, count=1, visible=True, enabled=True, hang=(), fail=()):
        self._count, self._visible, self._enabled = count, visible, enabled
        self.hang, self.fail = set(hang), set(fail)
        self.first = self
        self.timeouts: list[float | None] = []

    async def _answer(self, what, value):
        if what in self.fail:
            raise PlaywrightError("Target page, context or browser has been closed")
        if what in self.hang:
            await asyncio.sleep(HANG_S)  # a busy renderer, or an element removed meanwhile
        return value

    async def count(self):
        return await self._answer("count", self._count)

    async def is_visible(self, **kwargs):
        return await self._answer("is_visible", self._visible)

    async def is_enabled(self, timeout=None, **kwargs):
        self.timeouts.append(timeout)
        return await self._answer("is_enabled", self._enabled)


class Spec:
    def __init__(self, element):
        self.element = element

    def resolve(self, page):
        return self.element


def turn(editor, users, *, left_s=10.0):
    """`left_s`: what is left before the request's own deadline (the provider's is earlier)."""
    now = time.monotonic()
    return SimpleNamespace(locators=SimpleNamespace(composer=Spec(editor), user_turn=Spec(users)),
                           deadline=now, started=now - 5,
                           request=SimpleNamespace(timeout_s=5 + left_s))


PAGE = SimpleNamespace(url="http://127.0.0.1:9/app?secret=1")


async def seen(fake):
    started = time.monotonic()
    async with asyncio.timeout(5):  # the old reads waited up to 30 s here
        text = await copilot_web._Turn.not_ready_seen(fake, PAGE, PageState.UNKNOWN,
                                                      time.monotonic() - 2, fake.deadline)
    return text, time.monotonic() - started


async def test_a_page_that_answers_is_described_by_structure_only():
    editor = Element(count=1, visible=True, enabled=False)
    text, took = await seen(turn(editor, Element(count=3)))
    assert "page http://127.0.0.1:9/app, state unknown, editor 1 matched, visible, not enabled, " \
           "3 user turns" in text and "secret" not in text
    assert editor.timeouts and all(t is not None and t <= 1000 for t in editor.timeouts)
    assert took < 1


@pytest.mark.parametrize("hang", [("is_enabled",), ("count",)],
                         ids=["editor_removed_between_checks", "busy_renderer"])
async def test_reads_that_do_not_answer_end_within_a_second(hang):
    text, took = await seen(turn(Element(hang=hang), Element(count=1)))
    assert text.endswith("; the page could not be read") and "ended by" in text
    assert took < 1.5


async def test_no_time_left_reads_nothing_and_never_extends_the_deadline():
    """With nothing left before the request's deadline nothing is read; with 0.4 s left the
    reads get half of it, never the whole."""
    text, took = await seen(turn(Element(hang=("count",)), Element(), left_s=0.0))
    assert text.endswith("; the page could not be read") and took < 0.2
    text, took = await seen(turn(Element(hang=("count",)), Element(), left_s=0.4))
    assert text.endswith("; the page could not be read") and 0.15 < took < 0.35


async def test_a_read_that_fails_does_not_raise():
    text, _ = await seen(turn(Element(fail=("is_visible",)), Element()))
    assert text.endswith("; the page could not be read")


# -- the reason travels with a cancellation (copilot_web.ask) ------------------------------------


def settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    path = measurement_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((FIXTURES / "ui.json").read_text("utf-8"), encoding="utf-8")
    return Settings.from_env({"HARNESS_DATA_DIR": str(data_dir), "HARNESS_PROVIDER": "copilot_web",
                              "HARNESS_COPILOT_URL": "http://127.0.0.1:9/app"})


async def close_like_close_owned() -> None:
    """Shaped as `harness.browser.edge.close_owned`: a coroutine of its own, the close shielded,
    the cancellation waited out and raised again. A cancellation raised there does not keep
    the error that was leaving the `async with` as its context (measured on Edge)."""
    closing = asyncio.ensure_future(asyncio.sleep(0.6))
    try:
        await asyncio.shield(closing)
    except asyncio.CancelledError:
        await asyncio.wait({closing})
        raise


class SlowClose:
    """A launcher whose browser takes 0.6 s to close."""

    @asynccontextmanager
    async def open(self, *, wait_s=None):
        try:
            yield SimpleNamespace(pages=[SimpleNamespace()])
        finally:
            await close_like_close_owned()


@pytest.mark.parametrize("sent", [False, True])
async def test_a_deadline_during_the_close_carries_the_reason_only_before_sending(
        tmp_path, monkeypatch, sent):
    reason = ProviderTimeout("the Copilot page was not ready in time; editor 0 matched")

    async def run(self, page):
        if sent:
            self.sent = True
        self.gave_up = reason
        raise reason

    monkeypatch.setattr(copilot_web._Turn, "run", run)
    provider = copilot_web.CopilotWebProvider(settings(tmp_path), launcher=SlowClose())
    request = LLMRequest(request_id=uuid4(), session_id=uuid4(), prompt="q", timeout_s=8)
    with pytest.raises(TimeoutError) as caught:
        async with asyncio.timeout(0.2):  # the service's deadline fires during the close
            await provider.ask(request, lambda: None)
    assert type(caught.value) is TimeoutError  # the deadline's own, not the provider's
    assert timeout_on_its_way(caught.value) is (None if sent else reason)
