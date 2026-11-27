"""`main.py chat` full screen at a real (pseudo-)terminal (shell-tui, task 5.1).

The child runs the real program with the Mock. Ctrl+C is the byte 0x03 written to the
terminal: Textual's raw mode makes it a key, never a signal. The output is full-screen drawing,
so the test looks for pieces of text with the escape sequences removed, and for the sequences
that enter and leave the alternate screen and show the cursor. Skipped where `pty` cannot be
imported, with that reason.
"""

from __future__ import annotations

import json
import os
import re
import signal
import struct
import sys
import time

import pytest

from harness.core.answer_style import CONCISE_NOTICE
from tests.conftest import REPO_ROOT, query, run_main, subprocess_env, wait_for_running
from tests.skill_support import GOOD_ECHO

pty = pytest.importorskip("pty", reason="no pseudo-terminal module on this system")
select = pytest.importorskip("select")
termios = pytest.importorskip("termios")
fcntl = pytest.importorskip("fcntl")

DEADLINE_S = 60.0
ESCAPES = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b[=>78PMc]|[\x07\x08\x0f]")
ALT_SCREEN_ON, ALT_SCREEN_OFF, CURSOR_SHOWN = "\x1b[?1049h", "\x1b[?1049l", "\x1b[?25h"
READY = "Type a question"


class FullScreenChild:
    def __init__(self, data_dir, *args: str, **env: str) -> None:
        environment = subprocess_env(data_dir, **{"TERM": "xterm-256color", **env})
        for name in ("NO_COLOR", "HARNESS_PLAIN"):
            if name not in env:
                environment.pop(name, None)
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(REPO_ROOT)
            os.execve(sys.executable, [sys.executable, "main.py", *args], environment)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 110, 0, 0))
        self.pid, self.fd = pid, fd
        self.raw = ""
        self.mark = 0

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
        self.raw += chunk.decode("utf-8", errors="replace")
        return True

    def text(self, start: int = 0) -> str:
        return ESCAPES.sub("", self.raw[start:])

    def read_until(self, text: str) -> None:
        """Until `text` is drawn after what the last call found."""
        deadline = time.monotonic() + DEADLINE_S
        while text not in self.text(self.mark):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._read(min(remaining, 0.5)) and \
                    text not in self.text(self.mark):
                raise AssertionError(f"{text!r} never appeared:\n{self.text()[-3000:]}")
        self.mark = len(self.raw)

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
                while self._read(0.05):
                    if not select.select([self.fd], [], [], 0)[0]:
                        break
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


def _restored(child: FullScreenChild) -> bool:
    """The last alternate-screen sequence leaves it, and the cursor is shown after it."""
    off = child.raw.rfind(ALT_SCREEN_OFF)
    return off > child.raw.rfind(ALT_SCREEN_ON) and CURSOR_SHOWN in child.raw[off - 200:]


@pytest.mark.parametrize("notice", [None, "on"], ids=["default", "notice-on"])
def test_a_question_on_the_full_screen_and_ctrl_q(data_dir, notice):
    # The Mock reports how much it received: the question alone by default; with
    # `HARNESS_CONCISE_ANSWERS=on`, the notice (prompt-economy D3), a blank line and the question.
    env = {} if notice is None else {"HARNESS_CONCISE_ANSWERS": notice}
    received = len("hola") + (0 if notice is None else len(CONCISE_NOTICE) + 2)
    child = FullScreenChild(data_dir, "chat", **env)
    try:
        child.read_until(READY)
        assert ALT_SCREEN_ON in child.raw
        child.type("hola\r")
        child.read_until(f"Received {received} characters")
        child.type("\x11")  # ctrl+q
        assert child.wait() == 0
    finally:
        child.kill()
    assert _restored(child)
    assert query(data_dir, "SELECT status FROM requests") == [("completed",)]


def test_ctrl_c_interrupts_the_question_not_the_screen(data_dir):
    session_id = run_main(data_dir, "session", "create", "S").stdout.strip()
    child = FullScreenChild(data_dir, "chat", "--session", session_id,
                            HARNESS_MOCK_DELAY_MS="60000")
    try:
        child.read_until(READY)
        child.type("\x03")  # nothing running: the screen stays
        child.read_until("still open")
        child.read_until(READY)
        child.type("pregunta lenta\r")
        wait_for_running(data_dir, session_id)
        child.type("\x03")
        child.read_until("is uncertain")
        child.type("/exit\r")
        assert child.wait() == 0
    finally:
        child.kill()
    assert _restored(child)
    assert query(data_dir, "SELECT status FROM requests") == [("uncertain",)]


def test_sigterm_closes_and_restores_the_terminal(data_dir):
    child = FullScreenChild(data_dir, "chat")
    try:
        child.read_until(READY)
        os.kill(child.pid, signal.SIGTERM)
        assert child.wait() == 0
    finally:
        child.kill()
    assert _restored(child)
    assert query(data_dir, "SELECT COUNT(*) FROM sessions") == [(1,)]


@pytest.mark.parametrize(("args", "env"), [
    (("chat", "--plain"), {}),
    (("chat",), {"NO_COLOR": "1"}),
    (("chat",), {"TERM": "dumb"}),
    (("chat",), {"HARNESS_PLAIN": "1"}),
    (("chat",), {"TEXTUAL_LOG": "conversacion.log"}),
])
def test_plain_text_when_asked(data_dir, args, env):
    child = FullScreenChild(data_dir, *args, **env)
    try:
        child.read_until("\n> ")
        assert "ai-harness conversation" in child.text()
        assert "\x1b[" not in child.raw  # no colour, no cursor movement: plain text
        child.type("\x04")
        assert child.wait() == 0
    finally:
        child.kill()
    assert not (REPO_ROOT / "conversacion.log").exists()


def test_lines_written_at_once_send_one_question(data_dir):
    """Review 2026-11-26: one write with two lines. The screen handles both Enters before the
    core's thread runs again; only one of them may become a question."""
    child = FullScreenChild(data_dir, "chat", HARNESS_MOCK_DELAY_MS="1500")
    try:
        child.read_until(READY)
        child.type("uno\rdos\r")
        child.read_until("Received ")  # Textual inserts the keys before it handles Enter
        child.read_until(READY)
        time.sleep(1.0)  # a second question would be running by now
        child.type("\x11")
        assert child.wait() == 0
    finally:
        child.kill()
    assert query(data_dir, "SELECT status FROM requests") == [("completed",)]


def test_a_hangup_during_a_question_exits_cleanly(data_dir):
    """Review 2026-11-26: the terminal goes away (SIGHUP, master closed) while a question runs:
    the request ends uncertain, the session is released and the exit code is 0, not the 120
    of a failed flush of the standard streams."""
    session_id = run_main(data_dir, "session", "create", "S").stdout.strip()
    child = FullScreenChild(data_dir, "chat", "--session", session_id,
                            HARNESS_MOCK_DELAY_MS="60000")
    try:
        child.read_until(READY)
        child.type("pregunta lenta\r")
        wait_for_running(data_dir, session_id)
        os.close(child.fd)
        os.kill(child.pid, signal.SIGHUP)
        deadline = time.monotonic() + DEADLINE_S
        while time.monotonic() < deadline:
            pid, status = os.waitpid(child.pid, os.WNOHANG)
            if pid:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("the conversation did not end")
    finally:
        child.kill()
    assert os.waitstatus_to_exitcode(status) == 0
    assert query(data_dir, "SELECT status FROM requests") == [("uncertain",)]
    assert run_main(data_dir, "ask", session_id, "otra").returncode == 0  # the session is free


def test_the_approval_buttons_at_a_real_terminal(data_dir, tmp_path):
    """approval-buttons: the skill line and, in the same write, the keys that would approve
    if a button had the focus (Tab, Enter, Space). The box opens and stays pending; Tab and
    Enter sent once it is armed approve, and the audit says so."""
    responses = tmp_path / "respuestas.json"
    responses.write_text(json.dumps({"tarea: demo-echo/draft": GOOD_ECHO}), encoding="utf-8")
    child = FullScreenChild(data_dir, "chat", HARNESS_MOCK_RESPONSES=str(responses),
                            HARNESS_SKILLS_DIR=str(REPO_ROOT / "tests" / "fixtures" / "skills"),
                            HARNESS_MOCK_DELAY_MS="0")
    try:
        child.read_until(READY)
        child.type("/skill demo-echo text=texto-sintetico\r\t\r \r\t\r")
        child.read_until("The whole proposal has been shown")
        time.sleep(1.0)  # armed by now
        assert query(data_dir, "SELECT status FROM approvals") == [("pending",)]
        child.type("\t")
        time.sleep(0.3)
        child.type("\r")
        child.read_until("is completed")
        child.type("\x11")
        assert child.wait() == 0
    finally:
        child.kill()
    assert _restored(child)
    assert query(data_dir, "SELECT status FROM approvals") == [("consumed",)]
    detail = query(data_dir, "SELECT detail FROM audit_events WHERE event_type = 'approval.granted'")
    assert detail[0][0].endswith(";means=button")
