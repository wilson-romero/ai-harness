"""A conversation owns its session (interactive-shell D4, task 3.4), with real processes."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading

import pytest

from tests.conftest import REPO_ROOT, query, run_main, subprocess_env

CHILD = REPO_ROOT / "tests" / "integration" / "chat_child.py"


class Child:
    """A conversation in another process, driven through its stdin and stdout."""

    def __init__(self, data_dir, *args: str) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(CHILD), "chat", *args],
            cwd=REPO_ROOT, env=subprocess_env(data_dir),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
        )
        self.lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self.seen: list[str] = []

    def _pump(self) -> None:
        for line in self.process.stdout:
            self.lines.put(line.rstrip("\n"))
        self.lines.put(None)

    def wait_for_prompt(self, timeout_s: float = 30.0) -> list[str]:
        """Lines printed up to the next prompt; fails if the child ends first."""
        while True:
            line = self.lines.get(timeout=timeout_s)
            if line is None:
                raise AssertionError(f"the child ended: {self.seen}")
            if line == "PROMPT":
                return self.seen
            self.seen.append(line)

    def type(self, line: str) -> None:
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def kill(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=30)


@pytest.fixture
def holder(data_dir):
    session_id = run_main(data_dir, "session", "create", "A").stdout.strip()
    child = Child(data_dir, "--session", session_id)
    try:
        child.wait_for_prompt()
        child.type("primera pregunta")  # the session stays held after a question, not only before
        child.wait_for_prompt()
        yield session_id, child
    finally:
        child.kill()


def _requests(data_dir) -> int:
    return query(data_dir, "SELECT count(*) FROM requests")[0][0]


def test_a_second_conversation_on_the_same_session_is_refused(data_dir, holder):
    """Scenario «Segunda conversación sobre la misma sesión»."""
    session_id, _ = holder
    second = subprocess.run(
        [sys.executable, str(CHILD), "chat", "--session", session_id],
        cwd=REPO_ROOT, env=subprocess_env(data_dir), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=60,
    )
    assert second.returncode == 1
    assert "in use by another process" in second.stderr
    assert "PROMPT" not in second.stdout


def test_a_single_question_on_a_session_in_conversation_is_refused(data_dir, holder):
    """Scenario «Pregunta suelta sobre una sesión en conversación»."""
    session_id, _ = holder
    before = _requests(data_dir)
    asked = run_main(data_dir, "ask", session_id, "x")
    assert asked.returncode == 1
    assert "question in progress" in asked.stderr or "busy" in asked.stderr
    assert _requests(data_dir) == before


def test_a_dead_conversation_frees_its_session(data_dir, holder):
    """Scenario «Conversación muerta»."""
    session_id, child = holder
    child.type("antes de morir")
    child.wait_for_prompt()
    child.kill()
    asked = run_main(data_dir, "ask", session_id, "después")
    assert asked.returncode == 0, asked.stderr
    assert query(data_dir, "SELECT status FROM requests ORDER BY rowid") == [
        ("completed",), ("completed",), ("completed",)]


def test_the_conversation_holds_the_session_between_questions(data_dir, holder):
    """The lock is not per question: after an answer, another process is still refused."""
    session_id, child = holder
    child.type("una pregunta")
    child.wait_for_prompt()
    asked = run_main(data_dir, "ask", session_id, "intercalada")
    assert asked.returncode == 1
    assert _requests(data_dir) == 2
