"""Copilot Web behind the full-screen conversation (shell-tui D8 with copilot-web-provider D3).

The conversation core runs in its own thread with its own event loop, as `main.py chat` runs
it, while Textual owns the main thread. Edge is opened, used and closed on the core's thread;
Ctrl+C and Ctrl+Q from the screen reach it; its notices arrive as harness lines. Synthetic
chat only, headless, temporary profile.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from harness.browser.edge import BROWSER_LOCK, EdgeLauncher
from harness.config import Settings
from harness.providers import copilot_web
from harness.providers.copilot_web import CopilotWebProvider
from harness.storage.database import open_database
from harness.storage.locks import NamedLock
from tests.browser.test_copilot_provider import write_ui
from tests.copilot_app import SyntheticCopilot
from tests.tui_support import SIZE, Tui

pytestmark = pytest.mark.edge

TIMEOUT_S = 40.0


class EdgeTui(Tui):
    """The full-screen conversation with a real Copilot provider against the synthetic chat."""

    def __init__(self, data_dir: Path, profile: Path, url: str) -> None:
        settings = Settings.from_env({
            "HARNESS_DATA_DIR": str(data_dir),
            "HARNESS_PROVIDER": "copilot_web",
            "HARNESS_COPILOT_URL": url,
            "HARNESS_EDGE_PROFILE": str(profile),
            "HARNESS_REQUEST_TIMEOUT_S": str(TIMEOUT_S),
            "HARNESS_TEST_HEADLESS": "1",
        })
        self.launcher = EdgeLauncher.from_settings(settings)
        super().__init__(data_dir, CopilotWebProvider(settings, self.launcher), timeout_s=TIMEOUT_S)

    def statuses(self) -> list[str]:
        conn = open_database(self.data_dir)
        try:
            return [r[0] for r in conn.execute("SELECT status FROM requests ORDER BY rowid")]
        finally:
            conn.close()

    def harness(self) -> str:
        return "\n".join(self.blocks("harness"))

    def edge_closed(self) -> bool:
        """No context, no launch in progress, the browser lock free."""
        lock = NamedLock(self.data_dir, BROWSER_LOCK)
        free = lock.acquire()
        if free:
            lock.release()
        return not self.launcher.contexts and self.launcher._starting_or_open == 0 and free


@pytest.fixture
def app(copilot_app: SyntheticCopilot, data_dir: Path) -> SyntheticCopilot:
    write_ui(data_dir)
    return copilot_app


@pytest.fixture
def threads(monkeypatch) -> list[str]:
    """The thread each Edge launch ran on."""
    names: list[str] = []
    original = EdgeLauncher._launch

    async def spy(self, playwright, profile):
        names.append(threading.current_thread().name)
        return await original(self, playwright, profile)

    monkeypatch.setattr(EdgeLauncher, "_launch", spy)
    return names


@pytest.fixture
def closes(monkeypatch) -> list[tuple[str, int]]:
    """Each `close_resources`: its thread and the contexts left open after it. Edge must be
    closed by the conversation itself, not by `asyncio.run` finalising the launcher's
    generator when the core's loop ends (that would also close it, which is why the
    contexts alone are not an oracle)."""
    seen: list[tuple[str, int]] = []
    original = CopilotWebProvider.close_resources

    async def spy(self):
        await original(self)
        seen.append((threading.current_thread().name, len(self._launcher.contexts)))

    monkeypatch.setattr(CopilotWebProvider, "close_resources", spy)
    return seen


def _tui(data_dir, tmp_path, url) -> EdgeTui:
    return EdgeTui(data_dir, tmp_path / "edge-profile", url)


async def _leave(tui, pilot) -> None:
    tui.app.simulate_key("ctrl+q")
    await tui.until(pilot, lambda: not tui.app.is_running, timeout=TIMEOUT_S)


async def test_ask_interrupt_and_quit_close_edge_from_the_core_thread(app, data_dir, tmp_path, threads,
                                                                       closes):
    tui = _tui(data_dir, tmp_path, app.url("/app", chunk_ms="300"))
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, "uno ZQX-END-1")
        await tui.until(pilot, lambda: tui.blocks("foreign"), timeout=TIMEOUT_S)
        await tui.ready(pilot)
        assert tui.statuses() == ["completed"]
        # A slow answer, interrupted from the screen once the prompt reached the page.
        await tui.send(pilot, "dos ZQX-END-2")
        await tui.until(pilot, lambda: app.prompt_count == 2, timeout=TIMEOUT_S)
        await pilot.press("ctrl+c")
        await tui.until(pilot, lambda: "is uncertain" in tui.harness(), timeout=TIMEOUT_S)
        await tui.ready(pilot)
        assert tui.app.is_running and tui.launcher.contexts  # Edge stays for the conversation
        await _leave(tui, pilot)
    assert tui.statuses() == ["completed", "uncertain"]
    assert app.prompt_count == 2  # never resent
    assert threads == ["conversation"]  # one launch, on the core's thread, not the screen's
    assert closes == [("conversation", 0)]  # closed once, by the conversation, on that thread
    assert tui.edge_closed()
    assert tui.conversation._lock is None  # the session was released


async def test_quit_while_a_question_runs_closes_edge(app, data_dir, tmp_path, threads, closes):
    tui = _tui(data_dir, tmp_path, app.url("/app", chunk_ms="300"))
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, "lenta ZQX-END-1")
        await tui.until(pilot, lambda: app.prompt_count == 1, timeout=TIMEOUT_S)
        await _leave(tui, pilot)
    assert tui.statuses() == ["uncertain"]
    assert tui.edge_closed() and tui.conversation._lock is None
    assert threads == ["conversation"] and closes == [("conversation", 0)]


async def test_signed_out_the_notice_is_a_harness_line(app, data_dir, tmp_path):
    app.require_login = True
    tui = _tui(data_dir, tmp_path, app.url())
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, "hola ZQX-END-1")
        await tui.until(pilot, lambda: "main.py copilot login" in tui.harness(), timeout=TIMEOUT_S)
        await tui.ready(pilot)
        assert tui.blocks("foreign") == []  # nothing shown as if Copilot had said it
        await _leave(tui, pilot)
    assert tui.statuses() == ["authentication_required"]
    assert app.prompt_count == 0 and app.login_events == []
    assert tui.edge_closed()


async def test_a_lost_tab_notice_is_a_harness_line(app, data_dir, tmp_path, monkeypatch):
    original = copilot_web._Turn.wait_ready
    lost: list = []

    async def losing(self, page, *args, **kwargs):
        if not lost:
            lost.append(page)
            await page.close()
        return await original(self, page, *args, **kwargs)

    monkeypatch.setattr(copilot_web._Turn, "wait_ready", losing)
    tui = _tui(data_dir, tmp_path, app.url())
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, "uno ZQX-END-1")
        await tui.until(pilot, lambda: tui.blocks("foreign"), timeout=TIMEOUT_S)
        assert "trying once more in a new tab" in tui.harness()
        await _leave(tui, pilot)
    assert tui.statuses() == ["completed"] and len(lost) == 1
    assert tui.edge_closed()
