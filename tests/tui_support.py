"""Drive the full-screen conversation with Textual's Pilot (shell-tui).

The conversation core runs in its own thread, exactly as `main.py chat` runs it: its database
connection is opened in that thread. The test waits on what the screen shows, never on a clock
alone: `until` polls a condition with a deadline.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

from textual.widgets import Static

from harness.shell.tui import HarnessApp, TuiTerminal
from harness.storage.database import open_database
from tests.shell_support import CountingProvider, make_conversation

SIZE = (110, 32)


class Tui:
    """One full-screen conversation over a temporary data directory."""

    def __init__(self, data_dir: Path, provider=None, *, arm_s: float = 0.0,
                 session: str | None = None, **options) -> None:
        self.data_dir = data_dir
        self.provider = provider if provider is not None else CountingProvider()
        self.terminal = TuiTerminal()
        self.conversation = None
        self.service = None

        def body() -> int:
            conn = open_database(data_dir)
            try:
                conversation, service, _ = make_conversation(
                    conn, data_dir, self.terminal, self.provider, **options)
                conversation._deps.columns = self.terminal.pane_columns
                conversation._deps.layout = self.terminal.layout_columns  # as app.py wires it
                self.conversation, self.service = conversation, service
                self.terminal.attach(conversation)
                return asyncio.run(conversation.run(session))
            finally:
                conn.close()

        self.app = HarnessApp(self.terminal, body, arm_s=arm_s)

    # -- reading the screen -------------------------------------------------------------------

    def blocks(self, kind: str) -> list[str]:
        """The text of every block of one kind (you, harness, foreign), in order."""
        return [str(widget.render()) for widget in self.app.query(f"#log .{kind}")
                if isinstance(widget, Static)]

    def text(self) -> str:
        return "\n".join(str(widget.render()) for widget in self.app.query("#log Static"))

    def screen(self) -> str:
        """What the terminal would show now, as text: the composed screen, row by row."""
        strips = self.app.screen._compositor.render_strips()
        return "\n".join(strip.text.rstrip() for strip in strips)

    def side(self) -> str:
        return str(self.app.query_one("#side", Static).render())

    async def until(self, pilot, condition: Callable[[], bool], timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                raise AssertionError(f"timed out; the screen shows:\n{self.text()}")
            if self.app.is_running and not self.app._exit_renderables and \
                    self.app.return_code is None:
                await pilot.pause(0.02)
            else:  # the app is leaving: Pilot cannot pause it any more
                await asyncio.sleep(0.02)

    async def ready(self, pilot) -> None:
        await self.until(pilot, self.terminal.waiting_for_line)

    async def send(self, pilot, line: str) -> None:
        """Type a line at the conversation input and press Enter, once the core waits."""
        await self.ready(pilot)
        prompt = self.app.query_one("#prompt")
        prompt.value = line
        prompt.cursor_position = len(line)
        await pilot.press("enter")
        await self.until(pilot, lambda: not self.terminal.waiting_for_line()
                         or prompt.value == "")
