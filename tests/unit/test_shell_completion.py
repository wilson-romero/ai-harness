"""Tab completion at the conversation prompt (shell-appearance D6)."""

from __future__ import annotations

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from harness.shell.completion import NONE, PATH, acceptable_path, complete
from harness.shell.parser import COMMANDS
from harness.shell.styled import ShellCompleter
from harness.shell.terminal import ShellState
from tests.shell_support import ScriptedTerminal, make_conversation
from tests.skill_support import copy_skills

STATE = ShellState(status=lambda: "s", resume_count=lambda: 12,
                   skill_names=lambda: ["architecture-memory", "demo-echo", "hls-review"])


@pytest.mark.parametrize(("text", "length", "candidates"), [
    ("/", 1, tuple(f"/{name}" for name in COMMANDS)),
    ("/s", 2, ("/status", "/sessions", "/skill")),
    ("/sk", 3, ("/skill",)),
    ("/nada", 5, ()),
    ("/resume ", 0, tuple(str(n) for n in range(1, 13))),
    ("/resume 1", 1, ("1", "10", "11", "12")),
    ("/skill ", 0, ("architecture-memory", "demo-echo", "hls-review")),
    ("/skill d", 1, ("demo-echo",)),
])
def test_commands_and_their_first_argument_complete(text, length, candidates):
    found = complete(text, STATE)
    assert (found.length, found.candidates) == (length, candidates)


@pytest.mark.parametrize("text", ["", "pregunta /s", "//s", " /s", "/skill demo-echo te",
                                  '/file "a', "/help x", "/memory a"])
def test_nothing_else_completes(text):
    assert complete(text, STATE) == NONE


def test_file_completes_a_path():
    found = complete("/file docs/a", STATE)
    assert (found.kind, found.word) == (PATH, "docs/a")


@pytest.mark.parametrize(("name", "ok"), [
    ("nota.md", True), ("dir/nota.md", True), ("mal\x1b[31m.md", False), ("‮dm.exe", False),
    ("con espacio.md", False), ('comilla".md', False), ("", False),
])
def test_a_path_is_offered_only_if_it_shows_and_parses_as_typed(name, ok):
    assert acceptable_path(name) is ok


def test_the_path_completer_skips_names_it_could_not_show(tmp_path, monkeypatch):
    (tmp_path / "nota.md").write_text("x", encoding="utf-8")
    (tmp_path / "otra nota.md").write_text("x", encoding="utf-8")
    try:
        (tmp_path / "n\x1b[31mrojo.md").write_text("x", encoding="utf-8")
        hostile = True
    except OSError:  # a file system that refuses the name: nothing to skip
        hostile = False
    monkeypatch.chdir(tmp_path)
    completer = ShellCompleter(STATE)
    found = [c.text for c in completer.get_completions(Document("/file n"), CompleteEvent())]
    assert found == ["ota.md"]  # only "nota.md": the others are skipped
    if hostile:  # negative control: the name is really there for the library
        raw = [c.text for c in completer._paths.get_completions(Document("n"), CompleteEvent())]
        assert any("\x1b" in text for text in raw)


def test_commands_complete_through_the_prompt_toolkit_adapter():
    found = list(ShellCompleter(STATE).get_completions(Document("/res"), CompleteEvent()))
    assert [(c.text, c.start_position) for c in found] == [("/resume", -4)]
    assert list(ShellCompleter(None).get_completions(Document("/res"), CompleteEvent())) == []


async def test_the_conversation_offers_skill_folders_and_listed_sessions(conn, data_dir,
                                                                         tmp_path):
    root = copy_skills(tmp_path)
    (root / "No-Es-Skill").mkdir()
    (root / "fichero-suelto").write_text("x", encoding="utf-8")
    terminal = ScriptedTerminal(["/sessions", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, skills_dir=root)
    await conversation.run()
    names = conversation._skill_names()
    assert "demo-echo" in names
    assert "No-Es-Skill" not in names and "fichero-suelto" not in names
    assert conversation._listed  # /resume completes 1..len of this list
