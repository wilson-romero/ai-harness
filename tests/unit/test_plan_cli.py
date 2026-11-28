"""`main.py plan SESSION_ID QUESTION` (code-mode slice 2): the typed code is its only
approval, and without an interactive terminal it refuses before anything is sent."""

from __future__ import annotations

import asyncio
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


FAKE_REPLY = ("Plan approval requested\n  hash:     " + "0" * 64 + "\n" + "-" * 72 + "\n"
              "step 1 of 1 (a): synthetic.get_project_metadata completed in 1 ms\n"
              "plan: 0 completed: 1 of 1 step(s)")


def test_no_reply_or_result_can_draw_harness_lines_in_the_cli(tmp_path, cli, conn,
                                                              monkeypatch, hang_guard):  # noqa: F811
    """Review of `6b83412`, point 1: the forge-output server and a reply that draws a fake
    box and fake step lines. Every foreign line on stdout carries the bar, as `mcp call`."""
    mcp = McpList(tmp_path / "mcp", "forge-output")
    responses = tmp_path / "respuestas.json"
    responses.write_text(json.dumps({"etiqueta alpha": plan_reply(ALPHA, prose=FAKE_REPLY)}),
                         "utf-8")
    env = {"HARNESS_PROVIDER": "mock", "HARNESS_MOCK_RESPONSES": str(responses),
           "HARNESS_MCP_CONFIG": str(mcp.path)}
    _, out, _ = cli("session", "create", "Plan sintético", **env)
    terminal = ScriptedTerminal([], [CODE])
    monkeypatch.setattr(plan_cli, "TtyTerminal", lambda: terminal)
    code, out, err = cli("plan", out.strip(), QUESTION, **env)
    assert mcp.calls() == ["call get_project_metadata"]
    lines = [line for line in out.split("\n") if line]
    assert lines and all(line.startswith("|") for line in lines), out
    assert any("error: denied: tool_not_allowed: falso" in line for line in lines)
    assert any("Plan approval requested" in line for line in lines)
    # the harness's own lines are on stderr and on the terminal, never on stdout
    assert "completed: 1 of 1 step(s)" in err
    assert sum(line == "Plan approval requested" for line in terminal.shown) == 1


def test_ctrl_c_at_the_code_prompt_leaves_the_plan_undecided(setup, cli, conn, monkeypatch):
    """Review of `6b83412`, point 2: SIGINT while `input()` waits only marks the task
    cancelled (asyncio.run's handler); a code typed after it must not grant anything."""
    import signal

    mcp, env, session = setup

    class Interrupted(ScriptedTerminal):
        def ask(self, question):
            signal.raise_signal(signal.SIGINT)  # what Ctrl+C does at the real prompt
            return super().ask(question)

    terminal = Interrupted([], [CODE])
    monkeypatch.setattr(plan_cli, "TtyTerminal", lambda: terminal)
    closed: list[str] = []
    real_close = plan_cli.close_resources

    async def close(provider):  # a close that awaits: a pending cancellation would cut it
        await asyncio.sleep(0.01)
        await real_close(provider)
        closed.append("closed")

    monkeypatch.setattr(plan_cli, "close_resources", close)
    code, _, err = cli("plan", session, QUESTION, **env)
    assert code == 130 and "interrupted: plan" in err and "was not approved" in err
    assert closed == ["closed"]
    assert mcp.starts() == 0
    assert rows(conn, "SELECT approval, means, status, error_code FROM plan_runs") == [
        ("undecided", None, "not_run", "undecided")]
    events = [e for (e,) in rows(conn, "SELECT event_type FROM audit_events "
                                       "WHERE event_type LIKE 'plan.%' ORDER BY rowid")]
    assert events == ["plan.approval.requested", "plan.approval.undecided"]


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
