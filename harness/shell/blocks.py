"""What the full screen decides about folding the blocks of a conversation (collapsible-blocks).

Only the standard library: the screen (`tui.py`) asks these functions how many rows of a block
to show, what its collapsed line says and when a turn folds by itself. Everything here is
harness state (row counts, the harness's own lines, the provider's configured name) or an
excerpt of text the core has already cleaned and redacted, made single-line and bounded again
(`one_line`) before it is drawn next to the harness's chrome (D4).
"""

from __future__ import annotations

import enum
import re
from collections.abc import Callable

from harness.shell.render import GUTTER, MD_HEADING, Row, row_text
from harness.text.safe_text import terminal_safe

MIN_PREVIEW_LINES = 8  # the fewest rows a folded block shows
PREVIEW_RESERVE = 7  # rows of the pane kept for the turn line, borders, footer and margins
FOLD_GRACE = 4  # a block only this much longer than the preview is shown whole
PREVIEW_MAX_CHARS = 32_000  # of the rows a folded block shows (bounds the work of a preview)
KEEP_OPEN_TURNS = 2  # the newest turn and the one before it never fold by themselves
EXCERPT_MAX = 200  # characters of foreign or typed text in a collapsed line

HeightOf = Callable[[Row], int]  # the screen rows a row takes in its block, once wrapped

# Categories of a block, from the harness's own first words (never from foreign text).
REPLY = "reply"  # the provider's answer to a question
FOREIGN = "foreign"  # other text from outside the harness (/history, /context, /memory, skills)
CONTEXT = "context"  # what the memory added to a question: metadata, collapsed by default
SKILL = "skill"  # a skill's step bookkeeping: metadata, collapsed by default
ALERT = "alert"  # an error, a warning, an interruption: never folded by default
NOTICE = "notice"  # any other harness output
METADATA = frozenset({CONTEXT, SKILL})

_CONTEXT_WORDS = ("context:", "omitted:", "attached:")
_SKILL_WORDS = ("skill:", "applied:")
_ALERT_WORDS = ("error:", "warning:", "interrupted:", "Not confirmed", "That is not")
_NOT_SHOWN = re.compile(r"\[\d+ more character\(s\) not shown\]")
_SKILL_STATUS = re.compile(r"skill: run \S+ is ([a-z_]+)$")


class Fold(enum.Enum):
    COLLAPSED = "collapsed"  # one line: the harness's summary
    PREVIEW = "preview"  # the first rows and a footer that says how many are hidden
    EXPANDED = "expanded"  # every row


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def preview_lines(viewport_rows: int) -> int:
    """Rows a folded block shows: the pane less its chrome, never fewer than the minimum, so
    the newest reply fills the pane when it arrives."""
    return max(MIN_PREVIEW_LINES, viewport_rows - PREVIEW_RESERVE)


def _one_row(row: Row) -> int:  # noqa: ARG001 - the height of a row nobody measured
    return 1


def folds_by_default(rows: list[Row], preview: int, height_of: HeightOf = _one_row) -> bool:
    """Whether the rows take more of the pane than the preview and its grace, measured with
    `height_of` (the screen rows a row takes once wrapped). Stops as soon as it knows."""
    used = 0
    for row in rows:
        used += height_of(row)
        if used > preview + FOLD_GRACE:
            return True
    return False


def rows_in_preview(rows: list[Row], preview: int, height_of: HeightOf = _one_row) -> int:
    """How many whole rows a folded block shows: as many as fit in `preview` screen rows
    (each row measured with `height_of`) and in PREVIEW_MAX_CHARS of text, never fewer than
    one. A row is never cut: the footer counts whole rows."""
    shown, used, chars = 0, 0, 0
    for row in rows:
        height = height_of(row)
        chars += sum(len(text) for _, text in row)
        if shown and (used + height > preview or chars > PREVIEW_MAX_CHARS):
            break
        shown += 1
        used += height
        if used >= preview:
            break
    return shown


def hidden_footer(hidden: int) -> str:
    return f"… {hidden} more {'line' if hidden == 1 else 'lines'} · enter/click to expand"


def expanded_footer(total: int) -> str:
    return f"{plural(total, 'line')} · enter/click to collapse"


def one_line(text: str, limit: int = EXCERPT_MAX) -> str:
    """An excerpt that can sit next to the harness's chrome: no control, format or line
    separator character (`terminal_safe`), whitespace runs as one space, at most `limit`
    characters (the last one an ellipsis when it was cut)."""
    flat = " ".join(terminal_safe(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def body_text(row: Row) -> str:
    """The text of a row without its gutter (the `| ` of foreign rows)."""
    return "".join(text for style, text in row if style != GUTTER)


def outline(rows: list[Row], limit: int = EXCERPT_MAX) -> str:
    """The summary of foreign rows: the outline of their Markdown headings when they have
    any (`## Resumen · ## Alternativas`), else their first non-blank row. Headings are the
    rows `render.markdown_styles` styled as headings, outside code."""
    headings: list[str] = []
    size = 0
    for row in rows:
        if any(style == MD_HEADING for style, _ in row):
            heading = one_line(body_text(row), limit)
            headings.append(heading)
            size += len(heading) + 3
            if size > limit:
                break
    if headings:
        return one_line(" · ".join(headings), limit)
    return first_line(rows, limit)


def first_line(rows: list[Row], limit: int = EXCERPT_MAX) -> str:
    for row in rows:
        text = one_line(body_text(row), limit)
        if text:
            return text
    return ""


def category(first_row_text: str, *, foreign: bool, label: str | None) -> str:
    """The category of a block, from the harness's own words: a foreign block is the reply
    when the provider was just asked (`label`), else other foreign text."""
    if foreign:
        return REPLY if label else FOREIGN
    line = first_row_text.lstrip()
    if line.startswith(_CONTEXT_WORDS):
        return CONTEXT
    if line.startswith(_SKILL_WORDS):
        return SKILL
    if line.startswith(_ALERT_WORDS) or _NOT_SHOWN.fullmatch(line):
        return ALERT
    return NOTICE


def is_not_shown_notice(line: str) -> bool:
    """The harness line that follows foreign text cut at MAX_SHOWN_CHARS."""
    return bool(_NOT_SHOWN.fullmatch(line.strip()))


def default_fold(kind: str, rows: list[Row], preview: int,
                 height_of: HeightOf = _one_row) -> Fold:
    """Metadata collapsed to one line once it has more than one; alerts whole; anything else
    whole unless it takes more of the pane than the preview (and its grace), then folded."""
    if kind == ALERT:
        return Fold.EXPANDED
    if kind in METADATA:
        return Fold.COLLAPSED if len(rows) > 1 else Fold.EXPANDED
    return Fold.PREVIEW if folds_by_default(rows, preview, height_of) else Fold.EXPANDED


def turn_state(harness_lines: list[str], has_reply: bool, truncated: bool) -> str:
    """The state of a turn, from the harness lines it showed (never from foreign text)."""
    status = ""
    for line in harness_lines:
        match = _SKILL_STATUS.search(line.strip())
        if match:
            status = match.group(1)
    if any(line.startswith("error:") for line in harness_lines):
        return "failed"
    if any(line.startswith("interrupted:") and "uncertain" in line for line in harness_lines):
        return "uncertain"
    if any(line.startswith("interrupted:") for line in harness_lines):
        return "interrupted"
    if status:
        return status
    if truncated:
        return "truncated"
    return "completed" if has_reply else "done"


def turn_who(line: str | None, reply_label: str | None) -> str:
    """Who a turn is: the person and the provider that answered, a command, a skill, or the
    harness for what was shown before the first line."""
    if line is None:
        return "harness"
    words = line.split()
    if words[:1] == ["/skill"] and len(words) > 1:
        return one_line(f"skill {words[1]}", 60)
    if line.startswith("/") and not line.startswith("//") and words:
        return one_line(words[0], 60)
    return f"you → {reply_label}" if reply_label else "you"


def row_texts(rows: list[Row]) -> list[str]:
    return [row_text(row) for row in rows]
