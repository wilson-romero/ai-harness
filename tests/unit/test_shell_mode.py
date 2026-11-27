"""`/mode` in the conversation, plain and full screen (change response-mode)."""

from __future__ import annotations

from harness.core.response_mode import ResponseMode
from harness.providers.mock import MockProvider
from harness.shell.parser import Command, LineError, parse_line
from tests.conftest import RecordingProvider
from tests.shell_support import ScriptedTerminal, make_conversation, statuses
from tests.tui_support import SIZE, Tui


class ModalProvider(MockProvider):
    """The Mock with the conversation's open/close hooks, counting both."""

    def __init__(self) -> None:
        super().__init__()
        self.opens = self.closes = 0

    async def open_resources(self) -> None:
        self.opens += 1

    async def close_resources(self) -> None:
        self.closes += 1


def _session_mode(conn) -> str:
    return conn.execute("SELECT response_mode FROM sessions").fetchone()[0]


def test_the_command_takes_none_or_one_word():
    assert parse_line("/mode") == Command("mode", ())
    assert parse_line("/mode deep") == Command("mode", ("deep",))
    try:
        parse_line("/mode deep quick")
    except LineError as refused:
        assert "/mode takes 0 to 1 argument(s)" in str(refused)
    else:
        raise AssertionError("two words were accepted")


async def test_mode_changes_the_session_and_sends_nothing(conn, data_dir):
    """Scenario «Cambiar de modo no envía», in the plain conversation (`--plain`)."""
    provider = ModalProvider()
    terminal = ScriptedTerminal(["/mode deep", "/mode", "/status", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider)
    assert await conversation.run() == 0
    assert provider.calls == 0 and statuses(conn) == []
    assert _session_mode(conn) == "deep"
    assert any(line.startswith("response mode: deep") and "nothing was sent" in line
               for line in terminal.shown)
    assert "response mode: deep (this session)" in terminal.shown  # `/mode` alone
    assert "mode:     deep" in terminal.shown  # `/status`


async def test_a_question_after_mode_carries_it(conn, data_dir):
    provider = ModalProvider()
    terminal = ScriptedTerminal(["/mode quick", "hola", "/history", "/status", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider)
    await conversation.run()
    assert provider.modes == [ResponseMode.QUICK]
    assert "[completed, mode quick] user:" in terminal.shown
    assert any(line.startswith("last request: ") and line.endswith("mode quick")
               for line in terminal.shown)


async def test_an_unknown_mode_is_an_error_and_changes_nothing(conn, data_dir):
    """Scenario «Modo desconocido»."""
    terminal = ScriptedTerminal(["/mode rapidisimo", "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal, ModalProvider())
    await conversation.run()
    assert _session_mode(conn) == "auto"
    assert any(line.startswith("error: ") and "auto, quick or deep" in line
               for line in terminal.shown)


async def test_a_provider_without_modes_refuses_quick_and_deep(conn, data_dir):
    terminal = ScriptedTerminal(["/mode deep", "/mode auto", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, RecordingProvider())
    await conversation.run()
    assert _session_mode(conn) == "auto"
    assert any("only the automatic mode" in line for line in terminal.shown)
    assert any(line.startswith("response mode: auto") for line in terminal.shown)


async def test_the_mode_belongs_to_the_session(conn, data_dir):
    """A new session starts in auto; resuming the first one finds its mode again."""
    terminal = ScriptedTerminal(["/mode deep", "/new otra", "/mode", "/sessions", "/resume 2",
                                 "/mode", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, ModalProvider())
    await conversation.run()
    shown = [line for line in terminal.shown if line.endswith("(this session)")]
    assert shown == ["response mode: auto (this session)", "response mode: deep (this session)"]


async def test_the_side_panel_shows_the_mode(tmp_path):
    """Scenario «Panel lateral»."""
    tui = Tui(tmp_path, ModalProvider())
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.until(pilot, lambda: "Mode\n auto" in tui.side())
        await tui.send(pilot, "/mode quick")
        await tui.until(pilot, lambda: "Mode\n quick" in tui.side())
        assert tui.provider.calls == 0
        await tui.send(pilot, "/exit")
    assert tui.app.return_value == 0
