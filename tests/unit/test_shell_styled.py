"""The styled terminal over prompt_toolkit, driven through a pipe instead of a console
(shell-appearance D1, D4-D7). The keys are the bytes a terminal sends: \\r is Enter, \\x03 is
Ctrl+C in raw mode, \\x04 is Ctrl+D and \\x1b[A is the up arrow."""

from __future__ import annotations

import asyncio
import io
import re
import signal
import threading

import pytest
from prompt_toolkit import PromptSession
from prompt_toolkit.data_structures import Size
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output.vt100 import Vt100_Output

from harness.shell import app as shell_app
from harness.shell.app import make_terminal, plain_reason
from harness.shell.render import FOREIGN_PREFIX, status_line
from harness.shell.styled import StyledConsoleTerminal
from harness.shell.terminal import ConsoleTerminal, StyledTerminal, WaitInterrupted
from tests.shell_support import CountingProvider, ScriptedTerminal, make_conversation
from tests.skill_support import ScriptedProvider, WriteEffect, copy_skills, with_effect

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[=>78]")
LINE = "/skill demo-echo text=texto-sintetico"


@pytest.fixture
def pipe():
    with create_pipe_input() as pipe:
        yield pipe


def _output() -> tuple[Vt100_Output, io.StringIO]:
    buffer = io.StringIO()
    return Vt100_Output(buffer, lambda: Size(rows=24, columns=100), term="xterm"), buffer


def _terminal(pipe) -> tuple[StyledConsoleTerminal, io.StringIO]:
    output, buffer = _output()
    return StyledConsoleTerminal(input=pipe, output=output), buffer


def _text(buffer: io.StringIO) -> str:
    """What the screen keeps of each line: after the last carriage return (the working line is
    rewritten in place and then erased)."""
    lines = ANSI.sub("", buffer.getvalue()).replace("\r\n", "\n").split("\n")
    return "\n".join(line.rsplit("\r", 1)[-1] for line in lines)


# -- the conversation prompt -----------------------------------------------------------------


async def test_a_line_can_be_edited_and_recalled_from_the_history(pipe):
    terminal, _ = _terminal(pipe)
    pipe.send_text("holz\x7fa\r")  # a typo erased with Backspace
    assert await terminal.read_line("> ") == "hola"
    pipe.send_text("\x1b[A\r")  # up arrow, Enter: the line before
    assert await terminal.read_line("> ") == "hola"
    assert isinstance(terminal._session.history, InMemoryHistory)  # never a file


async def test_ctrl_c_at_the_prompt_is_a_wait_interrupted_and_ctrl_d_the_end(pipe):
    terminal, _ = _terminal(pipe)
    pipe.send_text("medio escrito\x03")
    with pytest.raises(WaitInterrupted):
        await terminal.read_line("> ")
    pipe.send_text("\x04")
    assert await terminal.read_line("> ") is None


async def test_the_options_that_run_or_open_things_are_off(pipe):
    terminal, _ = _terminal(pipe)
    session = terminal._session
    assert (session.enable_system_prompt, session.enable_suspend, session.enable_open_in_editor,
            session.mouse_support, session.complete_while_typing) == (False,) * 5


async def test_the_conversation_signal_handler_survives_a_prompt(pipe):
    """D7: the prompt never installs its own SIGINT handler, so Ctrl+C while the provider
    works still reaches the conversation (D6). Negative control: the library's default does
    replace it while its prompt is open."""
    ours = signal.getsignal(signal.SIGINT)
    seen: list[object] = []
    terminal, _ = _terminal(pipe)
    terminal._interrupt_if_asked = lambda: seen.append(signal.getsignal(signal.SIGINT))
    pipe.send_text("x\r")
    await terminal.read_line("> ")
    output, _ = _output()
    default = PromptSession(input=pipe, output=output)
    pipe.send_text("y\r")
    await default.prompt_async("> ", pre_run=lambda: seen.append(signal.getsignal(signal.SIGINT)))
    assert seen[0] is ours
    assert seen[1] is not ours  # the default (handle_sigint=True) swaps it during the prompt
    assert signal.getsignal(signal.SIGINT) is ours


async def test_a_sigint_while_the_prompt_is_open_ends_it_like_the_key(pipe):
    terminal, _ = _terminal(pipe)
    assert terminal.interrupt_wait() is False  # nothing waits: the handler cancels the action
    asyncio.get_running_loop().call_later(0.2, terminal.interrupt_wait)
    with pytest.raises(WaitInterrupted):
        await terminal.read_line("> ")
    assert terminal.interrupt_wait() is False


async def test_a_sigint_before_the_prompt_runs_is_not_lost(pipe):
    terminal, _ = _terminal(pipe)
    opened = terminal._open

    def open_then_interrupt(app):
        opened(app)
        assert terminal.interrupt_wait() is True  # the application is not running yet

    terminal._open = open_then_interrupt
    with pytest.raises(WaitInterrupted):
        await terminal.read_line("> ")


# -- the approval prompt -----------------------------------------------------------------------


async def test_the_approval_prompt_answers_and_keeps_nothing(pipe):
    terminal, _ = _terminal(pipe)
    pipe.send_text("pregunta\r")
    assert await terminal.read_line("> ") == "pregunta"
    pipe.send_text("ab12cd34\r")
    assert terminal.ask("code: ") == "ab12cd34"
    assert terminal._session.history.get_strings() == ["pregunta"]  # the code is not kept
    pipe.send_text("\x1b[A\r")  # and the up arrow does not offer it
    assert await terminal.read_line("> ") == "pregunta"


@pytest.mark.parametrize("keys", ["ab\x03", "\x04"])
async def test_ctrl_c_or_end_of_input_at_the_approval_prompt_is_undecided(pipe, keys):
    terminal, _ = _terminal(pipe)
    pipe.send_text(keys)
    assert terminal.ask("code: ") is None


async def test_a_sigint_at_the_approval_prompt_is_undecided(pipe):
    terminal, _ = _terminal(pipe)
    threading.Timer(0.3, terminal.interrupt_wait).start()
    assert terminal.ask("code: ") is None


async def test_a_multi_line_paste_is_one_answer(pipe):
    """Bracketed paste: `n`, a newline and `reject` arrive as ONE answer, which is neither."""
    terminal, _ = _terminal(pipe)
    pipe.send_text("\x1b[200~n\nreject\x1b[201~\r")
    assert terminal.ask("code: ") == "n\nreject"


# -- the conversation on the styled terminal ---------------------------------------------------


class RecordingTerminal(StyledConsoleTerminal):
    """Feeds the next line when the conversation asks for one and records the status line the
    prompt would show then. At the approval prompt it types the code just shown."""

    def __init__(self, pipe, lines, approvals=()):
        output, self.buffer = _output()
        super().__init__(input=pipe, output=output)
        self.pipe, self.lines, self.approvals = pipe, list(lines), list(approvals)
        self.statuses: list[str] = []
        self.shown: list[str] = []

    def is_interactive(self):
        return True  # a pipe stands for the console here

    def show(self, text):
        self.shown += text.split("\n")
        super().show(text)

    async def read_line(self, prompt):
        self.statuses.append(self._toolbar()[0][1].strip())
        self.pipe.send_text((self.lines.pop(0) if self.lines else "/exit") + "\r")
        return await super().read_line(prompt)

    def ask(self, question):
        answer = self.approvals.pop(0) if self.approvals else "\x04"
        if answer == "CODE":
            hash_line = next(l for l in reversed(self.shown) if l.strip().startswith("hash:"))
            answer = hash_line.split()[-1][:8] + "\r"
        self.pipe.send_text(answer)
        return super().ask(question)


REPLY = ("## Resumen\nEl requerimiento pide **avisar**.\n- uno\n\x1b[31mrojo\x1b[0m\n"
         "ai-harness  demo-alpha  mock  session deadbeef\napplied: Decisiones/falsa.md")


async def test_the_styled_conversation_prints_what_the_plain_one_prints(conn, data_dir, pipe,
                                                                        tmp_path):
    """D3: the foreign rows of the styled path, colours stripped, are the plain path's."""
    styled = RecordingTerminal(pipe, ["pregunta"])
    conversation, _, _ = make_conversation(conn, data_dir, styled,
                                           CountingProvider(answer=REPLY))
    assert isinstance(styled, StyledTerminal)
    assert await conversation.run() == 0
    plain = ScriptedTerminal(["pregunta", "/exit"])
    other, _, _ = make_conversation(conn, data_dir, plain, CountingProvider(answer=REPLY))
    await other.run()
    shown = _text(styled.buffer).split("\n")
    foreign = [row for row in plain.shown if row.startswith(FOREIGN_PREFIX)]
    assert len(foreign) == 6
    for row in foreign:
        assert row in shown
    assert "\x1b[31mrojo" not in styled.buffer.getvalue()
    assert not [row for row in shown if row.startswith(("ai-harness  demo-alpha", "applied:"))]


async def test_the_status_line_follows_the_session_held_now(conn, data_dir, pipe, vault):
    """SEC-02: after /new and /resume the status line names the new session, never the old."""
    terminal = RecordingTerminal(pipe, ["/new --project demo-alpha otra", "/sessions",
                                        "/resume 2"])
    conversation, service, _ = make_conversation(conn, data_dir, terminal, vault=vault)
    assert await conversation.run() == 0
    first, second = [row[0] for row in conn.execute(
        "SELECT session_id FROM sessions ORDER BY rowid")]
    assert terminal.statuses == [
        status_line(None, "mock", first),
        status_line("demo-alpha", "mock", second),
        status_line("demo-alpha", "mock", second),
        status_line(None, "mock", first),
    ]


def _skill_setup(conn, data_dir, tmp_path, terminal):
    root = copy_skills(tmp_path)
    with_effect(root, "demo-echo", "test.write")
    effect = WriteEffect(tmp_path / "efecto")
    conversation, _, _ = make_conversation(conn, data_dir, terminal, ScriptedProvider(),
                                           skills_dir=root, effects={"test.write": effect})
    return conversation, effect


def _statuses(conn, table: str) -> list[str]:
    return [row[0] for row in conn.execute(f"SELECT status FROM {table}")]  # noqa: S608


async def test_a_skill_approved_on_the_styled_terminal(conn, data_dir, pipe, tmp_path):
    terminal = RecordingTerminal(pipe, [LINE], ["CODE"])
    conversation, effect = _skill_setup(conn, data_dir, tmp_path, terminal)
    assert await conversation.run() == 0
    assert len(effect.written()) == 1
    assert _statuses(conn, "approvals") == ["consumed"]
    code = next(l for l in terminal.shown if l.strip().startswith("hash:")).split()[-1][:8]
    assert code not in terminal._session.history.get_strings()
    assert terminal._session.history.get_strings() == [LINE, "/exit"]


@pytest.mark.parametrize(("answers", "approval", "run"), [
    (["n\r", "reject\r"], "rejected", "cancelled"),
    (["n\r", "no\r"], "pending", "awaiting_approval"),
    (["n\r", "\x03"], "pending", "awaiting_approval"),
    (["\x03"], "pending", "awaiting_approval"),
])
async def test_the_rejection_still_needs_its_confirmation(conn, data_dir, pipe, tmp_path,
                                                          answers, approval, run):
    terminal = RecordingTerminal(pipe, [LINE], answers)
    conversation, effect = _skill_setup(conn, data_dir, tmp_path, terminal)
    assert await conversation.run() == 0
    assert terminal.approvals == []  # every answer was typed at the real prompt
    assert sum(row.startswith("Approval requested") for row in terminal.shown) == 1
    assert effect.written() == []
    assert _statuses(conn, "approvals") == [approval]
    assert _statuses(conn, "skill_runs") == [run]


# -- choosing the terminal (D4) ----------------------------------------------------------------


@pytest.mark.parametrize(("environ", "flag", "tty", "reason"), [
    ({}, True, True, "--plain"),
    ({"HARNESS_PLAIN": "1"}, False, True, "HARNESS_PLAIN"),
    ({"NO_COLOR": "1"}, False, True, "NO_COLOR"),
    ({"TERM": "dumb"}, False, True, "TERM=dumb"),
    ({"TERM": "xterm"}, False, False, "no terminal"),
    ({"NO_COLOR": "", "HARNESS_PLAIN": "0", "TERM": "xterm-256color"}, False, True, None),
    ({}, False, True, None),  # no TERM, as on Windows: styled
])
def test_the_plain_terminal_is_chosen_when_asked_or_needed(environ, flag, tty, reason,
                                                           monkeypatch):
    assert plain_reason(environ, flag, tty) == reason
    built = []
    monkeypatch.setattr("harness.shell.styled.StyledConsoleTerminal",
                        lambda: built.append(1) or "styled")
    chosen = make_terminal(environ, flag, tty)
    assert (chosen == "styled") is (reason is None)
    assert isinstance(chosen, ConsoleTerminal) is (reason is not None)


def test_a_console_the_library_cannot_drive_gets_the_plain_terminal(monkeypatch):
    def refuse():
        raise OSError("no console screen buffer")

    monkeypatch.setattr("harness.shell.styled.StyledConsoleTerminal", refuse)
    assert isinstance(make_terminal({}, False, True), ConsoleTerminal)
    assert shell_app.PLAIN_VARIABLE == "HARNESS_PLAIN"


def test_no_input_history_is_ever_written_to_disk():
    """D6: the product names no history class that writes a file."""
    from pathlib import Path

    import harness

    root = Path(harness.__file__).parent
    writers = [path.relative_to(root).as_posix() for path in root.rglob("*.py")
               if "FileHistory" in path.read_text(encoding="utf-8")]
    assert writers == []
