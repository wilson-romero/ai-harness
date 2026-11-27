"""What the conversation prints, as rows (interactive-shell D9; shell-appearance D2-D4).

Every line is cut into rows narrower than the terminal (`wrap_rows`). A row of text from
outside the harness starts with FOREIGN_PREFIX, or CONTINUATION_PREFIX when it continues the
row above; no row of the harness starts with `|` unless it continues a harness line. That is
the mark that tells foreign text apart, and it holds without colour, when the text is copied
and at a dumb terminal.

A styled row is a list of segments (style name, text). Styling never changes a character: the
text of a styled row is exactly the plain row, so the styled path and the plain path print the
same characters (shell-appearance D3). The Markdown subset (`markdown_styles`) only chooses the
style of characters of text that has already been cleaned and redacted; it never interprets an
escape sequence, a link, HTML or an image: they are characters like any other.

Only the standard library: the styled terminal turns style names into colours.
"""

from __future__ import annotations

import re
import unicodedata

from harness.text.safe_text import safe_foreign_text, terminal_safe

FOREIGN_PREFIX = "| "  # no harness line starts with "|"
CONTINUATION_PREFIX = "|+"  # a row that continues the line above it (cut to the terminal width)
MIN_COLUMNS = 20
MAX_SHOWN_CHARS = 256 * 1024  # of one foreign text; the rest is counted, not shown

Segment = tuple[str, str]  # (style name, text)
Row = list[Segment]

# Style names. The styled terminal maps each one to a colour; the plain path ignores them.
GUTTER = "gutter"  # FOREIGN_PREFIX and CONTINUATION_PREFIX
FOREIGN = "foreign"
HARNESS = "harness"
HARNESS_ERROR = "harness.error"
HARNESS_WARNING = "harness.warning"
STATUS = "status"
MD_HEADING = "md.heading"
MD_BULLET = "md.bullet"
MD_QUOTE = "md.quote"
MD_RULE = "md.rule"
MD_FENCE = "md.fence"
MD_CODE = "md.code"
MD_STRONG = "md.strong"
MD_EM = "md.em"
MD_LINK = "md.link"

_HARNESS_STYLES = (
    (("error:",), HARNESS_ERROR),
    (("warning:", "interrupted:", "omitted:", "Not confirmed", "That is not"), HARNESS_WARNING),
)


EMOJI_PRESENTATION = "\ufe0f"  # VS16: draws the character before it as a two-column emoji


def _char_columns(char: str) -> int:
    """Columns a character takes at a terminal: 0 for combining and format characters, 2 for
    wide and full-width ones, 8 for a tab (the most it can take), 1 otherwise. Ambiguous-width
    characters count 1, as Western terminals show them (a limit, design D9).

    VS16 counts 1 (security review 2026-11-27, F-09): it turns a one-column character such as
    U+2764 into a two-column emoji, as Rich and current terminals draw it; counted 0, a row of
    such emoji was wider than the terminal, which wrapped it into a row without the mark. After
    a character already wide it over-counts, which only cuts the row earlier."""
    if char == "\t":
        return 8
    if char == EMOJI_PRESENTATION:
        return 1
    if unicodedata.combining(char) or unicodedata.category(char) in ("Mn", "Me", "Cf"):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def wrap_rows(line: str, columns: int | None, first: str = "") -> list[str]:
    """`line` as terminal rows, each narrower than the terminal (review 2026-11-25).

    The terminal would wrap a longer line by itself, and the part it moves to the next row
    would start that row with whatever the text says there: a foreign line could start a row
    without its prefix. So every row is cut here, below `columns`: the first row starts with
    `first`, every other with CONTINUATION_PREFIX. A row ends after its last space when it has
    one, so that words (an identifier, a command) stay whole; the rows put back together are
    the line. `columns` None: no cut. Linear: a character moves to the next row at most once.
    """
    if columns is None:
        return [first + line]
    limit = max(columns, MIN_COLUMNS) - 1  # never the last column: some terminals wrap there
    lead = len(CONTINUATION_PREFIX)
    rows: list[str] = []
    current: list[str] = [first]
    widths: list[int] = [len(first)]
    used = len(first)
    space, used_to_space = -1, 0  # the row's last space: its index in `current`, width up to it
    for char in line:
        width = _char_columns(char)
        if used + width > limit and len(current) > 1:
            cut = len(current)
            if space > 0 and lead + used - used_to_space + width <= limit:
                cut = space + 1  # after the space; what follows it goes to the next row
            rows.append("".join(current[:cut]))
            current, widths = [CONTINUATION_PREFIX, *current[cut:]], [lead, *widths[cut:]]
            used, space = sum(widths), -1
        current.append(char)
        widths.append(width)
        used += width
        if char == " ":
            space, used_to_space = len(current) - 1, used
    rows.append("".join(current))
    return rows


def _bounded_clean(text: str) -> tuple[list[str], int]:
    """Foreign text bounded (MAX_SHOWN_CHARS), cleaned and redacted, as lines; and how many
    characters were left out."""
    hidden = max(0, len(text) - MAX_SHOWN_CHARS)
    shown = text[:MAX_SHOWN_CHARS] if hidden else text
    return safe_foreign_text(shown).text.split("\n"), hidden


def foreign_lines(text: str, columns: int | None = None) -> tuple[list[str], int]:
    """Text from outside the harness as printable rows, and how many characters were left out.

    Bounded first (MAX_SHOWN_CHARS), then cleaned and redacted (`safe_foreign_text`: no escape
    sequences, controls or invisible format characters), then every line is prefixed and cut
    into rows narrower than `columns` (`wrap_rows`). Linear.
    """
    lines, hidden = _bounded_clean(text)
    rows: list[str] = []
    for line in lines:
        rows += wrap_rows(line, columns, FOREIGN_PREFIX)
    return rows, hidden


def _style_rows(rows: list[str], first: str, styles: list[str], row_style: str) -> list[Row]:
    """Rows of one line (from `wrap_rows`) as styled rows: the prefix of each row in GUTTER
    (or in `row_style` for the first row of a harness line, whose `first` is empty), and each
    character of the line in its own style. Runs of one style become one segment."""
    styled: list[Row] = []
    position = 0
    for index, row in enumerate(rows):
        lead = len(first) if index == 0 else len(CONTINUATION_PREFIX)
        segments: Row = [(GUTTER, row[:lead])] if row[:lead] else []
        body = row[lead:]
        start = 0
        while start < len(body):
            style = styles[position + start] if styles else row_style
            end = start + 1
            while end < len(body) and (styles[position + end] if styles else row_style) == style:
                end += 1
            segments.append((style, body[start:end]))
            start = end
        position += len(body)
        styled.append(segments)
    return styled


def foreign_rows(text: str, columns: int | None = None, *,
                 markdown: bool = False) -> tuple[list[Row], int]:
    """`foreign_lines` as styled rows: the same characters, row by row (shell-appearance D3).
    With `markdown`, the characters of the subset get their styles (`markdown_styles`)."""
    lines, hidden = _bounded_clean(text)
    styles = markdown_styles(lines) if markdown else [[FOREIGN] * len(line) for line in lines]
    rows: list[Row] = []
    for line, line_styles in zip(lines, styles, strict=True):
        rows += _style_rows(wrap_rows(line, columns, FOREIGN_PREFIX), FOREIGN_PREFIX,
                            line_styles, FOREIGN)
    return rows, hidden


def harness_style(line: str) -> str:
    """The style of a harness line, from its own first words (never from foreign text)."""
    for starts, style in _HARNESS_STYLES:
        if line.startswith(starts):
            return style
    return HARNESS


def harness_rows(lines: list[str], columns: int | None, style: str | None = None) -> list[Row]:
    """Harness lines as styled rows (in `style`, or the one `harness_style` gives each line).
    A line that would start with `|` gets a space before it, so that only foreign text starts
    a row with the mark."""
    rows: list[Row] = []
    for line in lines:
        safe = " " + line if line.startswith("|") else line
        rows += _style_rows(wrap_rows(safe, columns), "", [], style or harness_style(safe))
    return rows


def row_text(row: Row) -> str:
    return "".join(text for _, text in row)


def plain_rows(rows: list[Row]) -> list[str]:
    return [row_text(row) for row in rows]


def rows_of_plain_text(text: str) -> list[Row]:
    """Rows already cut and marked (the approval notice the engine prints), styled by their
    mark alone: a row that starts with `|` is foreign (GUTTER, then FOREIGN), any other is the
    harness's. No foreign row can claim a harness style: it starts with the mark."""
    rows: list[Row] = []
    for row in text.split("\n"):
        if row.startswith((FOREIGN_PREFIX, CONTINUATION_PREFIX)):
            rows.append([(GUTTER, row[:2]), *([(FOREIGN, row[2:])] if row[2:] else [])])
        else:
            rows.append([(harness_style(row), row)] if row else [])
    return rows


# -- the Markdown subset (shell-appearance D3) --------------------------------------------------
#
# Line level: a fence (``` or ~~~ after at most 3 spaces) opens a code block whose lines are
# code, closed by a fence of the same kind; an ATX heading (1-6 `#` and a space, or nothing after them); a thematic break
# (3 or more `-`, `*` or `_`, spaces allowed); a list item (`-`, `*`, `+` or 1-9 digits and `.`
# or `)`, then a space); a block quote (`>`). Inline, outside code: `code`, **strong**, *em* and
# [text](url), shown as the text they are, never followed. Everything else is plain text: `_em_`
# (it would style snake_case names), tables, HTML, images, nested or multi-line spans.
#
# Every inline pattern starts with its opening character and its body cannot contain that
# character, so a failed attempt stops at the next opening character: the scan is linear.
_FENCE = re.compile(r" {0,3}(```|~~~)")
_HEADING = re.compile(r" {0,3}#{1,6}(?: |$)")
_LIST_ITEM = re.compile(r"( *)(?:[-*+]|[0-9]{1,9}[.)]) ")
_QUOTE = re.compile(r" {0,3}>")
_INLINE = re.compile(
    r"(?P<code>`[^`]+`)"
    r"|(?P<strong>\*\*[^*]+\*\*)"
    r"|(?P<em>\*[^*\s][^*]*\*)"
    r"|(?P<link>\[[^\[\]]+\]\([^()\s]+\))"
)
_INLINE_STYLES = {"code": MD_CODE, "strong": MD_STRONG, "em": MD_EM, "link": MD_LINK}


def _thematic_break(line: str) -> bool:
    indent = len(line) - len(line.lstrip(" "))
    marks = line.replace(" ", "")
    return indent <= 3 and len(marks) >= 3 and marks[0] in "-*_" and marks == marks[0] * len(marks)


def _inline(line: str, start: int, styles: list[str]) -> None:
    for match in _INLINE.finditer(line, start):
        style = _INLINE_STYLES[match.lastgroup or "code"]
        styles[match.start():match.end()] = [style] * (match.end() - match.start())


def markdown_styles(lines: list[str]) -> list[list[str]]:
    """The style of every character of every line (cleaned text): one list per line, as long
    as the line. Linear in the length of the text."""
    result: list[list[str]] = []
    fence = ""  # the fence that opened the code block we are in; "" outside one
    for line in lines:
        styles = [FOREIGN] * len(line)
        opening = _FENCE.match(line)
        if opening and opening.group(1) == (fence or opening.group(1)):
            fence = "" if fence else opening.group(1)  # only the same kind closes a block
            styles = [MD_FENCE] * len(line)
        elif fence:
            styles = [MD_CODE] * len(line)
        elif _HEADING.match(line):
            styles = [MD_HEADING] * len(line)
        elif _thematic_break(line):
            styles = [MD_RULE] * len(line)
        elif item := _LIST_ITEM.match(line):
            marker = len(item.group(1))
            styles[marker:item.end()] = [MD_BULLET] * (item.end() - marker)
            _inline(line, item.end(), styles)
        elif quote := _QUOTE.match(line):
            styles[:quote.end()] = [MD_QUOTE] * quote.end()
            _inline(line, quote.end(), styles)
        else:
            _inline(line, 0, styles)
        result.append(styles)
    return result


# -- the status line (shell-appearance D5) ------------------------------------------------------


def status_line(project: str | None, provider: str, session_id: object) -> str:
    """Project, provider and the first 8 characters of the session: harness state only, read
    again each time it is shown, so it always names the session held now (SEC-02)."""
    return "  ".join([
        "ai-harness",
        terminal_safe(project or "-"),
        terminal_safe(provider),
        f"session {terminal_safe(str(session_id))[:8]}",
    ])
