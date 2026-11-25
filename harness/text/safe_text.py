"""The one way vault text leaves the harness (SEC-01, SEC-03).

Every piece of text derived from the vault that is printed, sent to a provider or stored
(note bodies, relative paths, frontmatter values, whole headers) goes through here. The order
matters: invisible characters are dropped first and only then is the text redacted, so that a
character hidden inside a credential cannot keep the pattern from matching and then vanish.
"""

from __future__ import annotations

import re
import unicodedata

from harness.text.redaction import Redacted, redact

# Line and paragraph separators break lines for some readers, like a newline.
_LINE_SEPARATORS = frozenset("  ")
# The block delimiters of the context (D6). A note may not contain them; the replacements are
# look-alikes that no reader confuses with the real ones.
OPEN_DELIMITER, OPEN_REPLACEMENT = "<<<", "‹‹‹"
CLOSE_DELIMITER, CLOSE_REPLACEMENT = ">>>", "›››"


# ECMA-48 escape sequences as a whole (independent review of 2026-11-24). Dropping only the
# ESC character leaves the rest (`[31m`, `(B`, `7`) glued to what follows, and a credential
# right after it then has no word boundary and escapes redaction. Recognised, in 7-bit form
# (ESC + byte) and, where one exists, in 8-bit C1 form:
# - CSI `ESC [` / 0x9B: parameter bytes 0x30-0x3F, intermediate 0x20-0x2F, final 0x40-0x7E;
# - control strings OSC `ESC ]` / 0x9D, DCS `ESC P` / 0x90, SOS `ESC X` / 0x98, PM `ESC ^` /
#   0x9E and APC `ESC _` / 0x9F, up to BEL, `ESC \` or ST 0x9C (or the end of the text);
# - nF `ESC` + intermediates 0x20-0x2F + one final 0x30-0x7E (`ESC ( B`);
# - two-byte Fp, Fe and Fs escapes `ESC` + 0x30-0x7E (`ESC 7`, `ESC D`, `ESC c`).
# Every part is a run over one character class, the classes that follow each other are
# disjoint and every part after the introducer is optional, so a match never backtracks:
# the substitution is linear in the length of the text (measured at 1 MiB in the tests).
_ESCAPE_SEQUENCE = re.compile(
    r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]?"
    r"|(?:\x1b[\]PX^_]|[\x90\x98\x9d\x9e\x9f])[^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)?"
    r"|\x1b[ -/]+[0-~]?"
    r"|\x1b[0-~]"
)


def drop_escape_sequences(text: str) -> str:
    """Remove whole terminal escape sequences; the cleaning functions below call it first."""
    return _ESCAPE_SEQUENCE.sub("", text)


def terminal_safe(text: str) -> str:
    """One line of text: no control (Cc), format (Cf) or line separator characters.

    Format characters include the bidirectional controls ("trojan source") and the zero-width
    ones. A tab becomes a space (it separates columns); a newline is dropped.
    """
    out = []
    for char in drop_escape_sequences(text):
        if char == "\t":
            out.append(" ")
        elif unicodedata.category(char) in ("Cc", "Cf") or char in _LINE_SEPARATORS:
            continue
        else:
            out.append(char)
    return "".join(out)


def strip_controls(text: str) -> str:
    """`terminal_safe` line by line: the same, keeping the `\\n` line ends."""
    # Sequences go before the split, so that one spanning lines is removed whole.
    return "\n".join(terminal_safe(line) for line in drop_escape_sequences(text).split("\n"))


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


def safe_foreign_line(text: str) -> Redacted:
    """`safe_line`, named for text from outside the harness's control (tool results, server
    names, requested names). Since the review of 2026-11-24 every cleaning path drops whole
    escape sequences, so this is the same function under the name its callers document."""
    return safe_line(text)


def safe_foreign_text(text: str) -> Redacted:
    """`safe_text` for text from outside the harness's control; see `safe_foreign_line`."""
    return safe_text(text)
