"""The whole full screen on the house scale and the theme (tui-spacing D1-D7): colours only
through theme variables, the side panel only where it fits, the person's messages marked by
shape, one column grid for text and vertical gaps only where the rows allow."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from textual.color import Color
from textual.widgets import Static

from harness.shell import spacing
from harness.shell.tui import HarnessApp, PromptInput
from tests.shell_support import CountingProvider, ScriptedTerminal, make_conversation
from tests.tui_support import Tui

ROOT = Path(__file__).resolve().parents[2]
SIZES = [(80, 24), (100, 30), (120, 40)]
# Conversation rows visible before this change (measured on 481ad2e, two turns with the Mock).
ROWS_BEFORE = {(80, 24): 20, (100, 30): 26, (120, 40): 36}
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
ANSWER = ("## Resumen\nEl requerimiento pide **avisar** de pedidos con `order.created`.\n\n"
          "## Preguntas pendientes\n- Que pasa con un evento que no se publica?")


def _ids(size):
    return f"{size[0]}x{size[1]}"


async def _two_turns(tmp_path, pilot_size, body):
    data = tmp_path / "datos"
    data.mkdir()
    tui = Tui(data, CountingProvider(answer=ANSWER))
    async with tui.app.run_test(size=pilot_size) as pilot:
        await tui.ready(pilot)
        for n in range(2):
            await tui.send(pilot, f"revisa este requerimiento {n}")
            await tui.until(pilot, lambda n=n: len(tui.blocks("foreign")) > n)
        await tui.ready(pilot)
        await tui.send(pilot, "/status")  # a harness block at the bottom, on the screen
        await tui.until(pilot, lambda: any("sends:" in t for t in tui.blocks("harness")))
        await tui.ready(pilot)
        await pilot.pause(0.2)
        await body(tui, pilot)
        await tui.send(pilot, "/exit")


# -- colours (D1) --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["tui.py", "blocks.py", "palette.py"])
def test_no_colour_of_the_house_only_theme_variables(name):
    source = (ROOT / "harness" / "shell" / name).read_text(encoding="utf-8")
    assert HEX.findall(source) == []


def test_every_colour_role_names_a_theme_variable():
    from harness.shell import palette

    assert palette.ROLES, "the roles exist"
    for role, value in palette.ROLES.items():
        colour = value.split()[0]
        assert colour.startswith("$") and not HEX.search(value), role


@pytest.mark.parametrize("theme", ["textual-dark", "ansi-dark"])
async def test_the_roles_resolve_in_a_full_and_in_an_ansi_theme(tmp_path, theme):
    from harness.shell import palette

    async def body(tui, pilot):
        tui.app.theme = theme
        await pilot.pause(0.1)
        variables = tui.app.get_css_variables()
        for role, value in palette.ROLES.items():
            name = value.split()[0][1:]
            assert name in variables, (role, value)

    await _two_turns(tmp_path, (100, 30), body)


# -- the side panel (D2) ---------------------------------------------------------------------


@pytest.mark.parametrize(("size", "shown"), [((80, 24), False), ((99, 30), False),
                                             ((100, 30), True), ((120, 40), True)],
                         ids=lambda v: _ids(v) if isinstance(v, tuple) else str(v))
async def test_the_side_panel_only_from_100_columns(tmp_path, size, shown):
    async def body(tui, pilot):
        side = tui.app.query_one("#side")
        log = tui.app.query_one("#log").region
        if shown:
            assert side.region.width == spacing.SIDE_WIDTH
            assert log.right == side.region.x
        else:
            assert side.region.width == 0
            assert log.width == size[0]

    await _two_turns(tmp_path, size, body)


async def test_status_says_what_the_side_panel_says(conn, data_dir):
    terminal = ScriptedTerminal(["uno", "/status", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    assert "sends: 1" in terminal.shown
    assert "memory: 0 note(s) in the last question" in terminal.shown


# -- the person's messages (D3) --------------------------------------------------------------


async def test_the_persons_message_has_a_bar_a_fill_and_a_row_before_it(tmp_path):
    async def body(tui, pilot):
        you = list(tui.app.query("#log .you"))[-1]
        styles = you.styles
        assert styles.border_left[0] == "thick"
        assert styles.background.a > 0  # a fill of its own
        others = [w for w in tui.app.query("#log .harness, #log .foreign, #log .you")
                  if w.region.bottom <= you.region.y and w.region.height]
        above = max(w.region.bottom for w in others)
        assert you.region.y - above == spacing.ROW

    await _two_turns(tmp_path, (100, 30), body)


async def test_in_an_ansi_theme_the_bar_still_marks_the_persons_message(tmp_path):
    async def body(tui, pilot):
        tui.app.theme = "ansi-dark"
        await pilot.pause(0.2)
        you = list(tui.app.query("#log .you"))[-1]
        harness = [w for w in tui.app.query("#log .harness") if w.region.width][0]
        # The shape carries it: a drawn bar left of the message, nothing left of a harness line.
        row = tui.app.screen._compositor.render_strips()[you.region.y].text
        assert row[you.region.x] not in (" ", ""), row
        assert harness.styles.border_left[0] in ("", "none", "hidden")

    await _two_turns(tmp_path, (100, 30), body)


# -- one column grid (D4) --------------------------------------------------------------------


@pytest.mark.parametrize("size", SIZES, ids=_ids)
async def test_text_starts_on_one_column(tmp_path, size):
    async def body(tui, pilot):
        columns = {
            "you": list(tui.app.query("#log .you"))[-1].content_region.x,
            "harness": [w for w in tui.app.query("#log .harness")
                        if w.region.width][0].content_region.x,
            "foreign": list(tui.app.query("#log .foreign"))[-1].content_region.x,
            "input": tui.app.query_one(PromptInput).content_region.x,
        }
        assert len(set(columns.values())) == 1, columns
        assert columns["you"] == spacing.TEXT_COLUMN
        assert tui.app.query_one("#footer", Static).content_region.x == spacing.EDGE

    await _two_turns(tmp_path, size, body)


# -- vertical gaps by height (D5) --------------------------------------------------------------


@pytest.mark.parametrize("size", SIZES, ids=_ids)
async def test_vertical_gaps_only_where_the_rows_allow(tmp_path, size):
    async def body(tui, pilot):
        harness = list(tui.app.query("#log .harness"))
        prompt = tui.app.query_one(PromptInput)
        footer = tui.app.query_one("#footer").region
        # The footer is always there, right under the input.
        assert prompt.region.bottom == footer.y and footer.bottom == size[1]
        if size[1] < spacing.SNUG_ROWS:
            assert all(w.styles.margin.top == 0 for w in harness)
            assert prompt.region.height == 2  # one row of text under a one-row rule
        else:
            assert all(w.styles.margin.top == spacing.ROW for w in harness
                       if not w.has_class("-lead"))
            assert prompt.region.height == 3

    await _two_turns(tmp_path, size, body)


@pytest.mark.parametrize("size", SIZES, ids=_ids)
async def test_the_conversation_keeps_its_rows(tmp_path, size):
    async def body(tui, pilot):
        rows = tui.app.query_one("#log").scrollable_content_region.height
        assert rows >= ROWS_BEFORE[size], rows

    await _two_turns(tmp_path, size, body)


# -- the frame of foreign text (D6) ------------------------------------------------------------


async def test_the_foreign_frame_is_neutral(tmp_path):
    async def body(tui, pilot):
        foreign = list(tui.app.query("#log .foreign"))[-1]
        frame = foreign.styles.border_top[1]
        variables = tui.app.get_css_variables()
        # Structure, not a state: no colour a status, the approval or the person's bar uses.
        for name in ("error", "warning", "success", "accent", "primary", "secondary",
                     "text-error", "text-warning"):
            assert frame.rgb != Color.parse(variables[name]).rgb, name

    await _two_turns(tmp_path, (100, 30), body)


def test_the_app_declares_both_breakpoints():
    assert HarnessApp.HORIZONTAL_BREAKPOINTS == [(0, "-narrow"), (spacing.WIDE_COLUMNS, "-wide")]
    assert HarnessApp.VERTICAL_BREAKPOINTS == [(0, "-short"), (spacing.SNUG_ROWS, "-tall")]
