"""What `read` and `list` return (workspace-tools D4, B1-4): visible, redacted, bounded."""

from __future__ import annotations

import pytest

from harness.text.safe_text import terminal_safe
from harness.workspace.codes import WorkspaceRefused
from harness.workspace.render import prefixed, shown_line, visible
from harness.workspace.tools import (
    LINE_MAX_CHARS,
    LIST_MAX_ENTRIES,
    READ_MAX_OUTPUT_BYTES,
    list_folder,
    newline_style,
    read_file,
)
from tests.workspace_support import built, root  # noqa: F401 - fixtures


def test_a_long_file_gives_the_first_200_lines(root):
    result = read_file(root, "long.txt")
    assert (result.first, result.last, result.total) == (1, 200, 1000)
    assert result.rows[0] == "     1  line 1"


def test_a_range_is_honoured_and_capped(root):
    result = read_file(root, "long.txt", offset=990, limit=400)
    assert (result.first, result.last) == (990, 1000)


def test_an_offset_past_the_end_is_refused(root):
    with pytest.raises(WorkspaceRefused) as caught:
        read_file(root, "long.txt", offset=1001)
    assert caught.value.code == "offset_out_of_range"


@pytest.mark.parametrize(("offset", "limit"), [(0, 10), (1, 0), (1, 401)])
def test_a_bad_range_is_a_programming_error(root, offset: int, limit: int):
    with pytest.raises(ValueError):
        read_file(root, "long.txt", offset=offset, limit=limit)


def test_newline_and_bom_are_reported(root):
    assert read_file(root, "crlf.txt").newline == "crlf"
    assert read_file(root, "src/app.py").newline == "lf"
    bom = read_file(root, "bom.txt")
    assert bom.bom and bom.rows == ("     1  with a bom",)


@pytest.mark.parametrize(("text", "style"), [("a\nb\n", "lf"), ("a\r\nb\r\n", "crlf"),
                                             ("a\r\nb\n", "mixed"), ("a\rb", "mixed"),
                                             ("abc", "none")])
def test_newline_style(text: str, style: str):
    assert newline_style(text) == style


def test_hostile_text_is_made_visible_and_cannot_act(root):
    rows = read_file(root, "hostile.txt").rows
    joined = "\n".join(rows)
    assert "\x1b" not in joined and "‮" not in joined and "​" not in joined
    assert "\r" not in joined and "\x07" not in joined
    assert "<U+001B>[31merror: refused" in rows[0]
    assert "<U+202E>" in rows[2] and "<U+200B>" in rows[3]
    assert "carriage<U+000D>return" in rows[4]
    for row in rows:
        assert terminal_safe(row) == row


def test_every_printed_row_starts_with_the_foreign_prefix(root):
    for row in read_file(root, "README.md").rows:
        assert prefixed(row).startswith("| ")
    assert prefixed("") == "|"


def test_a_tab_is_shown(root):
    assert read_file(root, "Makefile").rows[1].endswith("<U+0009>python -m pytest")


def test_a_long_line_of_a_file_is_cut_at_500_characters(root):
    (root.path / "wide-line.txt").write_text("z" * 600 + "\n", encoding="utf-8")
    row = read_file(root, "wide-line.txt").rows[0]
    assert row == "     1  " + "z" * 500 + " … [line cut at 500 characters]"


def test_the_read_window_and_output_bounds_are_literal(root):
    assert read_file(root, "long.txt", limit=400).last == 400
    (root.path / "wide.txt").write_text(("y" * 400 + "\n") * 400, encoding="utf-8")
    rows = read_file(root, "wide.txt", limit=400).rows
    assert sum(len(r.encode()) + 1 for r in rows) <= 16 * 1024 < sum(
        len(r.encode()) + 1 for r in rows) + 409


def test_a_long_line_is_cut_with_a_mark():
    line, _ = shown_line("x" * (LINE_MAX_CHARS + 50), LINE_MAX_CHARS, " [cut]")
    assert line == "x" * LINE_MAX_CHARS + " [cut]"


def test_a_credential_in_a_line_is_masked_when_shown():
    from tests.workspace_support import builder

    line, masked = shown_line(f"key={builder.fake_aws_key()}", 500, "")
    assert masked == 1 and builder.fake_aws_key() not in line


def test_visible_escapes_line_separators():
    assert visible("a b\nc") == "a<U+2028>b<U+000A>c"


def test_the_output_is_bounded(root):
    (root.path / "wide.txt").write_text(("y" * 400 + "\n") * 400, encoding="utf-8")
    result = read_file(root, "wide.txt", limit=400)
    assert result.output_cut
    assert sum(len(r.encode()) + 1 for r in result.rows) <= READ_MAX_OUTPUT_BYTES


def test_list_marks_links_and_denied_entries_and_never_descends_into_them(built, root):
    rows = list_folder(root, depth=3).rows
    assert ".git [denied: denied_component]" in rows
    assert ".env [denied: denied_name]" in rows
    assert ".env.example" in rows
    assert "src/" in rows and "src/app.py" in rows
    assert not any(row.startswith(".git/") for row in rows)
    if built.links:
        assert "docs/out [link]" in rows
        assert "src/escape.py [link]" in rows
        assert not any(row.startswith("docs/out/") for row in rows)


def test_list_shows_a_hostile_name_escaped(root):
    rows = list_folder(root, "docs").rows
    hostile = [r for r in rows if "evil" in r]
    if not hostile:
        pytest.skip("this file system refused a control character in a name")
    assert hostile == ["docs/evil<U+001B>[31mname.md [unusable name: invisible_character]"]


def test_list_depth_one_does_not_descend(root):
    assert not any("/" in row.rstrip("/") for row in list_folder(root).rows)


def test_list_is_bounded(root):
    many = root.path / "many"
    many.mkdir()
    for n in range(505):
        (many / f"f{n:04}.txt").write_text("", encoding="utf-8")
    result = list_folder(root, "many")
    assert result.stopped and len(result.rows) == 500 == LIST_MAX_ENTRIES


def test_list_of_a_file_is_refused(root):
    with pytest.raises(WorkspaceRefused) as caught:
        list_folder(root, "README.md")
    assert caught.value.code == "not_a_directory"


def test_list_of_a_denied_folder_is_refused(root):
    with pytest.raises(WorkspaceRefused) as caught:
        list_folder(root, ".git")
    assert caught.value.code == "denied_component"


def test_a_credential_that_the_cut_makes_recognisable_is_masked():
    # Review of d0a65d8, finding 2: whole, `ghp_<36>_suffix` is no GitHub token (the `_` goes
    # on); cut at 500 characters it ends right after the 36 and is one. It must not be shown.
    token = "gh" + "p_" + "A1b2C3d4E5" * 3 + "F6g7H8"
    text = "x" * 459 + " " + token + "_suffix"
    assert len("x" * 459 + " " + token) == LINE_MAX_CHARS
    line, masked = shown_line(text, LINE_MAX_CHARS, " … [line cut at 500 characters]")
    assert token not in line and masked == 1
    assert "[REDACTED:github]" in line and line.endswith("[line cut at 500 characters]")


def test_list_says_how_many_entries_it_left_out(root):
    # Review of d0a65d8, finding 6 (D4): past the cap, the count of what was not listed.
    many = root.path / "many"
    (many / "sub").mkdir(parents=True)
    for n in range(505):
        (many / f"f{n:04}.txt").write_text("", encoding="utf-8")
    for n in range(7):
        (many / "sub" / f"g{n}.txt").write_text("", encoding="utf-8")
    result = list_folder(root, "many")
    assert result.stopped and result.missing == 6  # 506 names, 500 listed; depth 1
    deeper = list_folder(root, "many", depth=2)
    assert deeper.stopped and deeper.missing == 6 + 7


def test_the_count_of_what_was_left_out_is_bounded(root, monkeypatch):
    from harness.workspace import tools as tools_module
    monkeypatch.setattr(tools_module, "LIST_MAX_ENTRIES", 3)
    monkeypatch.setattr(tools_module, "LIST_COUNT_MAX", 10)
    many = root.path / "many"
    many.mkdir()
    for n in range(40):
        (many / f"f{n:04}.txt").write_text("", encoding="utf-8")
    result = list_folder(root, "many")
    assert len(result.rows) == 3 and result.missing == 10 and result.missing_capped
