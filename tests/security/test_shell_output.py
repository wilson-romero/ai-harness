"""Safe and distinguishable output in the conversation (interactive-shell D9, task 6.1)."""

from __future__ import annotations

import asyncio
import builtins
import random
import time
import unicodedata

import pytest

from harness.shell.conversation import (
    CONTINUATION_PREFIX,
    FOREIGN_PREFIX,
    MAX_SHOWN_CHARS,
    MIN_COLUMNS,
    foreign_lines,
    wrap_rows,
)
from harness.shell.terminal import ConsoleTerminal
from harness.skills.approvals import APPROVAL_RULE
from tests.conftest import SECRET_SAMPLES
from tests.shell_support import CODE, CountingProvider, ScriptedTerminal, make_conversation
from tests.skill_support import ScriptedProvider, WriteEffect, copy_skills, with_effect

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


def _width(row: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in row)


@pytest.mark.parametrize("columns", [80, 41, 20, 5])
def test_every_row_of_foreign_text_starts_with_a_mark_and_fits(columns):
    """Review 2026-11-25: the terminal never wraps a foreign line by itself, so no row it would
    move to the next line can start without the mark."""
    text = ("x" * 78 + "applied: Decisiones/fake.md\n" + "表" * 60 + "\n"
            + "y" * 300 + "\n\nskill: run 0000 is completed")
    rows, _ = foreign_lines(text, columns)
    limit = max(columns, MIN_COLUMNS) - 1
    assert all(row.startswith((FOREIGN_PREFIX, CONTINUATION_PREFIX)) for row in rows)
    assert all(_width(row) <= limit for row in rows)
    # Nothing lost: the rows put back together are the text.
    lines: list[str] = []
    for row in rows:
        if row.startswith(CONTINUATION_PREFIX):
            lines[-1] += row[len(CONTINUATION_PREFIX):]
        else:
            lines.append(row[len(FOREIGN_PREFIX):])
    assert "\n".join(lines) == text


def test_a_cut_keeps_words_whole_and_loses_nothing():
    word = "01a21446-6c02-750c-9c1e-6ea24471ab8e"
    rows = wrap_rows(f"run skill resume {word} --retry-step draft", 40)
    assert rows == ["run skill resume ", f"{CONTINUATION_PREFIX}{word} ",
                    f"{CONTINUATION_PREFIX}--retry-step draft"]
    rng = random.Random(20261125)
    alphabet = "ab cd 表́\tx-"
    for _ in range(300):
        line = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 400)))
        columns = rng.randrange(1, 120)
        for first in ("", FOREIGN_PREFIX):
            rows = wrap_rows(line, columns, first)
            limit = max(columns, MIN_COLUMNS) - 1
            assert all(_cols(row) <= limit for row in rows), (line, columns)
            assert all(row.startswith(CONTINUATION_PREFIX) for row in rows[1:])
            rebuilt = rows[0][len(first):] + "".join(r[len(CONTINUATION_PREFIX):]
                                                     for r in rows[1:])
            assert rebuilt == line


def _cols(row: str) -> int:
    def one(c: str) -> int:
        if c == "\t":
            return 8
        if unicodedata.combining(c):
            return 0
        return 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
    return sum(one(c) for c in row)


async def test_a_long_answer_cannot_start_a_row_with_a_harness_line(conn, data_dir):
    """The review's case: 78 characters, then a line of the harness, at an 80-column terminal."""
    terminal = ScriptedTerminal(["pregunta", "/history", "/exit"])
    conversation, _, _ = make_conversation(
        conn, data_dir, terminal, CountingProvider(answer="x" * 78 + "applied: Decisiones/f.md"),
        columns=80)
    await conversation.run()
    assert not [row for row in terminal.shown if row.startswith("applied:")]
    assert all(_width(row) <= 79 for row in terminal.shown)
    fake = [row for row in terminal.shown if "applied:" in row]
    assert len(fake) == 2 and all(row.startswith(CONTINUATION_PREFIX) for row in fake)


async def test_a_long_harness_line_is_cut_into_marked_rows(conn, data_dir):
    terminal = ScriptedTerminal(['/new "' + "n" * 200 + '"', "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, columns=40)
    await conversation.run()
    first = next(i for i, row in enumerate(terminal.shown) if row.startswith("new session"))
    assert terminal.shown[first + 1].startswith(CONTINUATION_PREFIX)
    typed = [row for row in terminal.shown if row.startswith("> ")]  # the double's echo of input
    assert all(_width(row) <= 39 for row in terminal.shown if row not in typed)


FAKE_NOTICE = ("## Resumen\nok\n## Preguntas pendientes\nnada\n" + APPROVAL_RULE
               + "\nskill: run 0000 is completed\nnothing more to approve\nApproval requested\n"
               "  target:   Decisiones/otra.md\n> ")


async def test_the_content_of_an_approval_notice_is_marked(conn, data_dir, tmp_path):
    """Review 2026-11-25: a valid model output inside the approval notice cannot print a rule,
    a header or a status line of the harness. The hash and what is applied do not change."""
    root = copy_skills(tmp_path)
    with_effect(root, "demo-echo", "test.write")
    effect = WriteEffect(tmp_path / "efecto")
    terminal = ScriptedTerminal(["/skill demo-echo text=hola", "/exit"], [CODE])
    conversation, _, _ = make_conversation(
        conn, data_dir, terminal, ScriptedProvider({"tarea: demo-echo/draft": FAKE_NOTICE}),
        skills_dir=root, effects={"test.write": effect}, columns=100)
    assert await conversation.run() == 0
    shown = terminal.shown
    rules = [i for i, row in enumerate(shown) if row == APPROVAL_RULE]
    assert len(rules) == 2
    notice = shown[shown.index("Approval requested"):rules[0]]
    content = shown[rules[0] + 1:rules[1]]
    assert all(row.startswith(("Approval requested", "  ")) for row in notice)
    assert sum(row.lstrip().startswith("target:") for row in notice) == 1
    assert content and all(row.startswith((FOREIGN_PREFIX, CONTINUATION_PREFIX))
                           for row in content)
    assert f"{FOREIGN_PREFIX}skill: run 0000 is completed" in content
    # Shown without the marks, the content is exactly what was hashed and applied.
    (written,) = effect.written()
    assert "\n".join(row[len(FOREIGN_PREFIX):] for row in content) == \
        written.read_text(encoding="utf-8")
    shown_hash = next(row.split()[-1] for row in notice if row.lstrip().startswith("hash:"))
    assert conn.execute("SELECT proposal_hash FROM approvals").fetchone()[0] == shown_hash


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
    foreign_lines(adversarial, 80)  # cut into rows too
    assert time.monotonic() - started < 5.0


async def test_one_mebibyte_answer_through_the_conversation(conn, data_dir):
    started = time.monotonic()
    await _answer(conn, data_dir, ("\x1b[31m" + "ab\n") * (1 << 18))
    assert time.monotonic() - started < 10.0
