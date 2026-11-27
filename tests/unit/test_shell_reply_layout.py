"""Tables and code blocks in replies (reply-rendering D1-D3): laid out by the harness as literal
text. Pure functions: no terminal."""

from __future__ import annotations

import time

import pytest

from harness.shell.render import (
    FOREIGN,
    FOREIGN_PREFIX,
    GUTTER,
    MD_CODE,
    MD_EM,
    MD_FENCE,
    MD_STRONG,
    MD_TABLE,
    TABLE_MAX_CELL,
    TABLE_MAX_COLUMNS,
    TABLE_MAX_ROWS,
    _char_columns,
    foreign_lines,
    foreign_rows,
    markdown_layout,
    plain_rows,
)

TABLE = [
    "| Componente | Capa | Estado |",
    "|:-----------|:----:|-------:|",
    "| Pasarela | Integración | activo |",
    "| Motor de reglas | Dominio | en revisión |",
]


def width(text: str) -> int:
    return sum(_char_columns(char) for char in text)


def laid(lines: list[str], columns: int | None = None) -> list[str]:
    return markdown_layout(lines, columns)[0]


def cells(line: str) -> list[str]:
    return line.split(" │ ")


# -- tables ------------------------------------------------------------------------------------


def test_a_table_is_aligned_by_the_width_of_its_content():
    out = laid(TABLE)
    assert out == [
        "Componente      │    Capa     │      Estado",
        "────────────────┼─────────────┼────────────",
        "Pasarela        │ Integración │      activo",
        "Motor de reglas │   Dominio   │ en revisión",
    ]


def test_the_rule_is_harness_drawn_in_the_table_style_and_the_cells_keep_their_styles():
    lines, styles = markdown_layout(["| a | **b** |", "|---|---|", "| `c` | *d* |"], None)
    assert lines[1] == "────┼──────"  # `c` and **b** set the widths: 3 and 5
    assert set(styles[1]) == {MD_TABLE}
    separator = lines[0].index("│")
    assert styles[0][separator] == MD_TABLE
    assert MD_STRONG in styles[0]
    assert styles[2][lines[2].index("`")] == MD_CODE
    assert styles[2][lines[2].index("*")] == MD_EM


def test_wide_characters_are_measured_by_the_renderer():
    out = laid(["| 表表 | x |", "|---|---|", "| a | y |"])
    separators = {width(line[:line.index("│")]) for line in out if "│" in line}
    assert len(separators) == 1  # one column for every row, counted in cells, not characters


def test_a_table_wider_than_the_pane_wraps_its_cells_within_their_columns():
    long = "palabra " * 20
    out = laid(["| Nombre | Descripción |", "|---|---|", f"| corto | {long.strip()} |"], 40)
    assert all(width(line) <= 40 for line in out)
    positions = {width(line[:line.index("│")]) for line in out if "│" in line}
    assert len(positions) == 1  # every physical row keeps the column
    assert len(out) > 3  # the long cell took several rows
    assert " ".join(c.strip() for line in out[2:] for c in cells(line)[1:]).split() == \
        long.split()  # no word lost, in order


def test_a_table_that_cannot_fit_even_narrowed_is_literal_text():
    header = "|" + "|".join(f" c{n} " for n in range(12)) + "|"
    rule = "|" + "|".join("---" for _ in range(12)) + "|"
    lines = [header, rule, header]
    assert laid(lines, 30) == lines


@pytest.mark.parametrize("lines", [
    ["| a | b |", "|---|", "| c | d |"],  # the delimiter row has another number of cells
    ["| a | b |", "| c | d |"],  # no delimiter row
    ["| a | b |", "|-x-|---|"],  # not a delimiter
    ["| a | b |", "|---|---|", "| c | d | e |"],  # a row with more cells than the header
    ["a | b", "--- | ---", "c | d | e"],
])
def test_a_malformed_table_is_literal_text(lines):
    assert laid(lines) == lines


def test_a_table_without_outer_pipes_and_with_escaped_pipes():
    out = laid(["a | b", "--- | ---", r"x \| y | z"])
    assert out[2] == "x | y │ z"


def test_short_rows_are_padded():
    assert laid(["| a | b |", "|---|---|", "| c |"])[2] == "c │"


@pytest.mark.parametrize(("lines", "why"), [
    (["| a |", "|---|", *(["| x |"] * (TABLE_MAX_ROWS + 1))], "rows"),
    (["|" + "|".join("h" * 1 for _ in range(TABLE_MAX_COLUMNS + 1)) + "|",
      "|" + "|".join("-" for _ in range(TABLE_MAX_COLUMNS + 1)) + "|"], "columns"),
    (["| a |", "|---|", "| " + "x" * (TABLE_MAX_CELL + 1) + " |"], "cell"),
])
def test_a_table_over_the_bounds_is_literal_text(lines, why):
    assert laid(lines) == lines, why


def test_a_table_cannot_draw_a_box_or_take_a_background():
    out = laid(TABLE)
    drawn = set("".join(out)) - set("".join(TABLE))
    assert drawn <= {"─", "┼", "│", " "}  # no corners: never a closed box


def test_inside_a_code_block_a_table_is_code():
    lines = ["```", *TABLE, "```"]
    out = laid(lines)
    assert out[1:-1] == TABLE


# -- code blocks -------------------------------------------------------------------------------


def test_a_code_block_loses_its_fences_and_gets_a_label_and_rules():
    lines, styles = markdown_layout(["antes", "```python", "print('hola')", "```", "después"], 40)
    assert lines[0] == "antes" and lines[-1] == "después"
    assert not any(line.lstrip().startswith("```") for line in lines)
    top, code, bottom = lines[1], lines[2], lines[3]
    assert top.startswith("── python ") and set(top[len("── python "):]) == {"─"}
    assert code == "print('hola')" and set(styles[2]) == {MD_CODE}
    assert set(bottom) == {"─"}
    assert width(top) == width(bottom) <= 40
    assert set(styles[1]) <= {MD_TABLE, MD_FENCE} and set(styles[3]) == {MD_TABLE}


@pytest.mark.parametrize(("fence", "label"), [
    ("```", "code"),
    ("~~~ js", "js"),
    ("```python {linenos}", "python"),
    ("```" + "x" * 80, "code"),  # a label longer than the bound is not one
    ("```Approve? ──┼── yes", "code"),  # only a plain word
])
def test_the_label_is_a_short_word_of_the_info_string(fence, label):
    lines = laid([fence, "x", fence[:3]])
    assert lines[0].startswith(f"── {label} ")


def test_an_unclosed_code_block_runs_to_the_end_and_is_closed_by_a_rule():
    lines = laid(["```", "a", "b"])
    assert lines[1:3] == ["a", "b"] and set(lines[3]) == {"─"}


# -- the whole path ----------------------------------------------------------------------------


async def test_the_plain_conversation_aligns_a_reply_table_without_colour(conn, data_dir):
    """Plain mode (D4): the same layout, every row with the mark, cut to the terminal."""
    from tests.shell_support import CountingProvider, ScriptedTerminal, make_conversation

    terminal = ScriptedTerminal(["una pregunta", "/exit"])
    provider = CountingProvider(answer="\n".join([*TABLE, "```sh", "ls -l", "```"]))
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider, columns=50)
    await conversation.run(None)
    table = [line for line in terminal.shown if "│" in line or "┼" in line]
    assert table and all(line.startswith(FOREIGN_PREFIX) for line in table)
    assert len({line.index("│") for line in table if "│" in line}) == 1
    assert all(width(line) < 50 for line in terminal.shown)
    assert f"{FOREIGN_PREFIX}── sh " in "\n".join(terminal.shown)
    assert not any("```" in line for line in terminal.shown)
    assert not any("\x1b" in line for line in terminal.shown)


@pytest.mark.parametrize("columns", [None, 80, 40, 20])
def test_the_styled_rows_print_what_the_plain_rows_print(columns):
    text = "\n".join(["## T", *TABLE, "```py", "x = 1", "```", "fin"])
    styled, _ = foreign_rows(text, columns, markdown=True)
    plain, _ = foreign_lines(text, columns, markdown=True)
    assert plain_rows(styled) == plain
    assert all(row[0] == (GUTTER, FOREIGN_PREFIX) or row[0][0] == GUTTER for row in styled)


def test_without_markdown_the_table_stays_as_it_came():
    text = "\n".join(TABLE)
    plain, _ = foreign_lines(text, None)
    assert plain == [FOREIGN_PREFIX + line for line in TABLE]
    rows, _ = foreign_rows(text, None)
    assert {style for row in rows for style, _ in row} == {GUTTER, FOREIGN}


def test_hostile_cells_stay_literal_and_clean():
    text = "| a | b |\n|---|---|\n| \x1b[31mrojo | [t](https://example.invalid) |"
    rows, _ = foreign_rows(text, 80, markdown=True)
    assert all("\x1b" not in segment for row in rows for _, segment in row)


@pytest.mark.parametrize("adversarial", [
    "|" * (1 << 20),
    ("| a " * 2000 + "|\n") * 64,
    ("|---" * 4000 + "|\n") * 32,
    "| a | b |\n|---|---|\n" + "| x | y |\n" * (1 << 15),
    ("```\n" + "| a |\n") * (1 << 16),
])
def test_one_mebibyte_of_adversarial_tables_is_bounded(adversarial):
    started = time.monotonic()
    foreign_rows(adversarial, 80, markdown=True)
    foreign_rows(adversarial, None, markdown=True)
    assert time.monotonic() - started < 10.0
