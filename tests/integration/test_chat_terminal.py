"""`main.py chat` at a real (pseudo-)terminal, with Ctrl+C typed into it (task 4.2).

Ctrl+C is delivered as in the probe of task 1.2: the byte 0x03 is written to the terminal and
the terminal's line discipline sends SIGINT to the conversation, exactly as for a person at a
keyboard. A pseudo-terminal only exists where the `pty` module can be imported; elsewhere these
tests are skipped with that reason (the same code runs there: see the manual demo, task 7.6).
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from tests.conftest import REPO_ROOT, query, run_main, subprocess_env, wait_for_running

pty = pytest.importorskip("pty", reason="no pseudo-terminal module on this system")
select = pytest.importorskip("select")

DEADLINE_S = 60.0  # generous: the events are ordered by what the child prints, not by time


class TerminalChild:
    def __init__(self, data_dir, *args: str, **env: str) -> None:
        environment = subprocess_env(data_dir, **env)
        pid, fd = pty.fork()
        if pid == 0:  # the child: becomes `main.py` with the pseudo-terminal as its console
            os.chdir(REPO_ROOT)
            os.execve(sys.executable, [sys.executable, "main.py", *args], environment)
        self.pid, self.fd = pid, fd
        self.output = ""

    def read_until(self, text: str) -> str:
        deadline = time.monotonic() + DEADLINE_S
        while text not in self.output:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"{text!r} never appeared; output so far:\n{self.output}")
            ready, _, _ = select.select([self.fd], [], [], remaining)
            if not ready:
                continue
            try:
                chunk = os.read(self.fd, 4096)
            except OSError:
                chunk = b""
            if not chunk:
                raise AssertionError(f"the child ended before {text!r}:\n{self.output}")
            self.output += chunk.decode("utf-8", errors="replace").replace("\r\n", "\n")
        found = self.output
        self.output = ""
        return found

    def type(self, data: str) -> None:
        os.write(self.fd, data.encode("utf-8"))

    def wait(self) -> int:
        deadline = time.monotonic() + DEADLINE_S
        while time.monotonic() < deadline:
            try:  # drain, so the child is never blocked writing
                ready, _, _ = select.select([self.fd], [], [], 0.1)
                if ready:
                    os.read(self.fd, 4096)
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


def test_ctrl_c_at_a_terminal_interrupts_the_question_not_the_conversation(data_dir):
    session_id = run_main(data_dir, "session", "create", "S").stdout.strip()
    child = TerminalChild(data_dir, "chat", "--session", session_id,
                          HARNESS_MOCK_DELAY_MS="60000")
    try:
        header = child.read_until("\n> ")
        assert "provider: mock" in header and session_id in header

        child.type("\x03")  # Ctrl+C while the conversation waits for a line
        assert "the conversation is still open" in child.read_until("\n> ")

        child.type("pregunta lenta\r")
        wait_for_running(data_dir, session_id)
        child.type("\x03")  # Ctrl+C while the question is in progress
        shown = child.read_until("\n> ")
        assert "is uncertain" in shown and "not resent" in shown

        child.type("/exit\r")
        assert child.wait() == 0
    finally:
        child.kill()
    assert query(data_dir, "SELECT status FROM requests") == [("uncertain",)]
    assert query(data_dir, "SELECT count(*) FROM requests")[0][0] == 1  # nothing was resent


def test_the_program_alone_at_a_terminal_opens_the_conversation(data_dir):
    child = TerminalChild(data_dir)
    try:
        assert "ai-harness conversation" in child.read_until("\n> ")
        child.type("\x04")  # end of input (Ctrl+D) at an empty line
        assert child.wait() == 0
    finally:
        child.kill()
    assert query(data_dir, "SELECT count(*) FROM sessions")[0][0] == 1
