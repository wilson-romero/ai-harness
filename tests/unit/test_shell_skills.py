"""`/skill` and its approval inside the conversation (interactive-shell D8, task 5.3).

The approval prompt is the engine's, shown on the conversation's terminal; the only answer that
grants is the one typed at that prompt. A line typed at the normal prompt is a question or a
command, whatever it looks like.
"""

from __future__ import annotations

import asyncio

from harness.skills.engine import SkillEngine
from tests.shell_support import (
    CODE,
    INTERRUPT,
    Action,
    ScriptedTerminal,
    make_conversation,
)
from tests.skill_support import ScriptedProvider, WriteEffect, copy_skills, with_effect

LINE = "/skill demo-echo text=texto-sintetico"


def _setup(conn, data_dir, tmp_path, lines, approvals, provider=None):
    root = copy_skills(tmp_path)
    with_effect(root, "demo-echo", "test.write")
    effect = WriteEffect(tmp_path / "efecto")
    terminal = ScriptedTerminal(lines, approvals)
    conversation, service, provider = make_conversation(
        conn, data_dir, terminal, provider or ScriptedProvider(), skills_dir=root,
        effects={"test.write": effect})
    return conversation, terminal, effect, provider


class _CtrlCAfterSend(ScriptedProvider):
    """Ctrl+C reaches the conversation once the step's prompt is out (the SIGINT handler's call)."""

    conversation = None

    async def ask(self, request, on_sent) -> str:
        self.prompts.append(request.prompt)
        on_sent()
        self.conversation.interrupt()
        await asyncio.sleep(3600)
        raise AssertionError("not cancelled")


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
    """Scenario «Aprobación rechazada»: `n`, then the word `reject` (D8, decided 2026-11-25)."""
    conversation, terminal, effect, _ = _setup(conn, data_dir, tmp_path,
                                               [LINE, "/status", "/exit"], ["n", "reject"])
    assert await conversation.run() == 0
    assert effect.written() == []
    assert _run_status(conn) == ["cancelled"]
    assert _approvals(conn) == ["rejected"]
    assert terminal.questions[1].startswith("Type reject to confirm the rejection")
    assert any(line.startswith("last request:") for line in terminal.shown)  # still open


async def test_n_alone_leaves_the_approval_pending(conn, data_dir, tmp_path):
    """Scenario «Rechazo sin confirmar»: `n` and then the end of the answers."""
    conversation, terminal, effect, _ = _setup(conn, data_dir, tmp_path, [LINE, "/exit"], ["n"])
    assert await conversation.run() == 0
    assert effect.written() == []
    assert _run_status(conn) == ["awaiting_approval"]
    assert _approvals(conn) == ["pending"]
    assert "Not confirmed: the approval stays pending; nothing was rejected." in terminal.shown


async def test_n_then_other_text_is_pending_and_the_text_goes_nowhere(conn, data_dir, tmp_path):
    """The answer to the confirmation is neither a question nor a command, whatever it says."""
    for other in ["/status", "otra cosa", "REJECT", "rejected", " "]:
        conversation, terminal, effect, provider = _setup(
            conn, data_dir, tmp_path / other.strip().replace("/", "_") if other.strip()
            else tmp_path / "blank", [LINE, "/exit"], ["n", other])
        assert await conversation.run() == 0
        assert effect.written() == []
        assert provider.calls == 1  # only the skill's step
        assert other not in provider.prompts
        assert not any(line.startswith("last request:") for line in terminal.shown)
        assert _approvals(conn)[-1] == "pending"


async def test_wrong_answers_typed_ahead_leave_the_approval_pending(conn, data_dir, tmp_path):
    """Review 2026-11-25 (limit of type-ahead, D8): lines typed before the prompt can use up
    its attempts, but then nothing is decided: the approval stays pending for `skill resume`,
    which asks again with all its attempts."""
    conversation, terminal, effect, _ = _setup(conn, data_dir, tmp_path, [LINE, "/exit"],
                                               ["hola", "/status", "otra cosa"])
    assert await conversation.run() == 0
    assert len(terminal.questions) == 3
    assert effect.written() == []
    assert _run_status(conn) == ["awaiting_approval"]
    assert _approvals(conn) == ["pending"]


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


async def test_ctrl_c_during_the_llm_step_leaves_a_run_that_can_be_ended(conn, data_dir,
                                                                         tmp_path):
    """Review 2026-11-25: Ctrl+C while a step's question is out. The run is left as
    `recover_runs` leaves the run of a dead process (the step `uncertain`, never resent), the
    person is told the exact next command, and that command works once the session is free."""
    provider = _CtrlCAfterSend()
    conversation, terminal, effect, _ = _setup(conn, data_dir, tmp_path,
                                               [LINE, "/status", "/exit"], [], provider)
    provider.conversation = conversation
    assert await conversation.run() == 0
    ((run_id, run_status, run_error),) = conn.execute(
        "SELECT run_id, status, error_code FROM skill_runs").fetchall()
    assert (run_status, run_error) == ("uncertain", "interrupted")
    steps = {row[0]: row[1] for row in conn.execute(
        "SELECT step_key, status FROM skill_steps WHERE kind = 'llm'")}
    assert steps == {"draft": "uncertain"}
    assert [tuple(row) for row in conn.execute("SELECT status FROM requests")] == [
        ("uncertain",)]
    assert provider.calls == 1  # never resent
    told = next(i for i, line in enumerate(terminal.shown)
                if line.startswith("interrupted: skill run"))
    assert f"  skill resume {run_id} --retry-step draft" in terminal.shown[told:]
    assert f"  skill cancel {run_id}" in terminal.shown[told:]
    assert any(line.startswith("last request:") for line in terminal.shown)  # still open
    assert effect.written() == []
    engine = SkillEngine(conn, data_dir, conversation._service, None, default_timeout_s=5.0)
    assert engine.cancel(run_id).status == "cancelled"
