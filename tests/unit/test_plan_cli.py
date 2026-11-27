"""`main.py plan SESSION_ID QUESTION` (code-mode slice 2): the typed code is its only
approval, and without an interactive terminal it refuses before anything is sent."""

from __future__ import annotations

import json

import pytest

import harness.mcp.plan_cli as plan_cli
from tests.mcp_support import hang_guard  # noqa: F401 - fixture
from tests.plan_support import ALPHA, QUESTION, McpList, plan_reply, rows
from tests.shell_support import CODE, ScriptedTerminal


@pytest.fixture
def setup(tmp_path, cli, hang_guard):  # noqa: F811
    mcp = McpList(tmp_path / "mcp")
    responses = tmp_path / "respuestas.json"
    responses.write_text(json.dumps({"etiqueta alpha": plan_reply(ALPHA)}), "utf-8")
    env = {"HARNESS_PROVIDER": "mock", "HARNESS_MOCK_RESPONSES": str(responses),
           "HARNESS_MCP_CONFIG": str(mcp.path)}
    code, out, _ = cli("session", "create", "Plan sintético", **env)
    assert code == 0
    return mcp, env, out.strip()


def test_without_an_interactive_terminal_nothing_is_sent(setup, cli, conn):
    mcp, env, session = setup
    code, out, err = cli("plan", session, QUESTION, **env)
    assert code == 2
    assert "plan needs an interactive terminal" in err and "nothing was sent" in err
    assert rows(conn, "SELECT COUNT(*) FROM requests") == [(0,)]
    assert mcp.starts() == 0


def test_the_typed_code_approves_and_the_results_go_to_stdout(setup, cli, conn, monkeypatch):
    mcp, env, session = setup
    terminal = ScriptedTerminal([], [CODE])
    monkeypatch.setattr(plan_cli, "TtyTerminal", lambda: terminal)
    code, out, err = cli("plan", session, QUESTION, **env)
    assert code == 0, err
    assert "Plan approval requested" in terminal.text  # where the code is typed
    assert '| step 1 of 1 (a): synthetic.get_project_metadata  read  allowed' in terminal.text
    assert "Demo Alpha" in out  # the result: foreign text, on stdout
    assert "completed: 1 of 1 step(s)" in err
    assert mcp.calls() == ["call get_project_metadata"]
    assert rows(conn, "SELECT status, means FROM plan_runs") == [("completed", "code")]
    assert rows(conn, "SELECT COUNT(*) FROM requests") == [(1,)]


def test_a_wrong_code_runs_nothing_and_fails(setup, cli, conn, monkeypatch):
    mcp, env, session = setup
    terminal = ScriptedTerminal([], ["00000000", "11111111", "22222222"])
    monkeypatch.setattr(plan_cli, "TtyTerminal", lambda: terminal)
    code, _, err = cli("plan", session, QUESTION, **env)
    assert code == 1
    assert "was not approved; nothing was run" in err
    assert mcp.starts() == 0
    assert rows(conn, "SELECT approval FROM plan_runs") == [("undecided",)]


def test_a_session_in_use_is_refused_before_sending(setup, cli, conn, monkeypatch, data_dir):
    from harness.storage.locks import SessionLock

    mcp, env, session = setup
    monkeypatch.setattr(plan_cli, "TtyTerminal", lambda: ScriptedTerminal([], [CODE]))
    from uuid import UUID

    lock = SessionLock(data_dir, UUID(session))
    assert lock.acquire()
    try:
        code, _, err = cli("plan", session, QUESTION, **env)
    finally:
        lock.release()
    assert code == 1 and "in use" in err
    assert rows(conn, "SELECT COUNT(*) FROM requests") == [(0,)]
