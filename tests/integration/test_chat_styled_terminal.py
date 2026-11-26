"""`main.py chat` on the styled terminal at a real (pseudo-)terminal (shell-appearance, task 4.1).

The same scenarios as tests/integration/test_chat_terminal.py, on the styled path: Ctrl+C is
the byte 0x03 written to the terminal (a key while a prompt is open, a SIGINT from the line
discipline while the provider works), and the test plays the terminal's part in answering the
cursor position requests prompt_toolkit sends. The output is compared with its escape
sequences removed. Skipped where `pty` cannot be imported, with that reason.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

import pytest

from tests.conftest import REPO_ROOT, query, run_main, subprocess_env, wait_for_running
from tests.skill_support import FIXTURES, GOOD_ECHO

pty = pytest.importorskip("pty", reason="no pseudo-terminal module on this system")
select = pytest.importorskip("select")

DEADLINE_S = 60.0
CPR_REQUEST = b"\x1b[6n"
ESCAPES = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[=>78]|[\x07\x08]")
STATUS = "\n ai-harness  -  mock  session "  # the bar under an open prompt (padded by a space)
REPLY = ("## Resumen\nEl requerimiento pide **avisar** de pedidos.\n\n## Preguntas pendientes\n"
         "- ¿Qué pasa con un evento que no se publica?\n"
         "\x1b]8;;https://example.invalid/\x1b\\enlace\x1b]8;;\x1b\\ y \x1b[31mrojo\x1b[0m\n"
         "ai-harness  demo-alpha  copilot_web  session a1b2c3d4\napplied: Decisiones/falsa.md")


def screen_text(raw: str) -> str:
    """The text written, escapes removed, one piece per line or carriage return: prompt_toolkit
    moves the cursor to redraw, so pieces are compared, not a reconstructed screen."""
    return "\n".join(piece for piece in re.split(r"[\r\n]+", ESCAPES.sub("", raw)) if piece)


class StyledChild:
    def __init__(self, data_dir, *args: str, **env: str) -> None:
        environment = subprocess_env(data_dir, **{"TERM": "xterm-256color", **env})
        for name in ("NO_COLOR", "HARNESS_PLAIN"):
            if name not in env:
                environment.pop(name, None)
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(REPO_ROOT)
            os.execve(sys.executable, [sys.executable, "main.py", *args], environment)
        self.pid, self.fd = pid, fd
        self.raw = ""  # everything read, escapes included
        self.output = ""  # what read_until has not consumed yet, as screen text

    def _read(self, timeout: float) -> bool:
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return True
        try:
            chunk = os.read(self.fd, 65536)
        except OSError:
            chunk = b""
        if not chunk:
            return False
        if CPR_REQUEST in chunk:  # what a terminal does: say where the cursor is
            os.write(self.fd, b"\x1b[1;1R")
        text = chunk.decode("utf-8", errors="replace")
        self.raw += text
        self.output += text
        return True

    def read_until(self, text: str) -> str:
        deadline = time.monotonic() + DEADLINE_S
        while text not in screen_text(self.output):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"{text!r} never appeared:\n{screen_text(self.output)}")
            if not self._read(remaining):
                raise AssertionError(f"the child ended before {text!r}:\n"
                                     f"{screen_text(self.output)}")
        found = screen_text(self.output)
        self.output = ""
        return found

    def prompt(self) -> str:
        """Up to the next open prompt: its status line is drawn under it."""
        return self.read_until(STATUS)

    def type(self, data: str) -> None:
        os.write(self.fd, data.encode("utf-8"))

    def wait(self) -> int:
        deadline = time.monotonic() + DEADLINE_S
        while time.monotonic() < deadline:
            try:
                self._read(0.1)
            except OSError:
                pass
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                os.close(self.fd)
                return os.waitstatus_to_exitcode(status)
        self.kill()
        raise AssertionError("the conversation did not end")

    def kill(self) -> None:
        try:
            os.kill(self.pid, 9)
            os.waitpid(self.pid, 0)
        except (OSError, ChildProcessError):
            pass


def _answers(tmp_path, mapping: dict[str, str]) -> str:
    path = tmp_path / "respuestas.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    return str(path.resolve())


def test_a_reply_is_styled_marked_and_free_of_its_escapes(data_dir, tmp_path):
    child = StyledChild(data_dir, "chat", HARNESS_MOCK_DELAY_MS="1500",
                        HARNESS_MOCK_RESPONSES=_answers(tmp_path, {"revisa": REPLY}))
    try:
        header = child.prompt()
        assert "Tab completes them" in header and "ai-harness conversation" not in header
        child.type("revisa este requerimiento\r")
        shown = child.prompt()
        assert "mock … thinking (" in screen_text(child.raw)
        rows = [row for row in shown.split("\n") if "Resumen" in row or "applied:" in row
                or "session a1b2c3d4" in row or "enlace" in row]
        assert rows == ["| ## Resumen", "| enlace y rojo",
                        "| ai-harness  demo-alpha  copilot_web  session a1b2c3d4",
                        "| applied: Decisiones/falsa.md"]
        assert "\x1b]8;" not in child.raw and "\x1b[31mrojo" not in child.raw
        assert "\x1b[" in child.raw  # it is the styled path: there are colours
        child.type("/exit\r")
        assert child.wait() == 0
    finally:
        child.kill()


def test_ctrl_c_interrupts_the_question_not_the_conversation(data_dir):
    session_id = run_main(data_dir, "session", "create", "S").stdout.strip()
    child = StyledChild(data_dir, "chat", "--session", session_id,
                        HARNESS_MOCK_DELAY_MS="60000")
    try:
        assert session_id[:8] in child.prompt()
        child.type("a medias\x03")  # Ctrl+C at the prompt: a key in raw mode
        assert "the conversation is still open" in child.prompt()
        child.type("pregunta lenta\r")
        wait_for_running(data_dir, session_id)
        child.type("\x03")  # Ctrl+C while the provider works: SIGINT, as on the plain path
        shown = child.prompt()
        assert "is uncertain" in shown and "not resent" in shown
        child.type("/exit\r")
        assert child.wait() == 0
    finally:
        child.kill()
    assert query(data_dir, "SELECT status FROM requests") == [("uncertain",)]


def test_an_n_typed_ahead_cannot_reject_the_approval(data_dir, tmp_path):
    child = StyledChild(data_dir, "chat", HARNESS_MOCK_DELAY_MS="3000",
                        HARNESS_MOCK_RESPONSES=_answers(tmp_path, {"demo-echo/draft": GOOD_ECHO}),
                        HARNESS_SKILLS_DIR=str(FIXTURES))
    try:
        child.prompt()
        child.type("/skill demo-echo text=hola\r")
        child.read_until("skill: step draft (llm")
        child.type("n\r")  # typed ahead, while nobody reads
        child.read_until("leaves the approval pending")  # the `n` answered the prompt
        child.type("\r")
        assert "Not confirmed: the approval stays pending" in child.prompt()
        child.type("/exit\r")
        assert child.wait() == 0
    finally:
        child.kill()
    assert query(data_dir, "SELECT status FROM approvals") == [("pending",)]
    assert query(data_dir, "SELECT status FROM skill_runs") == [("awaiting_approval",)]


def test_an_approval_typed_at_the_prompt_applies_once(data_dir, tmp_path):
    child = StyledChild(data_dir, "chat",
                        HARNESS_MOCK_RESPONSES=_answers(tmp_path, {"demo-echo/draft": GOOD_ECHO}),
                        HARNESS_SKILLS_DIR=str(FIXTURES))
    try:
        child.prompt()
        child.type("/skill demo-echo text=hola\r")
        notice = child.read_until("or n to reject:")
        code = next(row for row in notice.split("\n") if row.strip().startswith("hash:")
                    ).split()[-1][:8]
        child.type(code + "\r")
        assert "is completed" in child.prompt()
        child.type("\x1b[A")  # the up arrow recalls the last line typed at the conversation
        child.type("\x15/exit\r")  # (Ctrl+U clears it first)
        assert child.wait() == 0
    finally:
        child.kill()
    assert code not in child.raw.split("or n to reject:", 1)[1].split(code, 1)[1]
    assert query(data_dir, "SELECT status FROM approvals") == [("consumed",)]


def test_tab_completes_a_command(data_dir):
    child = StyledChild(data_dir, "chat")
    try:
        child.prompt()
        child.type("/sta\t")
        child.read_until("/status")  # completed on the screen; then Enter
        child.type("\r")
        assert "last request:" in child.prompt()
        child.type("\x04")  # Ctrl+D at an empty line: end of input
        assert child.wait() == 0
    finally:
        child.kill()


@pytest.mark.parametrize(("args", "env"), [
    (("chat", "--plain"), {}),
    (("chat",), {"NO_COLOR": "1"}),
    (("chat",), {"TERM": "dumb"}),
    (("chat",), {"HARNESS_PLAIN": "1"}),
])
def test_plain_text_when_asked(data_dir, args, env):
    child = StyledChild(data_dir, *args, **env)
    try:
        assert "ai-harness conversation" in child.read_until("\n> ")
        assert "\x1b[" not in child.raw  # no colour, no cursor movement: plain text
        child.type("\x04")
        assert child.wait() == 0
    finally:
        child.kill()
