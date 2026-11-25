"""Whole terminal escape sequences are dropped before redaction (independent review of
2026-11-24, finding 3), for tool output and for vault text alike."""

from __future__ import annotations

import time

import pytest

from harness.mcp.render import clean_description
from harness.text.safe_text import (
    drop_escape_sequences,
    safe_foreign_text,
    safe_line,
    safe_text,
    strip_controls,
    terminal_safe,
)
from tests.conftest import SECRET_SAMPLES

TOKEN = SECRET_SAMPLES["github"]
SEQUENCES = {
    "tput sgr0 (xterm)": "\x1b(B\x1b[m",
    "nF: designate G0": "\x1b(B",
    "Fp: save cursor": "\x1b7",
    "Fe: index": "\x1bD",
    "Fs: reset": "\x1bc",
    "CSI colour": "\x1b[31m",
    "C1 CSI colour": "\x9b31m",
    "OSC title, BEL": "\x1b]0;titulo\x07",
    "OSC title, ST": "\x1b]0;titulo\x1b\\",
    "C1 OSC": "\x9d0;titulo\x9c",
    "DCS": "\x1bPq#0;2;0;0;0\x1b\\",
    "C1 DCS": "\x90q#0\x9c",
    "APC": "\x1b_ocult\x1b\\",
    "PM": "\x1b^ocult\x1b\\",
    "SOS": "\x1bXocult\x1b\\",
}


@pytest.mark.parametrize("sequence", list(SEQUENCES.values()), ids=list(SEQUENCES))
def test_a_token_right_after_any_escape_sequence_is_redacted(sequence):
    text = "x " + sequence + TOKEN
    for clean in (safe_foreign_text, safe_text, safe_line):
        result = clean(text)
        assert TOKEN not in result.text, (clean.__name__, result.text)
        assert "[REDACTED:github]" in result.text
        assert result.text.startswith("x ")


@pytest.mark.parametrize("sequence", list(SEQUENCES.values()), ids=list(SEQUENCES))
def test_nothing_of_the_sequence_is_left(sequence):
    assert drop_escape_sequences("a" + sequence + "b") == "ab"
    assert terminal_safe("a" + sequence + "b") == "ab"


def test_vault_text_drops_whole_sequences_too():
    """The gap disclosed in the first report: `safe_text` used to drop only the ESC byte."""
    assert safe_text("x \x1b[31m" + TOKEN).text == "x [REDACTED:github]"
    assert strip_controls("una\n\x1b[1mlinea\x1b[0m\nmas") == "una\nlinea\nmas"


def test_a_server_description_with_tput_output_hides_the_token():
    shown = clean_description("Herramienta \x1b(B\x1b[m" + TOKEN)
    assert TOKEN not in shown and "[REDACTED:github]" in shown


@pytest.mark.parametrize("adversarial", [
    "\x1b" * (1 << 20),
    "\x1b[" * (1 << 19),
    "\x1b[" + "0" * (1 << 20),
    "\x1bP" + "q" * (1 << 20),
    "\x1b]" * (1 << 19),
    "\x1b(" * (1 << 19),
    "\x1b " * (1 << 19),
    "\x9b" * (1 << 20),
    ("\x1b[0;" * 1000 + "x") * 200,
])
def test_one_mebibyte_of_escapes_is_linear(adversarial):
    started = time.monotonic()
    drop_escape_sequences(adversarial)
    safe_text(adversarial)
    assert time.monotonic() - started < 2.0
