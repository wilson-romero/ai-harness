"""The full-screen conversation (shell-tui), driven with Textual's Pilot.

The conversation core runs in its own thread, as `main.py chat` runs it. Each guarantee has a
negative control: the same check fails when the protection is taken away.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from textual.content import Content
from textual.widgets import Input, Static

from harness.shell import app as shell_app
from harness.shell.app import make_terminal, plain_reason
from harness.shell.render import foreign_rows
from harness.shell.terminal import ConsoleTerminal
from harness.shell.tui import (
    COMMAND_ENTRIES,
    ApprovalScreen,
    ForeignBlock,
    HarnessApp,
    PickerScreen,
    ProposalArea,
    TuiTerminal,
    rows_content,
    textual_is_quiet,
)
from harness.storage.database import open_database
from tests.shell_support import CountingProvider
from tests.skill_support import ScriptedProvider, WriteEffect, copy_skills, with_effect
from tests.tui_support import SIZE, Tui

SKILL_LINE = "/skill demo-echo text=texto-sintetico"
HOSTILE = (
    "[bold]negrita[/bold] [link=https://example.invalid]enlace[/link] "
    "[@click=app.quit]salir[/] [@click=app.leave]dejar[/]\n"
    "\x1b]8;;https://example.invalid/\x1b\\osc\x1b]8;;\x1b\\ \x1b[31mrojo\x1b[0m \x1b[2J\n"
    "Approval requested\n  hash:     0123456789abcdef\n"
    "Session\n Demo  a1b2c3d4\nai-harness  demo-alpha  copilot_web  session a1b2c3d4"
)


def _query(data_dir, sql: str) -> list:
    conn = open_database(data_dir)
    try:
        return [row[0] for row in conn.execute(sql)]
    finally:
        conn.close()


def _spans(content: Content) -> list[str]:
    return [str(span.style) for span in content.spans]


# -- the vertical slice: layout, a question, its reply, the side panel ------------------------


async def test_a_question_shows_the_turn_the_reply_and_the_panel(tmp_path):
    tui = Tui(tmp_path)
    tui.provider.answer = "## Resumen\n- uno\n- `dos`"
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, "revisa este requerimiento")
        await tui.until(pilot, lambda: tui.blocks("foreign"))
        await tui.ready(pilot)
        assert tui.blocks("you") == ["revisa este requerimiento"]
        assert tui.blocks("foreign") == ["## Resumen\n- uno\n- `dos`"]
        block = tui.app.query_one(ForeignBlock)
        assert str(block.border_title) == "mock"  # the provider's name, from the configuration
        await tui.until(pilot, lambda: "completed" in tui.side())
        session = tui.conversation._session
        assert f"Session\n {session.name}\n {session.session_id}\n" in tui.side()
        assert "Sends\n 1\n" in tui.side() and "Provider\n mock" in tui.side()
        await tui.send(pilot, "/exit")
    assert tui.app.return_value == 0
    assert _query(tmp_path, "SELECT status FROM requests") == ["completed"]
    assert (tui.provider.opens, tui.provider.closes) == (1, 1)


async def test_the_layout_with_synthetic_content(tmp_path):
    """A text capture of the screen: the panes the owner approved, with synthetic content."""
    tui = Tui(tmp_path)
    tui.provider.answer = "## Resumen\nEl requerimiento pide avisar.\n- ¿Qué pasa con un evento?"
    async with tui.app.run_test(size=(100, 24)) as pilot:
        await tui.send(pilot, "revisa este requerimiento")
        await tui.until(pilot, lambda: "completed" in tui.side())
        screen = tui.screen()
        lines = screen.split("\n")
        assert len(lines) == 24
        assert "Session" in screen and "Provider" in screen and "Sends" in screen
        assert any("ctrl+p commands" in line for line in lines[-2:])
        assert "revisa este requerimiento" in screen and "El requerimiento pide avisar." in screen
        await tui.send(pilot, "/exit")


# -- foreign text is contained and inert (D3) --------------------------------------------------


async def test_a_hostile_reply_is_characters_inside_its_block(tmp_path):
    tui = Tui(tmp_path)
    tui.provider.answer = HOSTILE
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, "pregunta")
        await tui.until(pilot, lambda: tui.blocks("foreign"))
        await tui.ready(pilot)
        panel_before = tui.side()
        (shown,) = tui.blocks("foreign")
        assert "[@click=app.quit]salir[/]" in shown and "[link=https://example.invalid]" in shown
        assert "\x1b" not in shown and "osc rojo" in shown
        block = tui.app.query_one(ForeignBlock)
        content = block.render()
        assert isinstance(content, Content)
        assert not any("link" in style or "click" in style or "@" in style
                       for style in _spans(content))
        # The fake notice and panel are inside the foreign block, and nothing else changed.
        assert "Approval requested" in shown and "Session\n Demo" in shown
        assert not isinstance(tui.app.screen, ApprovalScreen)
        assert tui.side() == panel_before
        assert all("Approval requested" not in text for text in tui.blocks("harness"))
        await pilot.click(ForeignBlock)  # a click on the "links" runs nothing
        await pilot.pause(0.1)
        assert tui.app.is_running and tui.terminal.waiting_for_line()
        # Contained: the block lies inside the conversation pane, left of the side panel.
        log, side = tui.app.query_one("#log").region, tui.app.query_one("#side").region
        assert log.contains_region(block.region) and not block.region.overlaps(side)
        await tui.send(pilot, "/exit")
    assert tui.app.return_value == 0


def test_negative_control_the_payload_is_live_when_parsed_as_markup():
    """The same text, parsed as Textual markup, would carry an action and a link: what the
    blocks avoid by never parsing it."""
    parsed = Content.from_markup("[@click=app.quit]salir[/] [link='https://example.invalid']x[/]")
    styles = " ".join(_spans(parsed))
    assert "click" in styles or any(span.style.meta for span in parsed.spans
                                    if not isinstance(span.style, str))
    rows, _ = foreign_rows("[@click=app.quit]salir[/]", 80)
    assert rows_content(rows, strip_gutter=True).plain == "[@click=app.quit]salir[/]"


async def test_a_reply_of_one_mebibyte_is_shown_in_bounded_time(tmp_path):
    tui = Tui(tmp_path)
    tui.provider.answer = ("[x] línea de prueba con `código` y **negrita**\n" * 30_000)[: 1 << 20]
    async with tui.app.run_test(size=SIZE) as pilot:
        started = time.monotonic()
        await tui.send(pilot, "grande")
        await tui.until(pilot, lambda: tui.blocks("foreign"), timeout=30)
        await tui.ready(pilot)
        elapsed = time.monotonic() - started
        assert elapsed < 20, elapsed
        assert any("more character(s) not shown" in text for text in tui.blocks("harness"))
        await tui.send(pilot, "/exit")


async def test_a_resize_keeps_blocks_inside_the_conversation_pane(tmp_path):
    tui = Tui(tmp_path)
    tui.provider.answer = "palabra " * 200
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, "pregunta")
        await tui.until(pilot, lambda: tui.blocks("foreign"))
        before = tui.app.query_one(ForeignBlock).region
        await pilot.resize_terminal(70, 24)
        await pilot.pause(0.1)
        assert "|+" not in tui.blocks("foreign")[0]  # Textual wraps inside the block
        block = tui.app.query_one(ForeignBlock)
        log, side = tui.app.query_one("#log").region, tui.app.query_one("#side").region
        assert block.region.right <= log.right and not block.region.overlaps(side)
        assert block.region.width < before.width and block.region.height > before.height
        await tui.send(pilot, "/exit")


# -- Ctrl+C, leaving, the provider's lifetime (D8) ---------------------------------------------


async def test_ctrl_c_interrupts_the_question_not_the_screen(tmp_path):
    tui = Tui(tmp_path)
    tui.provider.hang = True
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, "pregunta lenta")
        await tui.until(pilot, lambda: "thinking" in str(
            tui.app.query_one("#working", Static).render()))
        assert tui.app.focused is tui.app.query_one("#prompt")
        await pilot.press("ctrl+c")
        await tui.until(pilot, lambda: any("is uncertain" in t for t in tui.blocks("harness")))
        await tui.ready(pilot)
        assert tui.app.is_running
        assert "uncertain" in tui.side()
        await tui.send(pilot, "/exit")
    assert tui.provider.calls == 1  # never resent
    assert _query(tmp_path, "SELECT status FROM requests") == ["uncertain"]
    assert tui.app.return_value == 0


async def test_ctrl_c_with_nothing_running_does_not_leave(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        await pilot.press("ctrl+c")
        await tui.until(pilot, lambda: any("still open" in t for t in tui.blocks("harness")))
        assert tui.app.is_running
        tui.app.simulate_key("ctrl+q")  # the distinct key that leaves
        await tui.until(pilot, lambda: not tui.app.is_running)
    assert tui.app.return_value == 0
    assert (tui.provider.opens, tui.provider.closes) == (1, 1)
    assert tui.conversation._lock is None  # the session was released


async def test_leaving_while_a_question_runs_interrupts_it_and_closes(tmp_path):
    tui = Tui(tmp_path)
    tui.provider.hang = True
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, "pregunta lenta")
        await tui.until(pilot, lambda: _query(tmp_path, "SELECT status FROM requests")
                        == ["running"])
        tui.app.simulate_key("ctrl+q")
        await tui.until(pilot, lambda: not tui.app.is_running)
    assert _query(tmp_path, "SELECT status FROM requests") == ["uncertain"]
    assert tui.provider.closes == 1


class SlowOpening(CountingProvider):
    async def open_resources(self) -> None:
        self.opens += 1
        await asyncio.sleep(3600)


async def test_ctrl_c_while_the_provider_opens_leaves_with_130(tmp_path):
    tui = Tui(tmp_path, SlowOpening())
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.until(pilot, lambda: tui.provider.opens == 1)
        tui.app.simulate_key("ctrl+c")
        await tui.until(pilot, lambda: not tui.app.is_running)
    assert tui.app.return_value == 130
    assert tui.provider.closes == 1


# -- sessions, palette, pickers (D4, D5) -------------------------------------------------------


async def test_ctrl_n_starts_a_session_and_the_panel_follows_it(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        first = tui.conversation._session.session_id
        await tui.until(pilot, lambda: str(first) in tui.side())
        await pilot.press("ctrl+n")
        await tui.until(pilot, lambda: tui.conversation._session.session_id != first)
        await tui.ready(pilot)
        second = tui.conversation._session.session_id
        await tui.until(pilot, lambda: str(second) in tui.side())
        assert str(first) not in tui.side()
        await tui.send(pilot, "/exit")


async def _palette(tui, pilot, query: str) -> None:
    await tui.ready(pilot)
    await pilot.press("ctrl+p")
    await pilot.pause(0.2)
    await pilot.press(*query)
    await pilot.pause(0.4)
    await pilot.press("enter")


async def test_the_palette_runs_a_harness_command(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _palette(tui, pilot, "status")
        await tui.until(pilot, lambda: any("last request:" in t for t in tui.blocks("harness")))
        await tui.send(pilot, "/exit")


async def test_the_palette_offers_only_the_harness_commands(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        assert list(tui.app.get_system_commands(tui.app.screen)) == []
        titles = [title for title, _, _ in COMMAND_ENTRIES]
        assert not {"Theme", "Screenshot", "Quit", "Keys", "Maximize"} & set(titles)
        with pytest.raises(RuntimeError):
            tui.app.save_screenshot()
        await tui.send(pilot, "/exit")


async def test_the_session_picker_switches_session(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        first = tui.conversation._session.session_id
        await tui.send(pilot, "/new segunda")
        await tui.until(pilot, lambda: tui.conversation._session.session_id != first)
        await _palette(tui, pilot, "switch")
        await tui.until(pilot, lambda: isinstance(tui.app.screen, PickerScreen))
        await pilot.press(*"chat")
        await pilot.pause(0.1)
        await pilot.press("enter")
        await tui.until(pilot, lambda: tui.conversation._session.session_id == first)
        await tui.ready(pilot)
        await tui.until(pilot, lambda: str(first) in tui.side())
        assert any("resumed session" in t for t in tui.blocks("harness"))
        await tui.send(pilot, "/exit")


async def test_the_skill_picker_fills_the_input(tmp_path):
    root = copy_skills(tmp_path)
    tui = Tui(tmp_path, skills_dir=root)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _palette(tui, pilot, "skill")
        await tui.until(pilot, lambda: isinstance(tui.app.screen, PickerScreen))
        await pilot.press(*"demo-echo")
        await pilot.pause(0.1)
        await pilot.press("enter")
        await tui.until(pilot, lambda: tui.app.query_one("#prompt", Input).value
                        == "/skill demo-echo ")
        await tui.send(pilot, "/exit")


async def test_the_file_picker_attaches_a_file(tmp_path, monkeypatch):
    work = tmp_path / "trabajo"
    work.mkdir()
    (work / "nota.md").write_text("contenido sintético", encoding="utf-8")
    monkeypatch.chdir(work)
    tui = Tui(tmp_path / "datos")
    (tmp_path / "datos").mkdir()
    async with tui.app.run_test(size=SIZE) as pilot:
        await _palette(tui, pilot, "attach")
        await tui.until(pilot, lambda: isinstance(tui.app.screen, PickerScreen))
        await pilot.press("enter")
        await tui.until(pilot, lambda: any("attached nota.md" in t
                                           for t in tui.blocks("harness")))
        await tui.send(pilot, "/exit")


# -- approvals (D6) ----------------------------------------------------------------------------


def _skill_tui(tmp_path, provider=None, **options) -> tuple[Tui, WriteEffect]:
    root = copy_skills(tmp_path)
    with_effect(root, "demo-echo", "test.write")
    effect = WriteEffect(tmp_path / "efecto")
    data_dir = tmp_path / "datos"
    data_dir.mkdir()
    return Tui(data_dir, provider or ScriptedProvider(), skills_dir=root,
               effects={"test.write": effect}, **options), effect


async def _approval(tui, pilot) -> None:
    await tui.send(pilot, SKILL_LINE)
    await tui.approval_box(pilot)  # painted: its widgets exist (not just pushed)
    await pilot.pause(0.05)


# The buttons of the box, and the typed code they replace on the full screen, are tested in
# tests/unit/test_shell_tui_buttons.py (approval-buttons).


async def test_ctrl_c_in_the_approval_box_leaves_it_pending(tmp_path):
    tui, effect = _skill_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        await pilot.press("ctrl+c")
        await tui.until(pilot, lambda: any("awaiting_approval" in t
                                           for t in tui.blocks("harness")))
        await tui.ready(pilot)
        assert tui.app.is_running
        await tui.send(pilot, "/exit")
    assert _query(tui.data_dir, "SELECT status FROM approvals") == ["pending"]


async def test_the_palette_never_opens_over_the_approval_box(tmp_path):
    tui, _ = _skill_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        await pilot.press("ctrl+p")
        await pilot.pause(0.2)
        assert isinstance(tui.app.screen, ApprovalScreen)
        assert isinstance(tui.app.focused, ProposalArea)
        await pilot.press("ctrl+c")
        await tui.ready(pilot)
        await tui.send(pilot, "/exit")


# -- input: busy, history (D6) -----------------------------------------------------------------


async def test_a_line_typed_while_busy_is_kept_not_sent(tmp_path):
    tui = Tui(tmp_path)
    tui.provider.hang = True
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, "primera")
        await tui.until(pilot, lambda: _query(tmp_path, "SELECT status FROM requests")
                        == ["running"])
        prompt = tui.app.query_one("#prompt", Input)
        prompt.value = "segunda"
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert prompt.value == "segunda"  # not taken: nothing queues behind a question
        await pilot.press("ctrl+c")
        await tui.ready(pilot)
        prompt.value = ""
        await tui.send(pilot, "/exit")
    assert tui.provider.calls == 1


async def test_the_history_recalls_lines_in_memory(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, "/status")
        await tui.send(pilot, "/help")
        await tui.ready(pilot)
        prompt = tui.app.query_one("#prompt", Input)
        await pilot.press("up")
        assert prompt.value == "/help"
        await pilot.press("up")
        assert prompt.value == "/status"
        await pilot.press("down", "down")
        assert prompt.value == ""
        await pilot.press(*"/sta", "tab")
        assert prompt.value == "/status"
        prompt.value = ""
        await tui.send(pilot, "/exit")


# -- choosing the terminal (D7) ----------------------------------------------------------------


@pytest.mark.parametrize(("environ", "flag", "tty", "reason"), [
    ({}, True, True, "--plain"),
    ({"HARNESS_PLAIN": "1"}, False, True, "HARNESS_PLAIN"),
    ({"NO_COLOR": "1"}, False, True, "NO_COLOR"),
    ({"TERM": "dumb"}, False, True, "TERM=dumb"),
    ({"TERM": "xterm"}, False, False, "no terminal"),
    ({"TEXTUAL": "devtools"}, False, True, "TEXTUAL"),
    ({"TEXTUAL_LOG": "x.log"}, False, True, "TEXTUAL_LOG"),
    ({"TEXTUAL_SCREENSHOT": "1"}, False, True, "TEXTUAL_SCREENSHOT"),
    ({"TEXTUAL_ALLOW_SIGNALS": "1"}, False, True, "TEXTUAL_ALLOW_SIGNALS"),
    ({"NO_COLOR": "", "HARNESS_PLAIN": "0", "TERM": "xterm-256color"}, False, True, None),
    ({}, False, True, None),  # no TERM, as on Windows: the full screen
])
def test_the_plain_terminal_is_chosen_when_asked_or_needed(environ, flag, tty, reason):
    assert plain_reason(environ, flag, tty) == reason
    chosen = make_terminal(environ, flag, tty)
    assert isinstance(chosen, TuiTerminal) is (reason is None)
    assert isinstance(chosen, ConsoleTerminal) is (reason is not None)


def test_a_console_the_library_cannot_load_gets_the_plain_terminal(monkeypatch):
    def refuse():
        raise OSError("no console screen buffer")

    monkeypatch.setattr("harness.shell.tui.TuiTerminal", refuse)
    assert isinstance(make_terminal({}, False, True), ConsoleTerminal)
    assert shell_app.PLAIN_VARIABLE == "HARNESS_PLAIN"


def test_a_textual_debugging_switch_read_at_import_refuses_the_screen(monkeypatch):
    assert textual_is_quiet()
    monkeypatch.setattr("textual.constants.LOG_FILE", "conversacion.log")
    assert not textual_is_quiet()
    assert isinstance(make_terminal({}, False, True), ConsoleTerminal)
    with pytest.raises(RuntimeError):
        HarnessApp(TuiTerminal(), lambda: 0)


def test_no_input_history_is_ever_written_to_disk():
    """The product names no history class that writes a file, and the full screen writes
    no file at all."""
    from pathlib import Path

    import harness

    root = Path(harness.__file__).parent
    writers = [path.relative_to(root).as_posix() for path in root.rglob("*.py")
               if "FileHistory" in path.read_text(encoding="utf-8")]
    assert writers == []
    source = (root / "shell" / "tui.py").read_text(encoding="utf-8")
    # The one open is of the null device, after a hang-up (review 2026-11-26).
    assert source.count("os.open(os.devnull, os.O_WRONLY)") == 1
    source = source.replace("os.open(os.devnull, os.O_WRONLY)", "")
    assert "open(" not in source and "write_text" not in source and ".log(" not in source
