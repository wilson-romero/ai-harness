"""What completes at the conversation input (shell-appearance D6, command-completion D2).

The engine is pure (`suggest`, `rank`) except `list_folder`, which lists names of one folder.
Each guarantee has a negative control: the same check fails without the protection.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from harness.shell import completion
from harness.shell.commands import TABLE
from harness.shell.completion import (
    MAX_ITEM_CHARS,
    MAX_ITEMS,
    NONE,
    CompletionData,
    Item,
    SessionChoice,
    SkillChoice,
    acceptable_path,
    list_folder,
    rank,
    suggest,
)
from harness.shell.parser import COMMANDS
from harness.shell.tui import _file_choices
from tests.shell_support import ScriptedTerminal, make_conversation
from tests.skill_support import copy_skills

DATA = CompletionData(
    projects=("demo-alpha", "demo-beta"),
    skills=(SkillChoice("architecture-memory", "Extrae una decisión", ("source",)),
            SkillChoice("demo-echo", "eco", ("text",)),
            SkillChoice("dos-entradas", "dos", ("a", "b"))),
    sessions=(SessionChoice("01a2-0000-uno", "demo-alpha", "Primera"),
              SessionChoice("01a3-0000-dos", "-", "Segunda")),
)


def inserts(found) -> list[str]:
    return [item.insert for item in found.items]


# -- the commands and their arguments ---------------------------------------------------------


def test_slash_lists_every_command_of_the_one_table_with_its_summary():
    found = suggest("/", DATA)
    assert [i.insert.strip() for i in found.items] == [f"/{name}" for name in COMMANDS]
    assert [i.help for i in found.items] == [spec.summary for spec in TABLE]
    # A command that takes arguments completes with a space, so its arguments follow.
    assert "/skill " in inserts(found) and "/status" in inserts(found)


@pytest.mark.parametrize(("text", "expected"), [
    ("/s", ["/status", "/sessions", "/skill "]),
    ("/sk", ["/skill "]),
    ("/nada", []),
])
def test_typing_filters_by_the_start_first(text, expected):
    assert inserts(suggest(text, DATA))[: len(expected)] == expected


def test_then_fuzzy_after_the_prefix_matches():
    found = inserts(suggest("/hsy", DATA))
    assert found == ["/history"]  # h..s..y in order; not a prefix of anything
    ranked = rank("st", [Item("/stx"), Item("/sxt"), Item("/status")], key=lambda i: i.insert[1:])
    assert [i.insert for i in ranked] == ["/stx", "/status", "/sxt"]


@pytest.mark.parametrize(("text", "expected"), [
    ("/new ", ["demo-alpha ", "demo-beta ", "--project "]),
    ("/new --project d", ["demo-alpha ", "demo-beta "]),
    ("/new -", ["--project "]),
    ("/ne demo-b", ["demo-beta "]),  # a cut name completes its arguments too
    ("/skill ", ["architecture-memory ", "demo-echo ", "dos-entradas "]),
    ("/skill dos-entradas ", ["a=", "b=", "--file "]),
    ("/skill dos-entradas --file ", ["a=", "b="]),
    ("/skill dos-entradas a=1 --", ["--file "]),
    ("/resume 01a3", ["01a3-0000-dos"]),
    ("/resume Prim", ["01a2-0000-uno"]),  # by the title
])
def test_arguments_complete_from_harness_data(text, expected):
    assert inserts(suggest(text, DATA)) == expected


def test_the_session_list_shows_its_project_and_title():
    found = suggest("/resume ", DATA)
    assert [i.help for i in found.items] == ["demo-alpha  Primera", "-  Segunda"]


@pytest.mark.parametrize("text", [
    "", "pregunta /s", "//s", "/help ", "/status x", "/memory a", "/new demo-alpha Mi",
    "/new --project demo-alpha ", "/resume 2", '/file "a', "/skill demo-echo text=va",
    "/nada x", "/s x",  # an ambiguous cut name completes no argument
])
def test_nothing_completes_where_text_is_typed_freely(text):
    found = suggest(text, DATA)
    assert not found.items and found.path is None


def test_paths_complete_where_a_command_takes_a_path():
    assert (suggest("/file docs/a", DATA).path, suggest("/file docs/a", DATA).start) == (
        "docs/a", 6)
    one_input = suggest("/skill architecture-memory tests/x", DATA)
    assert one_input.path == "tests/x"  # a skill with one input: a bare path is that input
    assert suggest("/skill dos-entradas tests/x", DATA).path is None  # two inputs: no
    value = suggest("/skill dos-entradas --file b=tests/x", DATA)
    assert (value.path, value.prefix) == ("tests/x", "b=")


def test_a_title_in_the_list_is_one_clean_bounded_line():
    data = CompletionData(sessions=(SessionChoice(
        "01a4", "-", "Approval requested\n\x1b[31mrojo\x1b]8;;http://x\x07enlace" + "x" * 500),))
    (item,) = suggest("/resume 01a", data).items
    assert "\n" not in item.help and "\x1b" not in item.help
    assert len(item.help) <= completion.MAX_HELP_CHARS
    # Negative control: the raw title has all of it.
    assert "\x1b" in data.sessions[0].title and len(data.sessions[0].title) > 500


def test_the_list_is_bounded():
    data = CompletionData(projects=tuple(f"p{n:05}" for n in range(5000)))
    assert len(suggest("/new ", data).items) == MAX_ITEMS
    assert len(rank("", [Item(str(n)) for n in range(5000)])) == MAX_ITEMS


def test_ranking_is_linear():
    names = [Item("a" * 200 + str(n)) for n in range(20_000)]
    started = time.monotonic()
    rank("a" * 150 + "zz", names)
    assert time.monotonic() - started < 2.0


# -- paths -------------------------------------------------------------------------------------


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    root = tmp_path / "trabajo"
    (root / "docs" / "sub").mkdir(parents=True)
    (root / "docs" / "nota.md").write_text("contenido", encoding="utf-8")
    (root / "docs" / "notas-viejas").mkdir()
    (root / "docs" / ".oculto.md").write_text("x", encoding="utf-8")
    (root / "datos.md").write_text("x", encoding="utf-8")
    return root


def test_a_folder_lists_folders_first_then_files_relative_to_the_working_folder(folder):
    listing = list_folder("docs/no", cwd=folder)
    assert [i.insert for i in listing.items] == ["docs/notas-viejas/", "docs/nota.md"]
    assert [i.kind for i in listing.items] == ["folder", "file"]
    assert [i.insert for i in list_folder("", cwd=folder).items] == ["docs/", "datos.md"]


def test_hidden_names_only_when_the_name_typed_starts_with_a_dot(folder):
    assert ".oculto.md" not in str(list_folder("docs/", cwd=folder).items)
    assert [i.insert for i in list_folder("docs/.", cwd=folder).items][0] == "docs/.oculto.md"


def test_tilde_lists_the_home_folder_and_stays_in_the_text(folder):
    listing = list_folder("~/do", cwd=Path("/"), home=folder)
    assert [i.insert for i in listing.items][0] == "~/docs/"  # then fuzzy: ~/datos.md
    assert [i.insert for i in list_folder("~").items] == ["~/"]


def test_a_value_prefix_is_kept(folder):
    assert [i.insert for i in list_folder("da", prefix="source=", cwd=folder).items] == [
        "source=datos.md"]


@pytest.mark.parametrize("word", ["no-existe/", "datos.md/", "a\x00b/", "docs/nota.md/x"])
def test_a_folder_that_cannot_be_listed_gives_nothing_and_no_error(folder, word):
    listing = list_folder(word, cwd=folder)
    assert listing.items == ()


def test_a_folder_without_permission_gives_nothing(folder):
    locked = folder / "cerrada"
    locked.mkdir()
    (locked / "secreto.md").write_text("x", encoding="utf-8")
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("this user reads any folder (root, or a file system without modes)")
        assert list_folder("cerrada/", cwd=folder).items == ()
    finally:
        locked.chmod(0o700)


def test_a_link_is_a_name_and_is_never_followed(folder, tmp_path):
    outside = tmp_path / "fuera"
    (outside / "dentro").mkdir(parents=True)
    try:
        (folder / "enlace").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("this system does not let this user create links")
    items = list_folder("en", cwd=folder).items
    assert [(i.insert, i.kind) for i in items] == [("enlace", "link")]  # no trailing /
    # Negative control: what is behind the link is a folder.
    assert (folder / "enlace").is_dir()


def test_listing_reads_names_never_contents(folder, monkeypatch):
    opened: list[str] = []
    real_open = os.open

    def spy(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        opened.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    monkeypatch.setattr("builtins.open", lambda *a, **k: opened.append(str(a[0])))
    assert list_folder("docs/", cwd=folder).items
    assert not [p for p in opened if p.endswith(".md")]


def test_hostile_names_are_never_offered(folder):
    hostile = ["n\x1b[31mrojo.md", "con espacio.md", 'comilla".md', "x‮dm.exe",
               "salto\nlinea.md", "x" * (MAX_ITEM_CHARS + 5) + ".md"]
    made = []
    for name in hostile:
        try:
            (folder / name).write_text("x", encoding="utf-8")
            made.append(name)
        except OSError:  # a file system that refuses the name: nothing to offer
            pass
    (folder / "nota-buena.md").write_text("x", encoding="utf-8")
    offered = [i.insert for i in list_folder("", cwd=folder).items]
    assert not set(made) & set(offered)
    assert "nota-buena.md" in offered
    # Negative control: the names are really there on the disk.
    assert len(set(made) & {p.name for p in folder.iterdir()}) == len(made)


@pytest.mark.parametrize(("name", "ok"), [
    ("nota.md", True), ("dir/nota.md", True), ("mal\x1b[31m.md", False), ("‮dm.exe", False),
    ("con espacio.md", False), ('comilla".md', False), ("", False),
])
def test_a_path_is_offered_only_if_it_shows_and_parses_as_typed(name, ok):
    assert acceptable_path(name) is ok


def test_a_folder_of_fifty_thousand_entries_is_listed_in_bounded_time(tmp_path):
    big = tmp_path / "grande"
    big.mkdir()
    for number in range(50_000):
        (big / f"f{number:05}.md").touch()
    started = time.monotonic()
    listing = list_folder("grande/f4999", cwd=tmp_path)
    took = time.monotonic() - started
    assert took < completion.SCAN_S + 1.0
    assert len(listing.items) <= MAX_ITEMS
    cut = list_folder("grande/", cwd=tmp_path, limit=1000)
    assert cut.cut and cut.entries == 1000  # the bound holds: nothing past it is looked at


def test_the_file_picker_skips_names_it_could_not_show(tmp_path, monkeypatch):
    (tmp_path / "nota.md").write_text("x", encoding="utf-8")
    (tmp_path / "otra nota.md").write_text("x", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert _file_choices() == ["nota.md"]


# -- the snapshot the conversation hands over ---------------------------------------------------


async def test_the_conversation_offers_projects_skills_and_sessions(conn, data_dir, tmp_path,
                                                                    vault):
    root = copy_skills(tmp_path)
    (root / "No-Es-Skill").mkdir()
    (root / "fichero-suelto").write_text("x", encoding="utf-8")
    (vault / "projects" / "no es proyecto").mkdir()
    (vault / "projects" / "suelto.md").write_text("x", encoding="utf-8")
    terminal = ScriptedTerminal(["/sessions", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, skills_dir=root,
                                           vault=vault)
    await conversation.run(None, "demo-alpha")
    data = conversation._completion_data()
    assert data.projects == ("demo-alpha", "demo-beta")
    names = [skill.name for skill in data.skills]
    assert "demo-echo" in names and "No-Es-Skill" not in names
    assert data.skill("demo-echo").inputs == ("text",)
    assert [s.project for s in data.sessions] == ["demo-alpha"]


async def test_without_a_vault_there_are_no_projects_and_no_error(conn, data_dir):
    terminal = ScriptedTerminal(["/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    assert conversation._completion_data().projects == ()
    assert suggest("/new ", conversation._completion_data()) != NONE  # still --project


# -- a candidate is offered only if it reads back as the one word it is (independent review) --

# Each is split by the parser (any `isspace()` character cuts a word) or read as an option.
SPLIT_NAMES = (
    " z.md",  # a leading space: shown almost like z.md, read as z.md
    "a\u00a0--file\u00a0focus=.env",  # NBSP: one name, three words, the last one an option
    "--file\u00a0source=.env",  # starts as an option
    "b\u202fc.md",  # NARROW NO-BREAK SPACE
    "d\u3000e.md",  # IDEOGRAPHIC SPACE
    "f\u2007g.md",  # FIGURE SPACE
    "-x.md",  # a leading dash: an option to the parser
)


def _reads_back(word: str) -> bool:
    from harness.shell.parser import split_words

    return split_words(word) == [word]


def test_names_the_parser_would_split_or_take_as_an_option_are_never_offered(tmp_path):
    made = []
    for name in (*SPLIT_NAMES, "z.md", "ok.md"):
        try:
            (tmp_path / name).write_text("x", encoding="utf-8")
            made.append(name)
        except OSError:
            pass
    assert "a\u00a0--file\u00a0focus=.env" in made and "b\u202fc.md" in made
    offered = [item.insert for item in list_folder("", cwd=tmp_path).items]
    assert sorted(offered) == ["ok.md", "z.md"]
    offered = [item.insert for item in list_folder("", prefix="source=", cwd=tmp_path).items]
    assert sorted(offered) == ["source=ok.md", "source=z.md"]
    # Negative control: each of them really is cut by the parser or starts as an option.
    assert not [name for name in SPLIT_NAMES if _reads_back(name) and not name.startswith("-")]


def test_every_source_offers_only_what_reads_back_as_one_word():
    nbsp = "\u00a0"
    data = CompletionData(
        projects=(f"demo{nbsp}--project", "-p", "bueno"),
        skills=(SkillChoice(f"one{nbsp}x", "s", ("source",)),
                SkillChoice("one", "s", (f"source{nbsp}--file", "-in", "ok"))),
        sessions=(SessionChoice(f"01a5{nbsp}--x", "-", "t"), SessionChoice("01a6", "-", "t")))
    assert inserts(suggest("/new ", data)) == ["bueno ", "--project "]
    assert inserts(suggest("/skill ", data)) == ["one "]
    assert inserts(suggest("/skill one ", data)) == ["ok=", "--file "]
    assert inserts(suggest("/resume 01a", data)) == ["01a6"]
    # Negative control: the data holds them; only the offer leaves them out.
    assert f"demo{nbsp}--project" in data.projects and not _reads_back(f"demo{nbsp}--project")


async def test_the_sessions_for_the_list_are_read_with_a_bound(conn, data_dir):
    """Read at every line: the database gives at most MAX_SESSIONS rows, the newest, never the
    whole table (independent review, 2026-11-27)."""
    terminal = ScriptedTerminal(["/exit"])
    conversation, service, _ = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    for number in range(completion.MAX_SESSIONS + 20):
        service.create_session(f"sesion {number}")
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        data = conversation._completion_data()
    finally:
        conn.set_trace_callback(None)
    assert len(data.sessions) == completion.MAX_SESSIONS
    newest = [str(s.session_id) for s in service.list_sessions()[: completion.MAX_SESSIONS]]
    assert [s.session_id for s in data.sessions] == newest
    reads = [sql for sql in statements if "FROM sessions" in sql]
    assert reads and all(f"LIMIT {completion.MAX_SESSIONS}" in sql for sql in reads), reads
