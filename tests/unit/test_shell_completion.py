"""Tab completion at the conversation prompt (shell-appearance D6)."""

from __future__ import annotations

import pytest

from harness.shell.completion import NONE, PATH, acceptable_path, complete
from harness.shell.parser import COMMANDS
from harness.shell.terminal import ShellState
from harness.shell.tui import _file_choices, _path_candidates
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
    assert _path_candidates("n") == ["nota.md"]  # the others are skipped
    assert _file_choices() == ["nota.md"]  # the file picker offers the same (shell-tui D5)
    if hostile:  # negative control: the name is really there on the disk
        assert any("\x1b" in path.name for path in tmp_path.iterdir())


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
