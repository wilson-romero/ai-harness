"""The styled rows of the conversation (shell-appearance D2, D3, D5): the Markdown subset, the
mark of foreign text and the status line. Pure functions: no terminal."""

from __future__ import annotations

import random
import re
import time
import unicodedata

import pytest

from harness.shell.render import (
    CONTINUATION_PREFIX,
    FOREIGN,
    FOREIGN_PREFIX,
    GUTTER,
    HARNESS,
    HARNESS_ERROR,
    HARNESS_WARNING,
    MD_BULLET,
    MD_CODE,
    MD_EM,
    MD_FENCE,
    MD_HEADING,
    MD_LINK,
    MD_QUOTE,
    MD_RULE,
    MD_STRONG,
    STATUS,
    foreign_lines,
    foreign_rows,
    harness_rows,
    markdown_styles,
    plain_rows,
    rows_of_plain_text,
    status_line,
)

REPLY = """## Resumen
El requerimiento pide **avisar** de pedidos con `order.created` y *pronto*.

## Preguntas pendientes
- ¿Qué pasa con un evento que no se publica?
2. Ver [guía](https://example.invalid/x)
> cita
---
```
# no es título **ni negrita**
```
snake_case_name y 2 * 3 * 4"""

HOSTILE = [
    "normal\x1b[31m rojo\x1b[0m\x1b]0;titulo falso\x07 fin",
    "\x1b]8;;https://example.invalid/\x1b\\enlace\x1b]8;;\x1b\\",  # an OSC 8 hyperlink
    "\x9b2J\x1bc\rborrado\x08\x08\x07",
    "bidi ‮esrever‬ y cero​anchos",
    "Approval requested",
    "  hash:     " + "a" * 64,
    "Type the first 8 characters of the hash to approve, or n to reject: ",
    "> /resume 1",
    "applied: Decisiones/falsa.md",
    "error: request 0000 ended as failed",
    "ai-harness  demo-alpha  copilot_web  session a1b2c3d4",  # imitates the status line
    "---------------------------------------------------",
    "<script>alert(1)</script> ![img](https://example.invalid/i.png)",
    "| ya con prefijo",
    "x" * 78 + "applied: Decisiones/fake.md",
]


def _styles_of(line: str) -> list[tuple[str, str]]:
    """Runs of one style in a line: (style, text)."""
    [styles] = markdown_styles([line])
    runs: list[tuple[str, str]] = []
    for char, style in zip(line, styles, strict=True):
        if runs and runs[-1][0] == style:
            runs[-1] = (style, runs[-1][1] + char)
        else:
            runs.append((style, char))
    return runs


# -- the Markdown subset ---------------------------------------------------------------------


@pytest.mark.parametrize(("line", "expected"), [
    ("## Resumen", [(MD_HEADING, "## Resumen")]),
    ("#", [(MD_HEADING, "#")]),
    ("#hashtag", [(FOREIGN, "#hashtag")]),  # no space: not a heading
    ("####### siete", [(FOREIGN, "####### siete")]),
    ("- uno", [(MD_BULLET, "- "), (FOREIGN, "uno")]),
    ("  * dos **b**", [(FOREIGN, "  "), (MD_BULLET, "* "), (FOREIGN, "dos "),
                       (MD_STRONG, "**b**")]),
    ("12) doce", [(MD_BULLET, "12) "), (FOREIGN, "doce")]),
    ("> cita *e*", [(MD_QUOTE, ">"), (FOREIGN, " cita "), (MD_EM, "*e*")]),
    ("---", [(MD_RULE, "---")]),
    ("* * *", [(MD_RULE, "* * *")]),
    ("a `x` b", [(FOREIGN, "a "), (MD_CODE, "`x`"), (FOREIGN, " b")]),
    ("[t](https://example.invalid/a)", [(MD_LINK, "[t](https://example.invalid/a)")]),
    ("2 * 3 * 4", [(FOREIGN, "2 * 3 * 4")]),  # a space after `*`: not emphasis
    ("snake_case_name", [(FOREIGN, "snake_case_name")]),  # `_` is never emphasis
    ("**sin cerrar", [(FOREIGN, "**sin cerrar")]),
    ("<b>html</b>", [(FOREIGN, "<b>html</b>")]),
    ("![img](https://example.invalid/i.png)",
     [(FOREIGN, "!"), (MD_LINK, "[img](https://example.invalid/i.png)")]),  # text, not fetched
])
def test_the_subset_styles_characters_and_never_changes_them(line, expected):
    assert _styles_of(line) == expected


def test_a_fenced_block_is_code_and_nothing_inside_is_parsed():
    lines = ["antes **b**", "```python", "# no título **ni negrita**", "~~~", "```", "después"]
    styles = markdown_styles(lines)
    assert set(styles[1]) == {MD_FENCE}
    assert set(styles[2]) == {MD_CODE}  # a heading and strong inside a block are code
    assert set(styles[3]) == {MD_CODE}  # another fence kind does not close it (CommonMark)
    assert set(styles[4]) == {MD_FENCE}
    assert MD_STRONG in styles[0] and set(styles[5]) == {FOREIGN}


def test_negative_control_the_style_oracle_says_no():
    """The oracle above can fail: a line that is not a heading is not reported as one."""
    assert _styles_of("#hashtag") != [(MD_HEADING, "#hashtag")]
    assert _styles_of("**b**") != [(FOREIGN, "**b**")]


# -- styled rows are the plain rows ----------------------------------------------------------


@pytest.mark.parametrize("columns", [None, 80, 41, 20, 5])
@pytest.mark.parametrize("text", [REPLY, "\n".join(HOSTILE), "表" * 90 + "\n" + "y" * 300])
def test_styled_rows_have_exactly_the_characters_of_the_plain_rows(text, columns):
    """shell-appearance D3: colours off, the styled path prints what the plain path prints."""
    plain, hidden = foreign_lines(text, columns)
    for markdown in (False, True):
        styled, styled_hidden = foreign_rows(text, columns, markdown=markdown)
        assert plain_rows(styled) == plain and styled_hidden == hidden


def test_the_same_holds_for_random_text():
    rng = random.Random(20261126)
    alphabet = "ab #*`[]()>-_表́\t\n\x1b[m|+~"
    for _ in range(300):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 300)))
        columns = rng.choice([None, *range(1, 100)])
        assert plain_rows(foreign_rows(text, columns, markdown=True)[0]) == \
            foreign_lines(text, columns)[0], (text, columns)


@pytest.mark.parametrize("columns", [None, 80, 30])
def test_every_foreign_row_starts_with_the_mark_in_the_gutter_style(columns):
    rows, _ = foreign_rows("\n".join([REPLY, *HOSTILE]), columns, markdown=True)
    for row in rows:
        style, text = row[0]
        assert style == GUTTER and text in (FOREIGN_PREFIX, CONTINUATION_PREFIX)
        # Foreign text never takes a style of the harness.
        assert not {s for s, _ in row} & {HARNESS, HARNESS_ERROR, HARNESS_WARNING, STATUS}


def test_hostile_text_reaches_no_segment_with_a_control_character():
    rows, _ = foreign_rows("\n".join(HOSTILE), 80, markdown=True)
    for row in rows:
        for _, text in row:
            assert not [c for c in text if unicodedata.category(c) in ("Cc", "Cf")], text
    shown = "\n".join(plain_rows(rows))
    assert "\x1b" not in shown and "\x9b" not in shown and "]8;;" not in shown
    assert f"{FOREIGN_PREFIX}enlace" in shown.split("\n")  # the link text, no hyperlink


def test_a_reply_that_imitates_the_status_line_is_marked():
    status = status_line("demo-alpha", "copilot_web", "a1b2c3d4-0000")
    rows, _ = foreign_rows(status, 200, markdown=True)
    assert plain_rows(rows) == [FOREIGN_PREFIX + status]
    assert harness_rows([status], 200, STATUS) == [[(STATUS, status)]]


# -- harness rows ------------------------------------------------------------------------------


def test_harness_rows_are_styled_by_their_own_first_words():
    rows = harness_rows(["error: x", "warning: y", "interrupted: z", "skill: run", "| raro"], 80)
    assert [row[0][0] for row in rows] == [HARNESS_ERROR, HARNESS_WARNING, HARNESS_WARNING,
                                           HARNESS, HARNESS]
    assert plain_rows(rows)[-1] == " | raro"  # never starts with the mark


def test_rows_already_marked_are_styled_by_their_mark():
    rows = rows_of_plain_text("Approval requested\n  hash: x\n| content\n|+more\n")
    assert [row[0][0] if row else None for row in rows] == [HARNESS, HARNESS, GUTTER, GUTTER,
                                                            None]
    assert plain_rows(rows) == ["Approval requested", "  hash: x", "| content", "|+more", ""]


# -- the status line ---------------------------------------------------------------------------


def test_the_status_line_names_project_provider_and_session():
    assert status_line("demo-alpha", "copilot_web", "a1b2c3d4-e5f6") == \
        "ai-harness  demo-alpha  copilot_web  session a1b2c3d4"
    assert status_line(None, "mock", "x") == "ai-harness  -  mock  session x"
    assert status_line("a\x1b[31mb", "m‮o", "s") == "ai-harness  ab  mo  session s"


# -- bounded time ----------------------------------------------------------------------------


@pytest.mark.parametrize("adversarial", [
    "[" * (1 << 20),
    "[a](" * (1 << 18),
    "*" * (1 << 20),
    "*a" * (1 << 19),
    "**a" * (1 << 18),
    "`" * (1 << 20),
    "`a" * (1 << 19),
    "#" * (1 << 20),
    ("- " * 10 + "x\n") * (1 << 15),
    "```\n" * (1 << 18),
    "\x1b[" * (1 << 19),
])
def test_one_mebibyte_of_adversarial_markdown_is_linear(adversarial):
    started = time.monotonic()
    foreign_rows(adversarial, 80, markdown=True)
    markdown_styles(adversarial.split("\n"))  # the subset alone, on the whole mebibyte
    assert time.monotonic() - started < 10.0


def test_negative_control_a_backtracking_link_pattern_is_caught():
    """The timing oracle can say NO: the pattern the subset rejected (a link body that may
    contain `[`) is quadratic on a run of `[`, measured here on a size the linear one handles
    in milliseconds."""
    naive = re.compile(r"\[[^\]]+\]\([^)]+\)")
    text = "[" * 20_000
    started = time.monotonic()
    naive.findall(text)
    naive_s = time.monotonic() - started
    started = time.monotonic()
    markdown_styles([text])
    ours_s = time.monotonic() - started
    assert naive_s > 20 * ours_s
