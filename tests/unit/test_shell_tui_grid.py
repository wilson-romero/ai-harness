"""The geometry of the approval box on the spacing scale (approval-buttons D7): the buttons,
the gaps between them and the rows around them, at the sizes a person may use."""

from __future__ import annotations

import pytest
from textual.geometry import Region
from textual.widget import Widget
from textual.widgets import Button

from harness.shell import spacing
from harness.shell.tui import ApprovalScreen, ProposalArea
from tests.skill_support import ScriptedProvider
from tests.unit.test_shell_tui import SKILL_LINE, _skill_tui

SIZES = [(80, 24), (100, 30), (120, 40)]
# The proposal rows the box gave before the scale (measured on e65d250 with LONG): below
# ROOMY_ROWS the scale may not take any of them.
ROWS_BEFORE = {(80, 24): 0, (100, 30): 7, (120, 40): 17}
LONG = ("## Resumen\n" + "\n".join(f"Línea {n} del resumen sintético." for n in range(40))
        + "\n\n## Preguntas pendientes\n- Ninguna.")


def _skill(tmp_path, *, long: bool = True):
    provider = ScriptedProvider({"tarea: demo-echo/draft": LONG}) if long else None
    tui, _ = _skill_tui(tmp_path, provider, arm_s=0)
    return tui


async def _open(tui, pilot) -> ApprovalScreen:
    await tui.send(pilot, SKILL_LINE)
    await tui.until(pilot, lambda: isinstance(tui.app.screen, ApprovalScreen))
    await tui.until(pilot, lambda: not tui.app.screen.query_one("#reject", Button).disabled)
    await pilot.pause(0.1)
    return tui.app.screen


async def _leave(tui, pilot) -> None:
    await pilot.press("ctrl+c")
    await tui.ready(pilot)
    await tui.send(pilot, "/exit")


def _row(box: ApprovalScreen, left: str, right: str) -> tuple[Region, Region, Region]:
    a = box.query_one(f"#{left}", Button).region
    b = box.query_one(f"#{right}", Button).region
    return a, b, box.query_one(f"#{left}").parent.region


def _on_the_grid(box: ApprovalScreen, left: str, right: str, size: tuple[int, int]) -> None:
    a, b, row = _row(box, left, right)
    inner = box.query_one("#approval-box").content_region
    screen = Region(0, 0, *size)
    # The same width, two 8-column steps, and the 48 px row.
    assert a.width == b.width == spacing.BUTTON_WIDTH
    assert a.width % spacing.SPACE_8 == 0
    assert a.height == b.height == spacing.BUTTON_ROWS
    # One step of the scale between them, wider than the padding around any label.
    gap = b.x - a.right
    assert gap == spacing.BUTTON_GAP
    for name in (left, right):
        label = str(box.query_one(f"#{name}", Button).label)
        assert gap > (spacing.BUTTON_WIDTH - len(label)) // 2
    # The pair is centred in its row (a column of rounding at most).
    assert abs((a.x - row.x) - (row.right - b.right)) <= 1
    # Inside the box, inside the screen.
    for region in (a, b):
        assert inner.contains_region(region), (region, inner)
        assert screen.contains_region(region)


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
async def test_the_approve_and_reject_buttons_sit_on_the_grid(tmp_path, size):
    tui = _skill(tmp_path)
    async with tui.app.run_test(size=size) as pilot:
        box = await _open(tui, pilot)
        _on_the_grid(box, "approve", "reject", size)
        await _leave(tui, pilot)


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
async def test_the_back_and_yes_buttons_sit_on_the_grid_with_their_question(tmp_path, size):
    tui = _skill(tmp_path)
    async with tui.app.run_test(size=size) as pilot:
        box = await _open(tui, pilot)
        await pilot.click("#reject")
        await tui.until(pilot, lambda: box.query_one("#approval-confirm").display)
        await pilot.pause(0.1)
        _on_the_grid(box, "reject-back", "reject-yes", size)
        # The question is whole, inside the box, above the buttons with one row between
        # (none below SNUG_ROWS), and the hint above it is not hidden behind it.
        text = box.query_one("#approval-confirm-text").region
        assert box.query_one("#approval-box").content_region.contains_region(text)
        gap = spacing.ROW if size[1] >= spacing.SNUG_ROWS else 0
        assert box.query_one("#reject-back").region.y - text.bottom == gap
        assert box.query_one("#approval-more").region.bottom <= text.y
        await _leave(tui, pilot)


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
async def test_one_blank_row_between_the_hint_lines_and_the_buttons(tmp_path, size):
    tui = _skill(tmp_path)
    async with tui.app.run_test(size=size) as pilot:
        box = await _open(tui, pilot)
        more = box.query_one("#approval-more").region
        question = box.query_one("#approval-question").region
        buttons = box.query_one("#approval-buttons").region
        assert question.y == more.bottom  # the two hint lines are one group
        # One blank row above the buttons; below SNUG_ROWS it goes to the hint lines, which
        # the buttons never cover.
        assert buttons.y - question.bottom == (spacing.ROW if size[1] >= spacing.SNUG_ROWS
                                               else 0)
        await _leave(tui, pilot)


@pytest.mark.parametrize("size", SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
async def test_the_proposal_keeps_its_rows(tmp_path, size):
    tui = _skill(tmp_path)
    async with tui.app.run_test(size=size) as pilot:
        box = await _open(tui, pilot)
        rows = box.query_one(ProposalArea).scrollable_content_region.height
        header = box.query_one("#approval-header").region
        area = box.query_one(ProposalArea).region
        frame = box.query_one("#approval-box").region
        # Two columns between the border and the content, on both sides, at every size.
        assert header.x - frame.x == area.x - frame.x == 1 + spacing.BOX_PADDING_X
        assert frame.right - area.right == 1 + spacing.BOX_PADDING_X
        if size[1] < spacing.ROOMY_ROWS:
            assert rows >= ROWS_BEFORE[size]
            assert area.y == header.bottom  # dense: no blank rows between the parts
        else:
            assert rows >= 12
            assert area.y - header.bottom == spacing.ROW  # roomy: one blank row
            inner = box.query_one("#approval-box")
            assert header.y - inner.region.y == 1 + spacing.ROW  # border, then a blank row
        await _leave(tui, pilot)


def _style(widget: Widget) -> tuple[bool, bool, bool]:
    style = widget.styles.text_style
    return bool(style.bold), bool(style.strike), bool(style.reverse)


async def test_disabled_enabled_and_focused_differ_without_colour(tmp_path):
    tui = _skill(tmp_path, long=False)
    async with tui.app.run_test(size=(100, 30)) as pilot:
        box = await _open(tui, pilot)
        await tui.until(pilot, lambda: not box.query_one("#approve", Button).disabled)
        await pilot.press("tab")
        approve, reject = box.query_one("#approve", Button), box.query_one("#reject", Button)
        assert tui.app.focused is approve
        focused, enabled = _style(approve), _style(reject)
        disabled = _style(box.query_one("#reject-yes", Button))
        assert box.query_one("#reject-yes", Button).disabled
        # Text attributes, not colours: a monochrome terminal still tells them apart.
        assert len({focused, enabled, disabled}) == 3
        assert disabled[1] and not enabled[1] and not focused[1]  # struck out while disabled
        assert focused[2] and not enabled[2]  # reversed while focused
        await _leave(tui, pilot)
