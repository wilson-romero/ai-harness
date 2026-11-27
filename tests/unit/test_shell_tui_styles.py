"""Text from outside the harness never takes the look of a harness status (approval-buttons
D8): an inline `warning: ...` written by the model is not drawn like the harness's warning."""

from __future__ import annotations

from textual.style import Style

from harness.shell.render import (
    FOREIGN,
    GUTTER,
    HARNESS_ERROR,
    HARNESS_WARNING,
    MD_BULLET,
    MD_CODE,
    MD_EM,
    MD_FENCE,
    MD_HEADING,
    MD_LINK,
    MD_QUOTE,
    MD_RULE,
    MD_STRONG,
)
from harness.shell.tui import CHROME, EXCERPT_STYLE, STYLES
from tests.shell_support import CountingProvider
from tests.tui_support import SIZE, Tui
from tests.unit.test_shell_tui import _skill_tui

STATUSES = (HARNESS_ERROR, HARNESS_WARNING)
CONTENT = (FOREIGN, MD_HEADING, MD_BULLET, MD_QUOTE, MD_RULE, MD_FENCE, MD_CODE, MD_STRONG,
           MD_EM, MD_LINK)


async def test_no_style_of_foreign_text_takes_a_status_colour_a_fill_or_reverse(tmp_path):
    tui, _ = _skill_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        # Resolved with the screen's own theme, as the blocks are drawn.
        statuses = {name: Style.parse(STYLES[name]).foreground for name in STATUSES}
        assert all(colour is not None for colour in statuses.values())
        for name in CONTENT:
            style = Style.parse(STYLES[name])
            assert style.foreground not in statuses.values(), name
            assert style.background is None, name
            assert not style.reverse, name
        # The excerpt of a collapsed line is foreign or typed text too (collapsible-blocks
        # D4); the chrome of a folded block is the harness's, and only it has a fill.
        excerpt = Style.parse(EXCERPT_STYLE)
        assert excerpt.foreground not in statuses.values()
        assert excerpt.background is None and not excerpt.reverse
        assert Style.parse(CHROME).background is not None
        assert Style.parse(STYLES[GUTTER]).background is None
        await tui.ready(pilot)
        await tui.send(pilot, "/exit")


async def test_inline_code_from_the_model_is_not_drawn_like_a_harness_warning(tmp_path):
    data_dir = tmp_path / "datos"
    data_dir.mkdir()
    tui = Tui(data_dir, CountingProvider(answer="Then `warning: disk full` appears."))
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        await tui.send(pilot, "una pregunta sintética")
        await tui.until(pilot, lambda: tui.blocks("foreign"))
        await pilot.pause(0.1)
        warning = Style.parse(STYLES[HARNESS_WARNING]).foreground
        drawn = [segment for strip in tui.app.screen._compositor.render_strips()
                 for segment in strip if "warning: disk full" in segment.text]
        assert drawn, "the inline code is on the screen"
        for segment in drawn:
            colour = segment.style.color
            assert colour is not None
            assert (colour.triplet.red, colour.triplet.green, colour.triplet.blue) != (
                warning.r, warning.g, warning.b)
        await tui.ready(pilot)
        await tui.send(pilot, "/exit")
