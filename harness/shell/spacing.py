"""The spacing scale of the full screen (approval-buttons D7): every gap comes from here.

The 8-point grid measured in terminal cells. A cell is about twice as tall as it is wide
(roughly 8 x 16 px), so one column is one 8-point step and one row is two. Horizontal space
goes in columns of the scale (1, 2, 4, 8); vertical space goes in whole rows, the smallest
step there is, and only where the rows allow (`ROOMY_ROWS`).
"""

from __future__ import annotations

# Columns: one column is one 8-point step.
SPACE_1 = 1
SPACE_2 = 2
SPACE_4 = 4
SPACE_8 = 8

# Rows: one row is two steps (1 row = 2 columns, so an even inset is `padding: 1 2`); there is
# no half row.
ROW = 1
ROW_2 = 2

# A button: 16 columns wide (Textual's own minimum width, two 8-column steps) and 3 rows tall
# (about 48 px, the usual minimum touch target), so every button of a row has the same width.
BUTTON_WIDTH = 2 * SPACE_8
BUTTON_ROWS = 3
# Between two buttons: wider than the padding around any label inside a button
# (internal <= external), so a pair reads as two buttons and not one.
BUTTON_GAP = SPACE_8

# Inside a box, between its border and its content.
BOX_PADDING_X = SPACE_2

# The conversation (tui-spacing D4): two columns at the edge of the screen, one inside a framed
# block, and every line of text (typed, the harness's, foreign, the input) on one column.
EDGE = SPACE_2
BLOCK_INSET = SPACE_1
TEXT_COLUMN = EDGE + 1 + BLOCK_INSET  # the edge, a one-column frame or bar, the inset

# The side panel (tui-spacing D2): an even width, shown only from WIDE_COLUMNS.
SIDE_WIDTH = 32
WIDE_COLUMNS = 100

# Vertical gaps by terminal height (horizontal ones always stay):
# - below SNUG_ROWS every row goes to the content: no blank rows at all;
# - from SNUG_ROWS, one blank row above the buttons;
# - from ROOMY_ROWS, also a blank row inside the border and around the content.
SNUG_ROWS = 30
ROOMY_ROWS = 40

# The scale as Textual CSS variables: the screen's CSS names `$box-x`, never a bare number.
TOKENS: dict[str, int] = {
    "space-1": SPACE_1,
    "space-2": SPACE_2,
    "space-4": SPACE_4,
    "space-8": SPACE_8,
    "row": ROW,
    "row-2": ROW_2,
    "box-x": BOX_PADDING_X,
    "button-w": BUTTON_WIDTH,
    "button-rows": BUTTON_ROWS,
    "button-gap": BUTTON_GAP,
    "edge": EDGE,
    "inset": BLOCK_INSET,
    "side-w": SIDE_WIDTH,
}


def css_variables() -> str:
    """The lines that declare TOKENS at the top of a Textual stylesheet."""
    return "\n".join(f"${name}: {value};" for name, value in TOKENS.items())
