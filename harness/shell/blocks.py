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
# A reply arrives whole (reply-rendering D5) unless its rows hold more characters than this:
# then it arrives folded, which bounds the work of drawing it (collapsible-blocks D6).
ARRIVE_WHOLE_MAX_CHARS = 64_000
KEEP_OPEN_TURNS = 2  # the newest turn and the one before it never fold by themselves
EXCERPT_MAX = 200  # characters of foreign or typed text in a collapsed line

HeightOf = Callable[[Row], int]  # the screen rows a row takes in its block, once wrapped

# Categories of a block, from the harness's own first words (never from foreign text).
REPLY = "reply"  # the provider's answer to a question
FOREIGN = "foreign"  # other text from outside the harness (/history, /memory, skills)
EXACT = "exact"  # what `/context` shows: exactly what is sent, so never folded by default
CONTEXT = "context"  # the summary line of what the memory added: metadata
LISTING = "listing"  # the notes omitted and the files attached: never folded by default
SKILL = "skill"  # a skill's step bookkeeping: metadata, collapsed by default
RESULT = "result"  # how a skill run ended and what it applied: never folded by default
ALERT = "alert"  # an error, a warning, an interruption: never folded by default
NOTICE = "notice"  # any other harness output
METADATA = frozenset({CONTEXT, SKILL})
ALWAYS_WHOLE = frozenset({ALERT, LISTING, EXACT, RESULT})

_CONTEXT_WORDS = ("context:",)
_LISTING_WORDS = ("omitted:", "attached:")
_SKILL_WORDS = ("skill:",)
_ALERT_WORDS = ("error:", "warning:", "interrupted:", "Not confirmed", "That is not")
_NOT_SHOWN = re.compile(r"\[\d+ more character\(s\) not shown\]")
# The state of a turn comes from whole harness lines, matched from their first character: a
# line that only contains these words (a note path after `omitted:`) never sets it (review
# 2026-11-27, finding 5).
_SKILL_STATUS = re.compile(r"skill: run \S+ is ([a-z_]+)")
_UNCERTAIN = re.compile(r"interrupted: (?:request|skill run) \S+ is uncertain\b")
# The hint of a Ctrl+C with nothing in flight (`conversation.INTERRUPT_HINT`): it interrupts
# nothing, so it says nothing about the turn it lands in (finding 6).
IDLE_INTERRUPT = "interrupted: the conversation is still open;"


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


def category(first_row_text: str, *, foreign: bool, label: str | None,
             command: str | None = None) -> str:
    """The category of a block, from the harness's own words: a foreign block is the reply
    when the provider was just asked (`label`), what `/context` shows when that is the
    command of its turn (`command`, the person's own line), else other foreign text."""
    if foreign:
        if label:
            return REPLY
        return EXACT if command == "/context" else FOREIGN
    line = first_row_text.lstrip()
    if line.startswith(_CONTEXT_WORDS):
        return CONTEXT
    if line.startswith(_LISTING_WORDS):
        return LISTING
    if line.startswith("applied:") or _SKILL_STATUS.fullmatch(line.rstrip()):
        return RESULT
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
    """Metadata collapsed to one line once it has more than one; alerts, the omitted and
    attached lines and what `/context` shows whole; a reply whole (reply-rendering D5) unless
    its rows hold more than ARRIVE_WHOLE_MAX_CHARS; anything else whole unless it takes more
    of the pane than the preview (and its grace), then folded."""
    if kind in ALWAYS_WHOLE:
        return Fold.EXPANDED
    if kind == REPLY:
        chars = 0
        for row in rows:
            chars += sum(len(text) for _, text in row)
            if chars > ARRIVE_WHOLE_MAX_CHARS:
                return Fold.PREVIEW
        return Fold.EXPANDED
    if kind in METADATA:
        return Fold.COLLAPSED if len(rows) > 1 else Fold.EXPANDED
    return Fold.PREVIEW if folds_by_default(rows, preview, height_of) else Fold.EXPANDED


def _own(harness_lines: list[str]) -> list[str]:
    return [line.rstrip() for line in harness_lines if not line.startswith(IDLE_INTERRUPT)]


def turn_has_alert(harness_lines: list[str]) -> bool:
    """Whether the turn showed an error, a warning or an interruption: it never folds by
    itself (review 2026-11-27, finding 2)."""
    return any(line.startswith(_ALERT_WORDS) for line in _own(harness_lines))


def turn_state(harness_lines: list[str], has_reply: bool, truncated: bool) -> str:
    """The state of a turn, from the harness lines it showed (never from foreign text), and
    how many warnings it had (`completed · 1 warning`)."""
    lines = _own(harness_lines)
    status = ""
    for line in lines:
        match = _SKILL_STATUS.fullmatch(line)
        if match:
            status = match.group(1)
    if any(line.startswith("error:") for line in lines):
        state = "failed"
    elif any(_UNCERTAIN.match(line) for line in lines):
        state = "uncertain"
    elif any(line.startswith("interrupted:") for line in lines):
        state = "interrupted"
    elif status:
        state = status
    elif truncated:
        state = "truncated"
    else:
        state = "completed" if has_reply else "done"
    warnings = sum(line.startswith("warning:") for line in lines)
    return f"{state} · {plural(warnings, 'warning')}" if warnings else state


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
