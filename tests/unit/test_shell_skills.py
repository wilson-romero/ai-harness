"""`/skill` and its approval inside the conversation (interactive-shell D8, task 5.3).

The approval prompt is the engine's, shown on the conversation's terminal; the only answer that
grants is the one typed at that prompt. A line typed at the normal prompt is a question or a
command, whatever it looks like.
"""

from __future__ import annotations

from tests.shell_support import (
    CODE,
    INTERRUPT,
    Action,
    ScriptedTerminal,
    make_conversation,
)
from tests.skill_support import ScriptedProvider, WriteEffect, copy_skills, with_effect

LINE = "/skill demo-echo text=texto-sintetico"


def _setup(conn, data_dir, tmp_path, lines, approvals):
    root = copy_skills(tmp_path)
    with_effect(root, "demo-echo", "test.write")
    effect = WriteEffect(tmp_path / "efecto")
    terminal = ScriptedTerminal(lines, approvals)
    conversation, service, provider = make_conversation(
        conn, data_dir, terminal, ScriptedProvider(), skills_dir=root,
        effects={"test.write": effect})
    return conversation, terminal, effect, provider


def _run_status(conn) -> list[str]:
    return [row[0] for row in conn.execute("SELECT status FROM skill_runs")]


def _approvals(conn) -> list[str]:
    return [row[0] for row in conn.execute("SELECT status FROM approvals")]


async def test_a_skill_approved_in_the_conversation(conn, data_dir, tmp_path):
    """Scenario «Skill aprobado en la conversación»: the effect is applied once."""
    conversation, terminal, effect, _ = _setup(conn, data_dir, tmp_path, [LINE, "/exit"], [CODE])
    assert await conversation.run() == 0
    assert len(effect.written()) == 1
    assert _run_status(conn) == ["completed"]
    assert _approvals(conn) == ["consumed"]
    assert terminal.reads == 2  # back to waiting for a line
    assert any(line.startswith("applied: efecto/") for line in terminal.shown)
    assert terminal.questions == [
        "Type the first 8 characters of the hash to approve, or n to reject: "]


async def test_the_code_is_shown_only_next_to_the_content(conn, data_dir, tmp_path):
    conversation, terminal, _, _ = _setup(conn, data_dir, tmp_path, [LINE, "/status", "/exit"],
                                          [CODE])
    await conversation.run()
    hash_lines = [line for line in terminal.shown if line.strip().startswith("hash:")]
    code = hash_lines[0].split()[-1][:8]
    assert [line for line in terminal.shown if code in line] == hash_lines


async def test_a_rejected_approval(conn, data_dir, tmp_path):
    """Scenario «Aprobación rechazada»."""
    conversation, terminal, effect, _ = _setup(conn, data_dir, tmp_path,
                                               [LINE, "/status", "/exit"], ["n"])
    assert await conversation.run() == 0
    assert effect.written() == []
    assert _run_status(conn) == ["cancelled"]
    assert _approvals(conn) == ["rejected"]
    assert any(line.startswith("last request:") for line in terminal.shown)  # still open


async def test_ctrl_c_at_the_approval_prompt_leaves_it_undecided(conn, data_dir, tmp_path):
    conversation, terminal, effect, _ = _setup(conn, data_dir, tmp_path, [LINE, "/exit"],
                                               [INTERRUPT])
    assert await conversation.run() == 0
    assert effect.written() == []
    assert _run_status(conn) == ["awaiting_approval"]
    assert _approvals(conn) == ["pending"]


def _type_the_code(term: ScriptedTerminal) -> None:
    term.lines.insert(0, term.last_code())


async def test_a_line_that_looks_like_an_approval_is_a_question(conn, data_dir, tmp_path):
    """Scenario «Línea que parece una aprobación»: the code typed at the normal prompt."""
    conversation, terminal, effect, provider = _setup(
        conn, data_dir, tmp_path, [LINE, Action(_type_the_code), "/exit"], [INTERRUPT])
    assert await conversation.run() == 0
    assert effect.written() == []
    code = terminal.last_code()
    assert provider.prompts[-1] == code  # it went to the provider as a question
    assert _approvals(conn) == ["pending"]
    assert _run_status(conn) == ["awaiting_approval"]


async def test_a_line_that_looks_like_an_approval_command_is_refused(conn, data_dir, tmp_path):
    conversation, terminal, effect, provider = _setup(
        conn, data_dir, tmp_path, [LINE, "/approve", "/exit"], [INTERRUPT])
    await conversation.run()
    assert "unknown command /approve" in terminal.text
    assert effect.written() == []


async def test_a_second_skill_in_the_session_is_refused_while_one_is_open(conn, data_dir,
                                                                          tmp_path):
    conversation, terminal, effect, _ = _setup(conn, data_dir, tmp_path, [LINE, LINE, "/exit"],
                                               [INTERRUPT, CODE])
    await conversation.run()
    assert "already has an open run" in terminal.text
    assert effect.written() == []


async def test_skill_inputs_from_a_file_and_bad_inputs(conn, data_dir, tmp_path):
    source = tmp_path / "fuente.md"
    source.write_text("texto-desde-fichero", encoding="utf-8")
    conversation, terminal, effect, provider = _setup(
        conn, data_dir, tmp_path,
        ["/skill demo-echo texto", "/skill demo-echo text=a text=b", "/skill ../x text=a",
         f"/skill demo-echo --file text={source}", "/exit"], [CODE])
    await conversation.run()
    assert "inputs are NAME=VALUE" in terminal.text
    assert "was given twice" in terminal.text
    assert "invalid skill name" in terminal.text
    assert len(effect.written()) == 1
    assert any("texto-desde-fichero" in prompt for prompt in provider.prompts)
