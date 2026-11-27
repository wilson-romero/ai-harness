"""Replies in the full screen (reply-rendering): whole on arrival with their start in view, and
their tables and code blocks laid out to the block's width. Driven with Pilot."""

from __future__ import annotations

import pytest
from textual.widgets import Static

from harness.shell import blocks
from harness.shell.blocks import Fold
from harness.shell.render import foreign_rows
from harness.shell.tui import FOREIGN_FRAME, UNCUT, ForeignBlock, below_hint
from tests.tui_support import SIZE, Tui
from tests.unit.test_shell_tui_blocks import _ask, _replies, _turns, long_reply

TABLE = "\n".join([
    "## Comparación",
    "| Componente | Capa | Estado |",
    "|:-----------|:----:|-------:|",
    "| Pasarela de pagos | Integración | activo |",
    "| Motor de reglas con un nombre bastante largo para partirse en dos o tres filas | "
    "Dominio | en revisión |",
    "| Cola | Infraestructura | **activo** |",
    "",
    "```python",
    "print('hola')",
    "```",
    "fin",
])


def _footer(tui) -> str:
    return str(tui.app.query_one("#footer", Static).render())


def _top_in_pane(tui, block) -> int:
    log = tui.app._log()
    return block.region.y - log.region.y


# -- whole on arrival (D5) ---------------------------------------------------------------------


async def test_a_long_reply_arrives_whole_with_its_start_at_the_top_of_the_pane(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        text = long_reply(80)
        await _ask(tui, pilot, text)
        await pilot.pause(0.1)
        block = _replies(tui)[-1]
        log = tui.app._log()
        assert block.fold is Fold.EXPANDED and block.shown_rows() == block.total
        assert str(block.render()).split("\n") == text.split("\n")
        assert block.outer_size.height > log.size.height  # taller than the pane
        assert 0 <= _top_in_pane(tui, block) <= 1  # its first line (the border) on top
        assert "## Resumen" in tui.screen()
        below = log.max_scroll_y - log.scroll_y
        assert below > 0 and _footer(tui).startswith(below_hint(below))
        await tui.send(pilot, "/exit")


async def test_a_reply_not_laid_out_yet_is_not_taken_for_one_that_fits(tmp_path):
    """The placement waits for the reply's layout: a block mounted and placed before the
    screen laid it out measures 0 rows. Deterministic: the placement is called by hand at
    that moment (review 2026-11-27; before the fix it anchored the pane to the reply's end)."""
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        app = tui.app
        app.start_turn("pregunta sintética")
        await pilot.pause(0.1)
        rows = foreign_rows(long_reply(80), UNCUT, markdown=True)[0]
        block = ForeignBlock(rows, "mock", kind=blocks.REPLY, preview=app._preview(),
                             height_of=app._height_of(True))
        app.session_log.turns[-1].add(block)
        app._log().release_anchor()
        app._arriving = block
        assert block.outer_size.height == 0  # mounted, not laid out
        app._show_start(block)
        await pilot.pause(0.3)
        assert block.outer_size.height > app._log().size.height
        assert 0 <= _top_in_pane(tui, block) <= 1
        await tui.send(pilot, "/exit")


async def test_of_replies_that_arrive_together_the_newest_is_shown_from_its_start(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        rows = foreign_rows(long_reply(40), UNCUT, markdown=True)[0]
        for n in range(10):
            tui.app.start_turn(f"pregunta sintética {n}")
            tui.app.show_rows(rows, "mock")
        await pilot.pause(0.3)
        assert 0 <= _top_in_pane(tui, _replies(tui)[-1]) <= 1
        await tui.send(pilot, "/exit")


async def test_a_line_sent_before_the_reply_is_placed_goes_to_the_end(tmp_path):
    """Sending always goes to the end (collapsible-blocks): a reply that has not been placed
    yet does not pull the pane back to its start afterwards."""
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        tui.app.start_turn("pregunta sintética")
        await pilot.pause(0.1)
        tui.app.show_rows(foreign_rows(long_reply(80), UNCUT, markdown=True)[0], "mock")
        tui.app.start_turn("otra pregunta")  # before any refresh
        await pilot.pause(0.3)
        log = tui.app._log()
        assert log.scroll_y == log.max_scroll_y
        await tui.send(pilot, "/exit")


async def test_reading_to_the_end_clears_the_hint(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _ask(tui, pilot, long_reply(80))
        await pilot.pause(0.1)
        assert "below" in _footer(tui)
        tui.app._log().scroll_end(animate=False, immediate=True)
        await pilot.pause(0.1)
        assert "below" not in _footer(tui)
        await tui.send(pilot, "/exit")


async def test_a_short_reply_keeps_the_end_in_view_and_shows_no_hint(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _ask(tui, pilot, "Respuesta corta.\nSegunda línea.")
        await pilot.pause(0.1)
        log = tui.app._log()
        assert log.scroll_y >= log.max_scroll_y - 1 and "below" not in _footer(tui)
        await tui.send(pilot, "/exit")


async def test_the_reply_still_folds_by_hand(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _ask(tui, pilot, long_reply(80))
        block = _replies(tui)[-1]
        await pilot.press("ctrl+o")
        await tui.until(pilot, lambda: block.fold is Fold.COLLAPSED)
        await pilot.press("ctrl+o")
        await tui.until(pilot, lambda: block.fold is Fold.EXPANDED)
        await tui.send(pilot, "/exit")


async def test_older_turns_still_fold_by_themselves(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        for n in range(3):
            await _ask(tui, pilot, long_reply(40), line=f"pregunta sintética {n}")
        turns = [turn for turn in _turns(tui) if turn.line is not None]
        assert [turn.closed for turn in turns] == [True, False, False]
        assert all(block.fold is Fold.EXPANDED for block in _replies(tui)[-2:])
        await tui.send(pilot, "/exit")


async def test_a_reply_over_the_work_bound_arrives_folded(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        line = "x" * 99
        lines = blocks.ARRIVE_WHOLE_MAX_CHARS // 100 + 10
        await _ask(tui, pilot, "\n".join([line] * lines))
        block = _replies(tui)[-1]
        assert block.fold is Fold.PREVIEW and block.hidden_rows() > 0
        await tui.send(pilot, "/exit")


def test_default_fold_of_a_reply():
    rows = [[("foreign", "x")]] * 500
    assert blocks.default_fold(blocks.REPLY, rows, 20) is Fold.EXPANDED
    assert blocks.default_fold(blocks.FOREIGN, rows, 20) is Fold.PREVIEW  # other text folds
    big = [[("foreign", "x" * 1000)]] * (blocks.ARRIVE_WHOLE_MAX_CHARS // 1000 + 1)
    assert blocks.default_fold(blocks.REPLY, big, 20) is Fold.PREVIEW


# -- tables and code blocks in the pane (D1-D3) --------------------------------------------------


@pytest.mark.parametrize("columns", [80, 100, 120])
async def test_a_table_is_laid_out_to_the_width_of_its_block(tmp_path, columns):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=(columns, 40)) as pilot:
        await _ask(tui, pilot, TABLE)
        block = _replies(tui)[-1]
        rows = str(block.render()).split("\n")
        inner = block.content_region.width
        assert inner == tui.app.foreign_width
        table = [row for row in rows if "│" in row]
        assert table and len({row.index("│") for row in table}) == 1  # one column for all
        assert all(len(row) <= inner for row in rows)
        assert block.content_region.height == len(rows)  # Textual wrapped no row again
        assert "```" not in tui.screen() and "── python " in tui.screen()
        await tui.send(pilot, "/exit")


async def test_the_width_follows_the_pane(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=(120, 40)) as pilot:
        await tui.ready(pilot)
        wide = tui.app.foreign_width
        await pilot.resize_terminal(80, 40)
        await pilot.pause(0.2)
        assert tui.app.foreign_width < wide
        assert tui.app.foreign_width == tui.app._log().scrollable_content_region.width - \
            FOREIGN_FRAME
        await tui.send(pilot, "/exit")


async def test_the_rules_of_a_table_have_no_background(tmp_path):
    tui = Tui(tmp_path)
    async with tui.app.run_test(size=(100, 40)) as pilot:
        await _ask(tui, pilot, TABLE)
        strips = tui.app.screen._compositor.render_strips()
        blank = {seg.style.bgcolor for strip in strips for seg in strip
                 if seg.style is not None and seg.text.strip() == "" and seg.text}
        drawn = [seg for strip in strips for seg in strip
                 if seg.style is not None and set(seg.text) & set("┼│")
                 and "╭" not in seg.text and "╰" not in seg.text]
        assert drawn
        screen_bg = tui.app.screen.styles.background.rich_color
        assert all(seg.style.bgcolor in (None, screen_bg) for seg in drawn), blank
        await tui.send(pilot, "/exit")
