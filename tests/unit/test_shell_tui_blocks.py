"""Blocks that fold and unfold in the full screen (collapsible-blocks), driven with Pilot.

The conversation core runs in its own thread, as `main.py chat` runs it. Each guarantee has a
negative control: the same check fails when the protection is taken away.
"""

from __future__ import annotations

import time

import pytest
from rich.color import Color
from textual.content import Content

from harness.shell import blocks
from harness.shell.blocks import (
    EXCERPT_MAX,
    Fold,
    hidden_footer,
    one_line,
    outline,
    preview_lines,
    rows_in_preview,
)
from harness.shell.render import FOREIGN_PREFIX, foreign_rows, harness_rows
from harness.shell.tui import (
    CHROME,
    COMMAND_ENTRIES,
    STYLES,
    UNCUT,
    ApprovalScreen,
    CodeInput,
    ForeignBlock,
    NoticeBlock,
    PromptInput,
    Turn,
    TuiTerminal,
    chrome_line,
)
from tests.tui_support import SIZE, Tui
from tests.unit.test_shell_tui import _approval, _palette, _skill_tui

CHROME_BG = Color.parse("#3a3f4b").triplet


def long_reply(lines: int = 60, first: str = "## Resumen") -> str:
    body = [f"- Punto sintético número {n}." for n in range(1, lines - 4)]
    return "\n".join([first, "Texto sintético.", *body, "## Alternativas", "- Ninguna."])


def _replies(tui) -> list[ForeignBlock]:
    return list(tui.app.session_log.query(ForeignBlock))


def _turns(tui) -> list[Turn]:
    return list(tui.app.session_log.turns)


def _chrome_cells(tui) -> list[str]:
    """Per screen row, the characters drawn on the chrome background."""
    rows = []
    for strip in tui.app.screen._compositor.render_strips():
        rows.append("".join(seg.text for seg in strip if seg.style is not None and
                            seg.style.bgcolor is not None and
                            seg.style.bgcolor.triplet == CHROME_BG))
    return rows


async def _ask(tui, pilot, answer: str, line: str = "pregunta sintética") -> None:
    tui.provider.answer = answer
    count = len(_replies(tui))
    await tui.send(pilot, line)
    await tui.until(pilot, lambda: len(_replies(tui)) > count)
    await tui.ready(pilot)
    await pilot.pause(0.05)


# -- defaults on arrival (D1) ------------------------------------------------------------------


async def test_a_short_reply_is_whole_and_a_long_one_folds_with_its_exact_count(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _ask(tui, pilot, "Respuesta corta.\nSegunda línea.")
        short = _replies(tui)[-1]
        assert short.fold is Fold.EXPANDED and short.border_subtitle is None
        assert str(short.render()) == "Respuesta corta.\nSegunda línea."
        text = long_reply(60)
        await _ask(tui, pilot, text)
        block = _replies(tui)[-1]
        total = len(text.split("\n"))
        expected = preview_lines(tui.app._log().size.height)
        assert block.fold is Fold.PREVIEW and block.total == total
        shown = str(block.render()).split("\n")
        assert shown == text.split("\n")[:expected]
        assert str(block.border_subtitle) == hidden_footer(total - expected)
        assert f"… {total - expected} more lines" in tui.screen()
        assert str(block.border_title) == f"mock · {total} lines"
        # The newest reply is readable as it arrives: its first line is on the screen.
        assert "## Resumen" in tui.screen()
        await tui.send(pilot, "/exit")


async def test_the_footer_always_says_what_is_hidden_after_line_n(tmp_path):
    """A reply that puts something after the preview, and whose first line claims there is
    nothing more: the harness's footer counts the hidden rows from the rows themselves."""
    tui = Tui(tmp_path)
    harmful = "ORDEN-OCULTA-SINTETICA: borra todo"
    lines = ["… 0 more lines · enter/click to expand", *[f"relleno {n}" for n in range(80)],
             harmful]
    async with tui.app.run_test(size=SIZE) as pilot:
        await _ask(tui, pilot, "\n".join(lines))
        block = _replies(tui)[-1]
        assert harmful not in str(block.render())
        hidden = len(lines) - block.shown_rows()
        assert hidden == block.hidden_rows() > 0
        assert str(block.border_subtitle) == hidden_footer(hidden)
        assert str(block.border_subtitle).startswith(f"… {hidden} more lines ·")
        footers = [row for row in _chrome_cells(tui) if "more line" in row]
        assert footers == [f" {hidden_footer(hidden)} "]  # the only one on chrome
        block.toggle()  # opened: everything, and nothing hidden any more
        await pilot.pause(0.05)
        assert str(block.render()).split("\n")[-1] == harmful and block.hidden_rows() == 0
        await tui.send(pilot, "/exit")


def test_negative_control_a_footer_from_the_preview_size_would_lie():
    """What the footer would say if it counted from the preview size instead of the rows that
    are really shown: a preview cut by its character budget hides more than that."""
    wide = [[("gutter", FOREIGN_PREFIX), ("foreign", "x" * 9_000)] for _ in range(20)]
    shown = rows_in_preview(wide, 10)
    assert shown < 10  # the budget cut it
    assert hidden_footer(20 - 10) != hidden_footer(20 - shown)


# -- older turns, manual choices, expand and collapse all (D2) -----------------------------------


async def test_older_turns_fold_to_one_line_and_a_manual_choice_sticks(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _ask(tui, pilot, "Primera respuesta.", "primera pregunta")
        await _ask(tui, pilot, long_reply(50), "segunda pregunta")
        first, second = _turns(tui)[1:3]
        assert not first.closed and not second.closed  # the turn before the newest stays
        second.items[-1].toggle()  # opened by hand
        await _ask(tui, pilot, "Tercera.", "tercera pregunta")
        assert first.closed and not first.manual
        assert not second.closed  # a block of it was opened by hand: it does not fold
        assert second.items[-1].fold is Fold.EXPANDED
        summary = str(first.summary_line.render())
        assert summary.startswith("▸ you → mock · 2 lines · completed ")
        assert summary.endswith("› primera pregunta")
        await _ask(tui, pilot, "Cuarta.", "cuarta pregunta")
        assert not second.closed and second.items[-1].fold is Fold.EXPANDED
        await tui.send(pilot, "/exit")


async def test_expand_all_and_collapse_all_from_the_palette_and_the_keys(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        for n in range(3):
            await _ask(tui, pilot, long_reply(40), f"pregunta {n}")
        await _palette(tui, pilot, "collapse all")
        await tui.until(pilot, lambda: all(turn.closed for turn in _turns(tui)))
        await _palette(tui, pilot, "expand all")
        await tui.until(pilot, lambda: not any(turn.closed for turn in _turns(tui)))
        assert all(block.fold is Fold.EXPANDED for block in _replies(tui))
        prompt = tui.app.query_one(PromptInput)
        await pilot.press("escape", "minus")
        await pilot.pause(0.05)
        assert all(turn.closed for turn in _turns(tui)) and prompt.browsing
        await pilot.press("plus")
        await pilot.pause(0.05)
        assert not any(turn.closed for turn in _turns(tui))
        await pilot.press("escape")
        assert tui.app.focused is prompt and not prompt.browsing
        titles = {title for title, _, _ in COMMAND_ENTRIES}
        assert {"Expand all blocks", "Collapse all blocks", "Jump to latest", "Browse blocks",
                "Open or close the block"} <= titles
        await tui.send(pilot, "/exit")


# -- keys, mouse, focus (D3) -------------------------------------------------------------------


async def test_browsing_moves_and_toggles_and_a_letter_types_again(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _ask(tui, pilot, long_reply(50), "primera")
        await _ask(tui, pilot, long_reply(50), "segunda")
        prompt = tui.app.query_one(PromptInput)
        await pilot.press("escape")
        assert prompt.browsing and tui.app.focused is prompt
        assert "esc back to typing" in str(tui.app.query_one("#footer").render())
        newest = _replies(tui)[-1]
        assert tui.app.selected is newest  # browsing starts at the newest block
        await pilot.press("up")
        assert tui.app.selected is _turns(tui)[-1]
        await pilot.press("up", "enter")  # the reply of the first question: opened
        older = _replies(tui)[-2]
        assert tui.app.selected is older and older.fold is Fold.EXPANDED
        await pilot.press("space")
        assert older.fold is Fold.COLLAPSED
        await pilot.press("end")
        assert tui.app.selected is newest
        await pilot.press("h", "o")  # a letter: back to typing, and it is typed
        assert not prompt.browsing and prompt.value == "ho" and tui.app.selected is None
        assert tui.terminal.waiting_for_line()  # nothing was sent
        prompt.value = ""
        await pilot.press("alt+up")  # from the input, without browsing
        assert tui.app.selected is newest and not prompt.browsing
        await pilot.press("ctrl+o")
        assert newest.fold is Fold.EXPANDED and tui.app.focused is prompt
        await tui.send(pilot, "/exit")


async def test_a_click_on_the_header_toggles_and_on_the_text_does_nothing(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _ask(tui, pilot, long_reply(50))
        block = _replies(tui)[-1]
        prompt = tui.app.query_one(PromptInput)
        await pilot.click(block, offset=(4, 3))  # inside the foreign text
        await pilot.pause(0.05)
        assert block.fold is Fold.PREVIEW and tui.app.focused is prompt
        await pilot.click(block, offset=(4, 0))  # its header (the border with the title)
        await pilot.pause(0.05)
        assert block.fold is Fold.EXPANDED and tui.app.focused is prompt
        await pilot.click(block, offset=(4, 0))
        await pilot.pause(0.05)
        assert block.fold is Fold.COLLAPSED
        await pilot.click(block)  # the collapsed line opens again
        await pilot.pause(0.05)
        assert block.fold is Fold.EXPANDED
        turn = _turns(tui)[-1]
        await pilot.click(turn.you)  # the person's line closes the turn
        await pilot.pause(0.05)
        assert turn.closed and tui.app.focused is prompt
        assert tui.terminal.waiting_for_line() and tui.provider.calls == 1
        await tui.send(pilot, "/exit")


async def test_toggling_while_the_core_works_sends_nothing_typed_ahead(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _ask(tui, pilot, long_reply(50), "primera")
        tui.provider.hang = True
        await tui.send(pilot, "lenta")
        await tui.until(pilot, lambda: tui.provider.calls == 2)
        prompt = tui.app.query_one(PromptInput)
        prompt.value = "adelantada"
        await pilot.click(_replies(tui)[-1], offset=(4, 0))
        await pilot.press("ctrl+o", "alt+up", "enter")  # enter at the input: refused, busy
        await pilot.pause(0.1)
        assert prompt.value == "adelantada" and tui.provider.calls == 2
        assert tui.app.focused is prompt
        await pilot.press("ctrl+c")
        await tui.ready(pilot)
        prompt.value = ""
        await tui.send(pilot, "/exit")
    assert tui.provider.calls == 2


async def test_a_reply_arriving_never_takes_the_typing(tmp_path):
    tui = Tui(tmp_path)
    tui.provider.hang = True
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, "pregunta")
        await tui.until(pilot, lambda: tui.provider.calls == 1)
        prompt = tui.app.query_one(PromptInput)
        await pilot.press(*"escribo")
        tui.app.show_rows(foreign_rows(long_reply(80), UNCUT, markdown=True)[0], "mock")
        await pilot.pause(0.1)
        assert tui.app.focused is prompt and prompt.value == "escribo"
        await pilot.press("ctrl+c")
        await tui.ready(pilot)
        prompt.value = ""
        await tui.send(pilot, "/exit")


# -- scroll stability (D3) ---------------------------------------------------------------------


def _fill(tui, turns: int, reply: str) -> None:
    rows = foreign_rows(reply, UNCUT, markdown=True)[0]
    for n in range(turns):
        tui.app.start_turn(f"pregunta sintética {n}")
        tui.app.show_rows(rows, "mock")


async def test_the_block_being_read_does_not_jump(tmp_path):
    """Opening, closing or collapsing everything keeps the selected header on its row of the
    pane. Negative control: the same change without `_keep_in_place` moves it."""
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        _fill(tui, 30, long_reply(40))
        await pilot.pause(0.3)
        log = tui.app._log()

        def row(item) -> int:
            return item.widget.region.y - log.region.y

        await pilot.press("escape", "home", *["down"] * 10)  # an old turn, folded
        turn = tui.app.selected
        await pilot.pause(0.1)
        assert isinstance(turn, Turn) and turn.closed and turn.line == "pregunta sintética 9"
        before = row(turn)
        assert 0 <= before < log.size.height
        await pilot.press("enter")  # opened: it grows below its line
        await pilot.pause(0.2)
        assert not turn.closed and row(turn) == before
        await pilot.press("down", "enter")  # its reply, opened whole
        await pilot.pause(0.2)
        reply = tui.app.selected
        assert isinstance(reply, ForeignBlock) and reply.fold is Fold.EXPANDED
        reply_row = row(reply)
        assert 0 <= reply_row < log.size.height
        # Output arriving at the end while the person reads does not move what they read.
        tui.app.show_rows(harness_rows(["warning: synthetic notice"], None), None)
        tui.app.show_rows(foreign_rows(long_reply(40), UNCUT, markdown=True)[0], "mock")
        await pilot.pause(0.2)
        assert row(reply) == reply_row
        before = row(turn)
        await pilot.press("minus")  # collapse all: the turn being read keeps its row
        await pilot.pause(0.2)
        assert all(t.closed for t in tui.app.session_log.turns)
        assert tui.app.selected is turn and row(turn) == before
        # Negative control: opening everything without keeping the anchor moves it.
        for other in tui.app.session_log.turns:
            other.set_closed(False, manual=True)
        await pilot.pause(0.2)
        assert row(turn) != before
        await pilot.press("escape")
        await tui.send(pilot, "/exit")


async def test_opening_the_newest_reply_at_the_end_keeps_its_header(tmp_path):
    """At the end of the pane, the pane follows its bottom: opening the newest reply would
    push its header up and out of view. Its header stays on its row."""
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _ask(tui, pilot, long_reply(30), "primera")
        await _ask(tui, pilot, long_reply(80), "segunda")
        block = _replies(tui)[-1]
        log = tui.app._log()
        before = block.region.y - log.region.y
        assert 0 <= before < log.size.height and block.fold is Fold.PREVIEW
        await pilot.press("ctrl+o")
        await pilot.pause(0.2)
        assert block.fold is Fold.EXPANDED and block.region.y - log.region.y == before
        await pilot.press("ctrl+o")  # closed: one line, on the same row
        await pilot.pause(0.2)
        assert block.fold is Fold.COLLAPSED
        assert block.region.y - log.region.y == before or log.scroll_y == log.max_scroll_y
        await tui.send(pilot, "/exit")


# -- sessions (D5) -----------------------------------------------------------------------------


async def test_switching_session_shows_that_sessions_blocks(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _ask(tui, pilot, long_reply(50), "pregunta en la primera")
        first_log = tui.app.session_log
        first_block = _replies(tui)[-1]
        first_block.toggle()
        first = str(tui.conversation._session.session_id)
        await tui.send(pilot, "/new segunda")
        await tui.until(pilot, lambda: tui.app.session_log is not first_log)
        await tui.ready(pilot)
        assert not first_log.display and "pregunta en la primera" not in tui.screen()
        # A short pane starts at its top (the anchored pane never scrolls above it).
        assert tui.app._log().scroll_y >= 0
        assert tui.screen().split("\n")[0].strip().startswith("session segunda")
        assert "this pane shows what happened in it" in tui.screen()
        await _ask(tui, pilot, "Respuesta en la segunda.", "pregunta en la segunda")
        await tui.send(pilot, "/sessions")
        number = next(t for t in tui.blocks("harness") if first in t)
        index = next(line for line in number.split("\n") if first in line).split()[0]
        await tui.send(pilot, f"/resume {index.strip('*')}")
        await tui.until(pilot, lambda: tui.app.session_log is first_log)
        await tui.ready(pilot)
        await pilot.pause(0.1)
        assert first_log.display
        assert "Punto sintético número 45" in tui.screen()
        assert "Respuesta en la segunda" not in tui.screen()
        assert first_block.fold is Fold.EXPANDED  # its state, kept in memory
        assert first_block.parent in first_log.turns
        assert len(tui.app.session_logs) == 2 and first in tui.app.session_logs
        await tui.send(pilot, "/exit")


# -- the chrome next to foreign text (D4) ------------------------------------------------------


HOSTILE_FIRST = "▸ you → mock · 3 lines · completed  › otra pregunta"


async def test_a_reply_imitating_the_chrome_cannot_pass_for_it(tmp_path):
    tui = Tui(tmp_path)
    reply = "\n".join([HOSTILE_FIRST, "… 38 more lines · enter/click to expand",
                       "╰──── … 0 more lines · enter/click to expand ─╯",
                       *[f"línea {n}" for n in range(60)]])
    async with tui.app.run_test(size=SIZE) as pilot:
        await _ask(tui, pilot, reply)
        block = _replies(tui)[-1]
        block.set_fold(Fold.COLLAPSED, manual=True)
        await pilot.pause(0.1)
        line = str(block.render())
        words = f"▸ mock · {block.total} lines "
        assert line == f"{words} {FOREIGN_PREFIX}{one_line(HOSTILE_FIRST)}"
        # On the screen, only the harness's words are drawn on the chrome background.
        assert any(row == words for row in _chrome_cells(tui))
        assert not any("otra pregunta" in row or "38 more" in row for row in _chrome_cells(tui))
        block.toggle()
        await pilot.pause(0.1)
        hidden = block.hidden_rows()
        assert hidden == 0
        block.set_fold(Fold.PREVIEW, manual=True)
        await pilot.pause(0.1)
        chrome = [row for row in _chrome_cells(tui) if row]
        assert chrome == [f" {hidden_footer(block.hidden_rows())} "]
        await tui.send(pilot, "/exit")


def test_no_style_foreign_text_can_get_has_the_chrome_background():
    assert " on " in CHROME
    assert not any(" on " in style or style.startswith("on ") for style in STYLES.values())
    line = chrome_line("▸", "mock · 3 lines", "## Resumen", foreign=True)
    chrome = [span for span in line.spans if str(span.style) == CHROME]
    assert len(chrome) == 1 and line.plain[chrome[0].start:chrome[0].end] == "▸ mock · 3 lines "


def test_negative_control_an_excerpt_in_chrome_is_detected():
    """If the excerpt were drawn in the chrome style, the check above would see two spans."""
    forged = Content.assemble(("▸ mock ", CHROME), ("## Resumen", CHROME))
    assert len([s for s in forged.spans if str(s.style) == CHROME]) != 1 or \
        forged.plain != "▸ mock · 3 lines "


@pytest.mark.parametrize("text", [
    "uno dos tres\rcuatro\x85cinco\nseis",
    "\x1b[2J\x1b]8;;https://example.invalid\x07enlace\x1b]8;;\x07",
    "‮olleh‬",
    "x" * 10_000,
])
def test_an_excerpt_is_one_bounded_line(text):
    excerpt = one_line(text)
    assert len(excerpt) <= EXCERPT_MAX
    assert not any(c in excerpt for c in "\n\r\x0b\x0c\x1c\x1d\x1e\x85  \x1b‮")
    # Negative control: the raw text breaks a line or carries a control.
    assert len(text) > EXCERPT_MAX or any(c in text for c in "\n\r\x85 \x1b‮")


def test_the_outline_of_a_markdown_reply_is_its_headings():
    rows, _ = foreign_rows("## Resumen\ntexto\n```\n# no es título\n```\n## Alternativas\n- a",
                           UNCUT, markdown=True)
    assert outline(rows) == "## Resumen · ## Alternativas"
    plain_rows, _ = foreign_rows("\n\nprimera línea\nsegunda", UNCUT, markdown=True)
    assert outline(plain_rows) == "primera línea"


# -- metadata collapsed by default (D1) --------------------------------------------------------


async def test_skill_step_bookkeeping_is_one_line_by_default(tmp_path):
    tui, _ = _skill_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        assert not tui.app.screen.query(ForeignBlock) and not tui.app.screen.query(Turn)
        assert isinstance(tui.app.focused, CodeInput)
        await pilot.press("ctrl+o", "escape")  # the blocks' keys do nothing in the box
        assert isinstance(tui.app.screen, ApprovalScreen)
        assert not tui.app.query_one(PromptInput).browsing
        await pilot.press("ctrl+c")
        await tui.ready(pilot)
        steps = [b for b in tui.app.session_log.query(NoticeBlock) if b.kind == blocks.SKILL]
        assert steps and all(b.fold is Fold.COLLAPSED for b in steps if b.total > 1)
        assert all(str(b.render()).startswith("▸ skill steps · ") for b in steps if b.total > 1)
        await tui.send(pilot, "/exit")


def _rows(count: int) -> list:
    return [[("foreign", f"fila {n}")] for n in range(count)]


def test_default_folds():
    assert blocks.default_fold(blocks.CONTEXT, _rows(3), 20) is Fold.COLLAPSED
    assert blocks.default_fold(blocks.CONTEXT, _rows(1), 20) is Fold.EXPANDED
    assert blocks.default_fold(blocks.ALERT, _rows(500), 20) is Fold.EXPANDED
    assert blocks.default_fold(blocks.REPLY, _rows(24), 20) is Fold.EXPANDED  # the grace
    assert blocks.default_fold(blocks.REPLY, _rows(25), 20) is Fold.PREVIEW
    # Wrapped rows count by the screen rows they take: 12 rows of 3 screen rows each fold.
    assert blocks.default_fold(blocks.REPLY, _rows(12), 20, lambda row: 3) is Fold.PREVIEW
    assert rows_in_preview(_rows(12), 20, lambda row: 3) == 6
    assert blocks.category("context: demo", foreign=False, label=None) == blocks.CONTEXT
    assert blocks.category("error: x", foreign=False, label=None) == blocks.ALERT
    assert blocks.category("[12 more character(s) not shown]", foreign=False,
                           label=None) == blocks.ALERT


# -- bounds: 500 blocks and a 1 MiB reply ------------------------------------------------------


async def test_five_hundred_blocks_stay_responsive_and_folding_touches_one(tmp_path):
    tui = Tui(tmp_path)
    reply = foreign_rows(long_reply(40), UNCUT, markdown=True)[0]
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        started = time.monotonic()
        for n in range(250):
            tui.app.start_turn(f"pregunta sintética {n}")
            tui.app.show_rows(harness_rows([f"context: demo, {n} note(s)"], None), None)
            tui.app.show_rows(reply, "mock")
        await pilot.pause(0.2)
        built = time.monotonic() - started
        assert len(_replies(tui)) == 250 and built < 30, built
        assert sum(turn.closed for turn in _turns(tui)) >= 248  # the older ones folded
        renders = {id(b): b.renders for b in _replies(tui)}
        started = time.monotonic()
        await pilot.press("escape", "enter")
        await pilot.pause(0.05)
        assert time.monotonic() - started < 3
        changed = [b for b in _replies(tui) if b.renders != renders[id(b)]]
        assert changed == [_replies(tui)[-1]]  # one block rebuilt, not all of them
        started = time.monotonic()
        await pilot.press("minus")
        await pilot.pause(0.05)
        await pilot.press("plus")
        await pilot.pause(0.05)
        assert time.monotonic() - started < 30
        await pilot.press("escape")
        await tui.send(pilot, "/exit")


async def test_a_folded_mebibyte_reply_costs_its_preview(tmp_path):
    tui = Tui(tmp_path)
    tui.provider.answer = ("línea sintética de prueba\n" * 60_000)[: 1 << 20]
    async with tui.app.run_test(size=SIZE) as pilot:
        started = time.monotonic()
        await tui.send(pilot, "grande")
        await tui.until(pilot, lambda: _replies(tui), timeout=30)
        await tui.ready(pilot)
        assert time.monotonic() - started < 20
        block = _replies(tui)[-1]
        assert block.fold is Fold.PREVIEW
        assert len(str(block.render())) < 4_000  # the preview, not the reply
        assert block.truncated and "truncated" in str(block.border_title)
        assert any("more character(s) not shown" in t for t in tui.blocks("harness"))
        started = time.monotonic()
        block.toggle()
        await pilot.pause(0.2)
        assert time.monotonic() - started < 20
        assert block.hidden_rows() == 0
        await tui.send(pilot, "/exit")


async def test_the_palette_starts_browsing_and_jumps_to_the_latest(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _ask(tui, pilot, long_reply(50), "primera")
        await _palette(tui, pilot, "browse blocks")
        prompt = tui.app.query_one(PromptInput)
        await tui.until(pilot, lambda: prompt.browsing and tui.app.focused is prompt)
        assert tui.app.selected is _replies(tui)[-1]
        await pilot.press("escape")
        await _palette(tui, pilot, "open or close")
        await tui.until(pilot, lambda: _replies(tui)[-1].fold is Fold.EXPANDED)
        await _palette(tui, pilot, "jump to latest")
        await pilot.pause(0.2)
        log = tui.app._log()
        assert log.scroll_y == log.max_scroll_y
        await tui.send(pilot, "/exit")


def test_the_folding_module_is_standard_library_and_writes_nothing():
    from pathlib import Path

    source = Path(blocks.__file__).read_text(encoding="utf-8")
    imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
    assert all("textual" not in line and "rich" not in line for line in imports)
    assert "open(" not in source and "write" not in source


async def test_a_folded_reply_of_wrapped_lines_fits_the_pane_as_it_arrives(tmp_path):
    """The preview is measured in screen rows: lines that wrap take more than one. Negative
    control: counting each line as one row makes the preview taller than the pane."""
    tui = Tui(tmp_path)
    wide = "\n".join(["## Resumen", *[f"- Riesgo sintético {n}: " + "palabra " * 14
                                      for n in range(40)]])
    async with tui.app.run_test(size=(100, 30)) as pilot:
        await _ask(tui, pilot, wide)
        block = _replies(tui)[-1]
        log = tui.app._log()
        assert block.fold is Fold.PREVIEW
        assert block.outer_size.height <= log.size.height
        screen = tui.screen()
        assert "## Resumen" in screen and "more lines · enter/click to expand" in screen
        assert rows_in_preview(block.rows, block.preview) > block.shown_rows()
        assert len(str(block.render()).split("\n")) == block.shown_rows()
        assert str(block.border_subtitle) == hidden_footer(block.total - block.shown_rows())
        await tui.send(pilot, "/exit")


def test_a_warning_before_the_reply_does_not_take_its_title():
    """The provider's name titles the foreign rows after its answer, even when a harness
    line (a warning of the request) comes first; the next wait forgets it."""
    terminal = TuiTerminal()
    posted: list = []
    terminal._post = lambda method, *args: posted.append((method, args))
    terminal._label = "mock"
    terminal.show_rows(harness_rows(["warning: synthetic"], None))
    terminal.show_rows(foreign_rows("respuesta", UNCUT)[0])
    terminal.show_rows(foreign_rows("otra", UNCUT)[0])
    assert [args[1] for _, args in posted] == ["mock", "mock", None]
