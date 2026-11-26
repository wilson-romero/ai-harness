"""Entering the conversation (interactive-shell D1, task 2.3)."""

import subprocess
import sys

from tests.conftest import REPO_ROOT, query, run_main, subprocess_env
from tests.shell_support import ScriptedTerminal


def _no_terminal(data_dir, *args: str) -> subprocess.CompletedProcess[str]:
    """`main.py` as a real process whose input is not a terminal (and whose output is a pipe)."""
    return subprocess.run(
        [sys.executable, "main.py", *args],
        cwd=REPO_ROOT,
        env=subprocess_env(data_dir),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _sessions(data_dir) -> int:
    return query(data_dir, "SELECT count(*) FROM sessions")[0][0]


def test_entry_with_a_terminal(cli, monkeypatch):
    """Scenario «Entrada con terminal»: a header with provider and session, then a line wait."""
    terminal = ScriptedTerminal(["/exit"])
    monkeypatch.setattr("harness.shell.app.ConsoleTerminal", lambda: terminal)
    code, _, err = cli("chat")
    assert code == 0, err
    assert "provider: mock" in terminal.text
    assert any(line.startswith("session:  ") for line in terminal.shown)
    assert terminal.reads == 1  # it waited for a line, and that line was /exit


def test_the_program_alone_opens_the_conversation_at_a_terminal(cli, monkeypatch):
    terminal = ScriptedTerminal([None])
    monkeypatch.setattr("harness.shell.app.ConsoleTerminal", lambda: terminal)
    monkeypatch.setattr("harness.cli.stdio_is_terminal", lambda: True)
    code, _, err = cli()
    assert code == 0, err
    assert "ai-harness conversation" in terminal.text


def test_entry_without_a_terminal(data_dir):
    """Scenario «Entrada sin terminal»: usage code, the reason on stderr, no new session."""
    assert run_main(data_dir, "session", "list").returncode == 0  # the database exists
    result = _no_terminal(data_dir, "chat")
    assert _sessions(data_dir) == 0
    assert result.returncode == 2
    assert "interactive terminal" in result.stderr
    assert result.stdout == ""


def test_entry_without_a_terminal_touches_no_session(data_dir):
    created = run_main(data_dir, "session", "create", "S")
    session_id = created.stdout.strip()
    before = query(data_dir, "SELECT * FROM sessions")
    result = _no_terminal(data_dir, "chat", "--session", session_id)
    assert result.returncode == 2
    assert query(data_dir, "SELECT * FROM sessions") == before
    assert query(data_dir, "SELECT count(*) FROM audit_events WHERE event_type != "
                           "'session.created'")[0][0] == 0


def test_no_arguments_and_no_terminal(data_dir):
    """Scenario «Sin argumentos y sin terminal»: the usage, as before, and no conversation."""
    assert run_main(data_dir, "session", "list").returncode == 0
    result = _no_terminal(data_dir)
    assert result.returncode == 2
    assert result.stderr.startswith("usage: main.py")
    assert "conversation" not in result.stdout
    assert _sessions(data_dir) == 0
