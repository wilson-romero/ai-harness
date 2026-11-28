"""How text from a work-folder file is shown (workspace-tools D4, B1-4).

File text is foreign: every invisible, control or line-separator character is written as
`<U+XXXX>` (the tab and ESC too, so an escape sequence or a bidirectional override is seen
rather than obeyed), then the line is redacted and cut. The caller prints it after
`RESULT_PREFIX`, as `mcp call` does, so no line of a file can pass for a line of the harness.
"""

from __future__ import annotations

from harness.skills.approvals import is_invisible
from harness.text.redaction import redact
from harness.text.safe_text import terminal_safe
from harness.workspace.paths import LINE_SEPARATORS

RESULT_PREFIX = "| "


def visible(text: str) -> str:
    return "".join(
        f"<U+{ord(c):04X}>" if is_invisible(c) or c in LINE_SEPARATORS or c == "\n" else c
        for c in text
    )


def shown_line(text: str, max_chars: int, cut_marker: str) -> tuple[str, int]:
    """One line of foreign text, safe for a terminal, and the credentials masked in it."""
    redacted = redact(visible(text))
    line = redacted.text
    if len(line) > max_chars:
        line = line[:max_chars] + cut_marker
    assert terminal_safe(line) == line  # nothing left that a terminal would act on
    return line, redacted.count


def prefixed(line: str) -> str:
    return RESULT_PREFIX + line if line else RESULT_PREFIX.rstrip()
