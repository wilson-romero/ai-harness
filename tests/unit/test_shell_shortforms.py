"""Short forms of the commands (command-completion D3): the parser, the expansion, and the
conversation, which shows the full command before it runs one typed short. The long forms
keep working unchanged (tests/unit/test_shell_parser.py is not touched)."""

from __future__ import annotations

import pytest

from harness.shell.commands import TABLE, help_text, resolve_name
from harness.shell.conversation import HELP
from harness.shell.parser import COMMANDS, Command, LineError, parse_line, parse_short
from harness.shell.shortforms import NOTHING_KNOWN, RUNNING, Known, expand, format_command
from tests.shell_support import ScriptedTerminal, make_conversation, statuses
from tests.skill_support import copy_skills

KNOWN = Known(is_project=lambda slug: slug in {"demo-alpha", "demo-beta"},
              skill_inputs=lambda name: {"architecture-memory": ("source",),
                                         "demo-echo": ("text",),
                                         "dos": ("a", "b")}.get(name))
SOURCE = "tests/fixtures/skill-inputs/fuente-decision.md"


# -- one table -----------------------------------------------------------------------------------


def test_the_parser_and_help_read_the_one_table():
    assert COMMANDS == {spec.name: (spec.least, spec.most) for spec in TABLE}
    assert HELP == help_text()
    for spec in TABLE:
        assert spec.usage in HELP and spec.summary in HELP


# -- a cut name ----------------------------------------------------------------------------------


@pytest.mark.parametrize(("line", "name"), [
    ("/sk demo-echo", "skill"), ("/st", "status"), ("/ses", "sessions"), ("/f a.md", "file"),
    ("/e", "exit"), ("/hi", "history"), ("/skill x", "skill"),
])
def test_a_unique_start_names_the_command(line, name):
    parsed = parse_short(line)
    assert isinstance(parsed, Command) and parsed.name == name


@pytest.mark.parametrize("line", ["/s", "/h", "/s x"])
def test_an_ambiguous_start_is_an_error_that_names_the_candidates(line):
    with pytest.raises(LineError) as refused:
        parse_short(line)
    assert "more than one command" in str(refused.value)


@pytest.mark.parametrize("line", ["/nada", "/exti", "/Help", "/", "/ help", "/help!",
                                  "/he\x1b[31mlp", "/approve", "/sk​ill"])
def test_what_is_no_start_of_a_name_is_still_unknown(line):
    with pytest.raises(LineError):
        parse_short(line)


def test_the_strict_parser_does_not_take_a_cut_name():
    """Negative control: parse_line (the long forms) still refuses `/sk`."""
    with pytest.raises(LineError):
        parse_line("/sk demo-echo")
    assert resolve_name("") is None


# -- the expansion -------------------------------------------------------------------------------


@pytest.mark.parametrize(("line", "full"), [
    ("/new demo-alpha", "/new --project demo-alpha"),
    ('/new demo-alpha "Mi sesión"', '/new --project demo-alpha "Mi sesión"'),
    ("/new otra-cosa", "/new otra-cosa"),  # not a project: the session's name, as always
    ("/new --project demo-alpha", "/new --project demo-alpha"),
    (f"/skill architecture-memory {SOURCE}",
     f"/skill architecture-memory --file source={SOURCE}"),
    ("/skill demo-echo text=hola", "/skill demo-echo text=hola"),
    ("/skill demo-echo uno dos", "/skill demo-echo uno dos"),  # two bare words: no
    ("/skill dos a.md", "/skill dos a.md"),  # two inputs: no
    ("/skill demo-echo --file text=a.md", "/skill demo-echo --file text=a.md"),
    ("/skill demo-echo text=a b.md", "/skill demo-echo text=a b.md"),  # input already given
    ("/skill no-existe a.md", "/skill no-existe a.md"),
])
def test_short_forms_expand_to_the_long_form(line, full):
    parsed = parse_short(line)
    assert format_command(expand(parsed, KNOWN)) == full
    assert parse_line(full) == expand(parsed, KNOWN)  # the line shown is the command run


def test_nothing_known_expands_nothing():
    """Negative control: the same lines with no vault and no skills stay as typed."""
    for line in ("/new demo-alpha", f"/skill architecture-memory {SOURCE}"):
        assert expand(parse_line(line), NOTHING_KNOWN) == parse_line(line)


def test_a_lookup_that_fails_expands_nothing():
    def broken(_: str):  # noqa: ANN202
        raise OSError("no")

    known = Known(is_project=broken, skill_inputs=broken)
    assert expand(parse_line("/new demo-alpha"), known) == parse_line("/new demo-alpha")


@pytest.mark.parametrize("args", [("a b",), ("",), ("x", "--file", "n=c d/e.md"), ("ñ\t1",)])
def test_the_full_line_reads_back_as_the_same_command(args):
    command = Command("skill", args)
    assert parse_line(format_command(command)) == command


# -- in the conversation (plain terminal: the same short forms) -----------------------------------


async def test_the_two_lines_of_the_owner_in_short_form(conn, data_dir, vault, tmp_path):
    source = tmp_path / "fuente.md"
    source.write_text("texto-desde-fichero", encoding="utf-8")
    root = copy_skills(tmp_path)
    terminal = ScriptedTerminal(["/new demo-alpha", f"/sk demo-echo {source}", "/exit"],
                                [None])
    conversation, service, provider = make_conversation(conn, data_dir, terminal, vault=vault,
                                                        skills_dir=root)
    await conversation.run()
    shown = terminal.shown
    first = shown.index(RUNNING + "/new --project demo-alpha")
    assert shown[first + 1].startswith("new session ") and "project demo-alpha" in shown[first + 1]
    running = RUNNING + f"/skill demo-echo --file text={source}"
    assert running in shown
    # Shown before the skill did anything: the line right after it is the skill's own.
    assert shown[shown.index(running) + 1].startswith("skill:")
    assert any("texto-desde-fichero" in prompt for prompt in provider.prompts)
    projects = [row[0] for row in conn.execute("SELECT project_id FROM sessions ORDER BY rowid")]
    assert projects == [None, "demo-alpha"]


async def test_a_command_typed_in_full_is_not_echoed(conn, data_dir, vault):
    terminal = ScriptedTerminal(["/new --project demo-alpha", "/status", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, vault=vault)
    await conversation.run()
    assert not any(line.startswith(RUNNING) for line in terminal.shown)


async def test_an_ambiguous_start_runs_nothing(conn, data_dir):
    terminal = ScriptedTerminal(["/s", "/h", "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    assert sum("more than one command" in line for line in terminal.shown) == 2
    assert provider.calls == 0 and statuses(conn) == []


async def test_a_hostile_word_in_a_short_form_is_shown_clean(conn, data_dir, tmp_path):
    root = copy_skills(tmp_path)
    terminal = ScriptedTerminal(['/sk demo-echo "a\x1b[31mb‮c.md"', "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal, skills_dir=root)
    await conversation.run()
    running = [line for line in terminal.shown if line.startswith(RUNNING)]
    assert running == [RUNNING + "/skill demo-echo --file text=abc.md"]
    assert provider.calls == 0  # the file does not exist: an error, nothing sent


async def test_resume_by_a_session_id(conn, data_dir):
    terminal = ScriptedTerminal(["/new segunda", "/exit"])
    conversation, service, _ = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    first, second = [row[0] for row in conn.execute("SELECT session_id FROM sessions "
                                                    "ORDER BY rowid")]
    terminal = ScriptedTerminal([f"/resume {first}", f"/resume {second[:6]}", "/resume zzzzzzzz",
                                 f"/res {second}", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal)
    await conversation.run(second)
    text = terminal.text
    assert f"resumed session {first}" in text
    assert "at least its first 8 characters" in text
    assert "no session has an id that starts with 'zzzzzzzz'" in text
    assert f"resumed session {second}" in text


async def test_a_path_that_starts_with_tilde_is_read_from_the_home_folder(conn, data_dir,
                                                                         tmp_path, monkeypatch):
    home = tmp_path / "casa"
    home.mkdir()
    (home / "nota.md").write_text("contenido sintético", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Path.home() where HOME is not read
    terminal = ScriptedTerminal(["/file ~/nota.md", "/file ~no/nota.md", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    assert any(line.startswith("attached nota.md") for line in terminal.shown)
    assert any("cannot be read" in line for line in terminal.shown)  # only ~/ is the home
