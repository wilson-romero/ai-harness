"""How text from a work-folder file is shown (workspace-tools D4, B1-4).

File text is foreign: every invisible, control or line-separator character is written as
`<U+XXXX>` (the tab and ESC too, so an escape sequence or a bidirectional override is seen
rather than obeyed), then the line is redacted, cut, and redacted again: a credential that only
ends where the cut falls (`ghp_<36>_suffix` cut right after the 36) is one once cut (review of
d0a65d8, finding 2), as `loop.results_block` cleans again after its own cut. The caller prints it after
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
    line, count = redacted.text, redacted.count
    if len(line) > max_chars:
        again = redact(line[:max_chars])
        line, count = again.text + cut_marker, count + again.count
    assert terminal_safe(line) == line  # nothing left that a terminal would act on
    return line, count


def prefixed(line: str) -> str:
    return RESULT_PREFIX + line if line else RESULT_PREFIX.rstrip()
