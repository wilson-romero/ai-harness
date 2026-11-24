"""The one way vault text leaves the harness (SEC-01, SEC-03).

Every piece of text derived from the vault that is printed, sent to a provider or stored
(note bodies, relative paths, frontmatter values, whole headers) goes through here. The order
matters: invisible characters are dropped first and only then is the text redacted, so that a
character hidden inside a credential cannot keep the pattern from matching and then vanish.
"""

from __future__ import annotations

import unicodedata

from harness.memory.redaction import Redacted, redact

# Line and paragraph separators break lines for some readers, like a newline.
_LINE_SEPARATORS = frozenset("  ")
# The block delimiters of the context (D6). A note may not contain them; the replacements are
# look-alikes that no reader confuses with the real ones.
OPEN_DELIMITER, OPEN_REPLACEMENT = "<<<", "‹‹‹"
CLOSE_DELIMITER, CLOSE_REPLACEMENT = ">>>", "›››"


def terminal_safe(text: str) -> str:
    """One line of text: no control (Cc), format (Cf) or line separator characters.

    Format characters include the bidirectional controls ("trojan source") and the zero-width
    ones. A tab becomes a space (it separates columns); a newline is dropped.
    """
    out = []
    for char in text:
        if char == "\t":
            out.append(" ")
        elif unicodedata.category(char) in ("Cc", "Cf") or char in _LINE_SEPARATORS:
            continue
        else:
            out.append(char)
    return "".join(out)


def strip_controls(text: str) -> str:
    """`terminal_safe` line by line: the same, keeping the `\\n` line ends."""
    return "\n".join(terminal_safe(line) for line in text.split("\n"))


def safe_line(text: str) -> Redacted:
    """A single line for the terminal, the provider or SQLite: cleaned, then redacted."""
    return redact(terminal_safe(text))


def safe_text(text: str) -> Redacted:
    """A multi-line text: cleaned line by line, then redacted as a whole."""
    return redact(strip_controls(text))


def neutralise_delimiters(text: str) -> str:
    """Replace every `<<<` and `>>>`, whatever surrounds them. Linear: no pattern search."""
    return text.replace(OPEN_DELIMITER, OPEN_REPLACEMENT).replace(
        CLOSE_DELIMITER, CLOSE_REPLACEMENT
    )
