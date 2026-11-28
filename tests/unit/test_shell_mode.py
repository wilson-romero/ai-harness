"""`/mode` in the conversation, plain and full screen (change response-mode)."""

from __future__ import annotations

import pytest

from harness.core.response_mode import ResponseMode
from harness.providers.mock import MockProvider
from harness.shell.commands import BY_NAME, help_text
from harness.shell.completion import CompletionData, suggest
from harness.shell.parser import Command, LineError, parse_line
from harness.shell.shortforms import RUNNING
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


# -- the one table of commands (command-completion D1-D3) ----------------------------------------


def test_mode_is_one_entry_of_the_table_with_its_help_line():
    spec = BY_NAME["mode"]
    assert (spec.least, spec.most) == (0, 1)
    assert "  /mode [auto|quick|deep]   the response mode of this session (nothing is sent)" \
        in help_text().splitlines()


def test_completion_offers_exactly_the_three_modes():
    offered = suggest("/mode ", CompletionData())
    assert [item.insert for item in offered.items] == [m.value for m in ResponseMode]
    assert [item.insert for item in suggest("/mode de", CompletionData()).items][0] == "deep"
    assert suggest("/mode deep ", CompletionData()).items == ()  # one value at most
    assert suggest("mode ", CompletionData()).items == ()  # a question completes nothing


async def test_tab_after_mode_offers_the_modes_and_sends_nothing(tmp_path):
    from harness.shell.tui import PromptInput, SuggestionList

    tui = Tui(tmp_path, ModalProvider())
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        prompt, listing = tui.app.query_one(PromptInput), tui.app.query_one(SuggestionList)
        await pilot.press(*"/mode ")
        await tui.until(pilot, lambda: listing.showing)
        assert [item.insert for item in listing.items] == ["auto", "quick", "deep"]
        await pilot.press(*"d", "tab")
        await tui.until(pilot, lambda: prompt.value == "/mode deep")
        assert tui.terminal.waiting_for_line() and tui.provider.calls == 0  # nothing ran
        prompt.value = ""
        await tui.send(pilot, "/exit")


async def test_a_unique_start_shows_the_full_command_before_it_runs(conn, data_dir):
    terminal = ScriptedTerminal(["/mo deep", "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal, ModalProvider())
    await conversation.run()
    running = terminal.shown.index(RUNNING + "/mode deep")
    done = next(i for i, line in enumerate(terminal.shown) if line.startswith("response mode: deep"))
    assert running < done
    assert _session_mode(conn) == "deep" and provider.calls == 0


async def test_m_alone_is_ambiguous_between_memory_and_mode(conn, data_dir):
    """The rule is a unique start or an error naming the candidates: with /mode, /m is no
    longer /memory (accepted 2026-11-27). Nothing runs."""
    terminal = ScriptedTerminal(["/m deep", "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal, ModalProvider())
    await conversation.run()
    error = next(line for line in terminal.shown if line.startswith("error: "))
    assert "/memory" in error and "/mode" in error
    assert _session_mode(conn) == "auto" and provider.calls == 0


async def test_an_unknown_value_is_a_local_error(conn, data_dir):
    terminal = ScriptedTerminal(["/mo turbo", "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal, ModalProvider())
    await conversation.run()
    assert any(line.startswith("error: ") and "auto, quick or deep" in line
               for line in terminal.shown)
    assert _session_mode(conn) == "auto" and provider.calls == 0 and statuses(conn) == []


@pytest.mark.parametrize("line", ["mode deep", "mo deep", "deep", "//mode deep"])
async def test_no_short_form_turns_a_question_into_mode(conn, data_dir, line):
    terminal = ScriptedTerminal([line, "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal, ModalProvider())
    await conversation.run()
    assert _session_mode(conn) == "auto"
    assert provider.calls == 1 and provider.modes == [ResponseMode.AUTO]  # sent as a question
    assert not any(line.startswith(RUNNING) for line in terminal.shown)


@pytest.mark.parametrize(("size", "panel"), [((80, 24), False), ((100, 30), True),
                                             ((120, 40), True)],
                         ids=lambda v: f"{v[0]}x{v[1]}" if isinstance(v, tuple) else str(v))
async def test_the_mode_line_on_every_layout(tmp_path, size, panel):
    """From 100 columns the side panel shows «Mode»; below, the panel is hidden and /status
    says the mode instead (tui-spacing D2)."""
    tui = Tui(tmp_path, ModalProvider())
    async with tui.app.run_test(size=size) as pilot:
        await tui.send(pilot, "/mode deep")
        await tui.until(pilot, lambda: "Mode\n deep" in tui.side())
        side = tui.app.query_one("#side")
        assert (side.region.width > 0) is panel
        if panel:
            assert "Mode" in tui.screen() and " deep" in tui.screen()
        else:
            await tui.send(pilot, "/status")
            await tui.until(pilot, lambda: any("mode:     deep" in t
                                               for t in tui.blocks("harness")))
        await tui.send(pilot, "/exit")
    assert tui.app.return_value == 0
