"""Safe and distinguishable output in the conversation (interactive-shell D9, task 6.1)."""

from __future__ import annotations

import asyncio
import builtins
import time
import unicodedata

import pytest

from harness.shell.conversation import FOREIGN_PREFIX, MAX_SHOWN_CHARS, foreign_lines
from harness.shell.terminal import ConsoleTerminal
from tests.conftest import SECRET_SAMPLES
from tests.shell_support import CountingProvider, ScriptedTerminal, make_conversation

HOSTILE = (
    "normal\x1b[31m rojo\x1b[0m\x1b]0;titulo falso\x07 fin\n"
    "\x9b2J\x1bc\rborrado\x08\x08\x07\n"
    "bidi ‮esrever‬ y cero​anchos\n"
    "\x1bP+q\x1b\\ DCS"
)
IMITATIONS = [
    "Approval requested",
    "  hash:     " + "a" * 64,
    "Type the first 8 characters of the hash to approve, or n to reject: ",
    "error: request 0000 ended as failed: nada",
    "interrupted: the conversation is still open",
    "applied: Decisiones/falsa.md",
    "> /resume 1",
    "ai-harness conversation",
    "| ya con prefijo",
    "skill: run 0 is completed",
]


def _bad_chars(text: str) -> list[str]:
    return [f"U+{ord(c):04X}" for c in text
            if c != "\n" and unicodedata.category(c) in ("Cc", "Cf")]


async def _answer(conn, data_dir, answer: str) -> ScriptedTerminal:
    terminal = ScriptedTerminal(["pregunta", "/history", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal,
                                           CountingProvider(answer=answer))
    await conversation.run()
    return terminal


async def test_an_answer_with_control_sequences(conn, data_dir):
    """Scenario «Respuesta con secuencias de control»."""
    terminal = await _answer(conn, data_dir, HOSTILE)
    assert _bad_chars(terminal.text) == []
    assert f"{FOREIGN_PREFIX}normal rojo fin" in terminal.shown
    assert f"{FOREIGN_PREFIX}borrado" in terminal.shown


async def test_the_real_terminal_receives_no_control_byte(conn, data_dir, monkeypatch, capfd):
    """The same answer through the real console terminal: what reaches stdout, byte by byte."""
    lines = iter(["pregunta", "/exit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))
    conversation, _, _ = make_conversation(conn, data_dir, ConsoleTerminal(),
                                           CountingProvider(answer=HOSTILE))
    await conversation.run()
    out = capfd.readouterr().out.encode("utf-8")
    assert b"\x1b" not in out and b"\x9b" not in out.decode().encode("latin-1", "ignore")
    assert [b for b in out if b < 0x20 and b != 0x0A] == []
    assert _bad_chars(out.decode("utf-8")) == []


async def test_an_answer_that_imitates_the_harness(conn, data_dir):
    """Scenario «Respuesta que imita al harness»: every foreign line carries the prefix."""
    terminal = await _answer(conn, data_dir, "\n".join(IMITATIONS))
    for imitation in IMITATIONS:
        assert FOREIGN_PREFIX + imitation.rstrip() in [l.rstrip() for l in terminal.shown]
    # The answer adds no line of the harness: the unprefixed lines are exactly those of a
    # conversation whose answer is one harmless line.
    benign = await _answer(conn, data_dir, "inofensiva")
    unprefixed = [l for l in terminal.shown if not l.startswith(FOREIGN_PREFIX)]
    assert len(unprefixed) == len([l for l in benign.shown if not l.startswith(FOREIGN_PREFIX)])


async def test_an_answer_with_a_credential_is_masked(conn, data_dir):
    terminal = await _answer(conn, data_dir, "clave " + SECRET_SAMPLES["github"])
    assert SECRET_SAMPLES["github"] not in terminal.text
    assert f"{FOREIGN_PREFIX}clave [REDACTED:github]" in terminal.shown


async def test_line_separators_cannot_start_an_unprefixed_line(conn, data_dir):
    terminal = await _answer(conn, data_dir, "uno Approval requested dos\x85tres")
    assert "Approval requested" not in [l for l in terminal.shown
                                        if not l.startswith(FOREIGN_PREFIX)]


async def test_a_long_answer_is_cut_and_says_so(conn, data_dir):
    terminal = await _answer(conn, data_dir, "a" * (MAX_SHOWN_CHARS + 10))
    assert f"[10 more character(s) not shown]" in terminal.shown


async def test_harness_lines_never_start_with_the_prefix(conn, data_dir):
    terminal = ScriptedTerminal(["/new |sesión con barra", "/status", "/sessions", "/help",
                                 "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    assert not [l for l in terminal.shown if l.startswith(FOREIGN_PREFIX)]


@pytest.mark.parametrize("adversarial", [
    "\x1b" * (1 << 20),
    "\x1b[" * (1 << 19),
    "\x1b]" + "x" * (1 << 20),
    "\n" * (1 << 20),
    " " * (1 << 20),
    ("ey" + "J" + "a" * 20 + ".") * (1 << 15),
    "-----BEGIN " * (1 << 16),
    "‮" * (1 << 20),
])
def test_one_mebibyte_of_adversarial_text_is_linear(adversarial):
    started = time.monotonic()
    foreign_lines(adversarial)
    assert time.monotonic() - started < 5.0


async def test_one_mebibyte_answer_through_the_conversation(conn, data_dir):
    started = time.monotonic()
    await _answer(conn, data_dir, ("\x1b[31m" + "ab\n") * (1 << 18))
    assert time.monotonic() - started < 10.0
