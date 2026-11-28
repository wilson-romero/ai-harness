"""Reads allowed by rule (code-mode A2): `auto_read` in the local list, a plan of such reads
run without the box, the list's entries bound when the plan is read and checked again when
it runs, `means = rule` in the record and the audit, and the switch that turns the rule off.

The oracle of what ran is the synthetic server's own `starts.log` and `calls.log`; of what
was decided, the rows of `plan_runs`, `tool_calls` and `audit_events`."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sqlite3

import pytest

import harness.mcp.plan as plan_module
import harness.mcp.plan_flow as flow
from harness.mcp.config import ConfigError, load_config
from harness.mcp.plan import read_plan
from harness.mcp.plan_run import execute_plan, record_rule
from harness.storage.database import (
    FOREIGN_KEYS_OFF,
    MIGRATIONS_DIR,
    MigrationError,
    connect,
    migrate,
    transaction,
)
from tests.mcp_support import DEFAULT_TOOLS, hang_guard, server_entry, write_config  # noqa: F401
from tests.plan_support import ALPHA, BETA, QUESTION, McpList, plan_reply, rows, scripted_mock
from tests.shell_support import CODE, ScriptedTerminal, make_conversation

PLAN_LINE = f"/plan {QUESTION}"
AUTO = {**DEFAULT_TOOLS, "get_project_metadata": {**DEFAULT_TOOLS["get_project_metadata"],
                                                   "auto_read": True}}
ECHO = {"id": "e", "server": "synthetic", "tool": "echo_argv", "args": {}}


@pytest.fixture
def mcp(tmp_path, hang_guard) -> McpList:  # noqa: F811
    return McpList(tmp_path / "mcp", tools=AUTO)


def _run(conn, data_dir, mcp, provider, lines, approvals=(), **options):
    terminal = ScriptedTerminal(list(lines), list(approvals))
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider,
                                           mcp_config=options.pop("mcp_config", mcp.load),
                                           **options)
    asyncio.run(conversation.run())
    return terminal


def _plans(conn):
    return rows(conn, "SELECT status, approval, means, identity, error_code, stopped_at "
                      "FROM plan_runs ORDER BY rowid")


# -- the list ------------------------------------------------------------------------------------


def _config(tmp_path, tools: dict):
    path = write_config(tmp_path / "mcp.json", {"s": server_entry(tmp_path, tools=tools)})
    return load_config({"HARNESS_MCP_CONFIG": str(path)})


def test_auto_read_is_false_unless_the_person_writes_it(tmp_path):
    config = _config(tmp_path, DEFAULT_TOOLS)
    assert not any(tool.auto_read for tool in config.servers["s"].tools.values())
    assert _config(tmp_path, AUTO).servers["s"].tools["get_project_metadata"].auto_read


@pytest.mark.parametrize("entry", [
    {"operation": "write", "auto_read": True},
    {"operation": "read", "auto_read": "true"},  # strict: a string is not a boolean
    {"operation": "read", "auto_read": 1},
])
def test_auto_read_is_valid_only_as_a_boolean_on_a_read(tmp_path, entry):
    with pytest.raises(ConfigError) as refused:
        _config(tmp_path, {"t": entry})
    assert "tools.t" in str(refused.value)


# -- a plan of reads by rule -------------------------------------------------------------------


def test_a_plan_of_auto_reads_runs_without_the_box_and_says_so_first(conn, data_dir, mcp):
    provider = scripted_mock(plan_reply(ALPHA, BETA))
    terminal = _run(conn, data_dir, mcp, provider, [PLAN_LINE])
    assert terminal.questions == []  # no box, no code asked
    assert provider.calls == 1
    assert mcp.calls() == ["call get_project_metadata"] * 2
    assert _plans(conn) == [("completed", "consumed", "rule", "rule:auto_read", None, None)]
    text = terminal.text
    running = next(n for n, line in enumerate(terminal.shown) if line.startswith("running plan:"))
    assert "every one a read your local MCP list allows by rule (auto_read)" in text
    # Every step, with its server, tool and canonical arguments, before anything runs.
    following = terminal.shown[running + 1:running + 7]
    assert following[0] == ("| step 1 of 2 (a): synthetic.get_project_metadata  read  allowed"
                            "  auto_read")
    assert following[1] == '|   args: {"project":"demo-alpha"}'
    assert following[3].startswith("| step 2 of 2 (b):")
    assert terminal.shown.index(following[0]) < next(
        n for n, line in enumerate(terminal.shown) if "completed in" in line)
    granted = rows(conn, "SELECT outcome, detail FROM audit_events "
                         "WHERE event_type = 'plan.approval.granted'")
    assert len(granted) == 1 and granted[0][1].endswith(";means=rule")
    (calls,) = rows(conn, "SELECT COUNT(*) FROM tool_calls WHERE plan_id IS NOT NULL "
                          "AND status = 'completed'")
    assert calls == (2,)


def test_a_plan_with_one_read_not_by_rule_goes_to_the_box_whole(conn, data_dir, mcp):
    provider = scripted_mock(plan_reply(ALPHA, ECHO))
    terminal = _run(conn, data_dir, mcp, provider, [PLAN_LINE], [CODE])
    assert len(terminal.questions) == 1
    assert "running plan:" not in terminal.text
    assert "| step 1 of 2 (a): synthetic.get_project_metadata  read  allowed  auto_read" \
        in terminal.text
    assert "| step 2 of 2 (e): synthetic.echo_argv  read  allowed" in terminal.text
    assert mcp.calls() == ["call get_project_metadata", "call echo_argv"]
    assert _plans(conn)[0][:3] == ("completed", "consumed", "code")


def test_a_plan_left_undecided_in_the_box_runs_nothing_even_if_one_step_is_by_rule(
        conn, data_dir, mcp):
    terminal = _run(conn, data_dir, mcp, scripted_mock(plan_reply(ALPHA, ECHO)), [PLAN_LINE],
                    [None])
    assert len(terminal.questions) == 1
    assert mcp.starts() == 0
    assert _plans(conn)[0][:3] == ("not_run", "undecided", None)


def test_harness_auto_read_off_asks_the_box_for_every_plan(conn, data_dir, mcp):
    provider = scripted_mock(plan_reply(ALPHA, BETA))
    terminal = _run(conn, data_dir, mcp, provider, [PLAN_LINE], [CODE],
                    environ={"HARNESS_AUTO_READ": "off"})
    assert len(terminal.questions) == 1
    assert "running plan:" not in terminal.text
    assert _plans(conn)[0][:3] == ("completed", "consumed", "code")


def test_without_an_answer_and_the_rule_off_nothing_runs(conn, data_dir, mcp):
    terminal = _run(conn, data_dir, mcp, scripted_mock(plan_reply(ALPHA)), [PLAN_LINE],
                    environ={"HARNESS_AUTO_READ": "off"})
    assert len(terminal.questions) == 1 and mcp.starts() == 0


@pytest.mark.parametrize("value", ["yes", "ON", "0", ""])
def test_a_wrong_switch_sends_nothing(conn, data_dir, mcp, value):
    provider = scripted_mock(plan_reply(ALPHA))
    terminal = _run(conn, data_dir, mcp, provider, [PLAN_LINE],
                    environ={"HARNESS_AUTO_READ": value} if value else {})
    if value == "":  # unset: the default, on
        assert mcp.calls() == ["call get_project_metadata"]
        return
    assert "HARNESS_AUTO_READ must be on or off; nothing was sent" in terminal.text
    assert provider.calls == 0 and rows(conn, "SELECT COUNT(*) FROM requests") == [(0,)]


def test_the_decision_shown_is_the_policy_s_own(conn, data_dir, mcp, monkeypatch):
    """`allowed` in the step lines comes from the decision taken when the plan was read, not
    from a constant: a decision with another reason word shows that word."""
    real = plan_module.decide_before_start

    def probe(*args):
        return dataclasses.replace(real(*args), reason="allowed-probe")

    monkeypatch.setattr(plan_module, "decide_before_start", probe)
    terminal = _run(conn, data_dir, mcp, scripted_mock(plan_reply(ALPHA)), [PLAN_LINE])
    assert "| step 1 of 1 (a): synthetic.get_project_metadata  read  allowed-probe  auto_read" \
        in terminal.text


def test_record_rule_refuses_a_plan_that_is_not_wholly_by_rule(conn, data_dir, mcp):
    from harness.core.errors import HarnessError

    plan = read_plan(plan_reply(ALPHA, ECHO).replace("{{plan_nonce}}", "0" * 16),
                     nonce="0" * 16, config=mcp.load())
    assert not plan.by_rule
    with pytest.raises(HarnessError):
        record_rule(conn, plan_id="x", plan=plan, now=None)


# -- the list bound when the plan is read ------------------------------------------------------


def _change_before_running(monkeypatch, change):
    """Change the list after the plan is read and approved, just before the executor runs."""
    def instead(data_dir, approved, load_config, environ, **options):
        change()
        return execute_plan(data_dir, approved, load_config, environ, **options)

    monkeypatch.setattr(flow, "execute_plan", instead)


def _rewrite(mcp, **entry_options):
    tools = entry_options.pop("tools", AUTO)
    write_config(mcp.path, {"synthetic": server_entry(mcp.server.state, "ok", tools=tools,
                                                      **entry_options)})


CHANGES = {
    "command": dict(extra=("--extra-argument",)),
    "environment": dict(env=("HARNESS_SYNTHETIC_PROBE",)),
    "call deadline": dict(call=6),
    "startup deadline": dict(startup=6),
    "result limit": dict(tools={**AUTO, "get_project_metadata": {
        **AUTO["get_project_metadata"], "max_result_bytes": 2048}}),
    "operation by rule": dict(tools=DEFAULT_TOOLS),  # auto_read taken away
    "argument limits": dict(tools={**AUTO, "get_project_metadata": {
        **AUTO["get_project_metadata"],
        "arguments": {"project": {"type": "string", "max_length": 32, "required": True}}}}),
}


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_a_list_changed_after_the_plan_was_read_refuses_the_step(conn, data_dir, mcp,
                                                                 monkeypatch, change):
    _change_before_running(monkeypatch, lambda: _rewrite(mcp, **CHANGES[change]))
    terminal = _run(conn, data_dir, mcp, scripted_mock(plan_reply(ALPHA, BETA)), [PLAN_LINE])
    assert mcp.starts() == 0
    assert _plans(conn) == [("failed", "consumed", "rule", "rule:auto_read", "list_changed", 1)]
    assert "local MCP list's entry for synthetic.get_project_metadata changed" in terminal.text
    assert rows(conn, "SELECT COUNT(*) FROM tool_calls") == [(0,)]
    finished = rows(conn, "SELECT outcome, detail FROM audit_events "
                          "WHERE event_type = 'plan.finished'")
    assert len(finished) == 1 and finished[0][0] == "failed"
    assert finished[0][1].endswith(";steps_run=1;stopped_at=1")


def test_control_the_same_list_written_again_runs(conn, data_dir, mcp, monkeypatch):
    _change_before_running(monkeypatch, lambda: _rewrite(mcp))
    _run(conn, data_dir, mcp, scripted_mock(plan_reply(ALPHA, BETA)), [PLAN_LINE])
    assert mcp.calls() == ["call get_project_metadata"] * 2


def test_control_a_new_description_changes_nothing_that_runs(conn, data_dir, mcp, monkeypatch):
    described = {**AUTO, "get_project_metadata": {**AUTO["get_project_metadata"],
                                                   "description": "metadatos de un proyecto"}}
    _change_before_running(monkeypatch, lambda: _rewrite(mcp, tools=described))
    _run(conn, data_dir, mcp, scripted_mock(plan_reply(ALPHA)), [PLAN_LINE])
    assert mcp.calls() == ["call get_project_metadata"]


def test_a_command_changed_while_the_box_is_open_refuses_the_plan(conn, data_dir, tmp_path,
                                                                  hang_guard):  # noqa: F811
    """A plan the person approves in the box is bound the same way (review requirement for
    A2): the command that starts the server cannot change between the box and the run."""
    mcp = McpList(tmp_path / "box")

    class Editing(ScriptedTerminal):
        def ask(self, question):
            _rewrite(mcp, tools=DEFAULT_TOOLS, extra=("--extra-argument",))
            return super().ask(question)

    terminal = Editing([PLAN_LINE], [CODE])
    conversation, _, _ = make_conversation(conn, data_dir, terminal,
                                           scripted_mock(plan_reply(ALPHA)),
                                           mcp_config=mcp.load)
    asyncio.run(conversation.run())
    assert mcp.starts() == 0
    assert _plans(conn) == [("failed", "consumed", "code", "persona-local", "list_changed", 1)]
    assert "  bound:    the list's entries of these steps as they are now" in terminal.text


def test_a_step_after_the_first_is_refused_when_its_entry_changed(conn, data_dir, tmp_path,
                                                                  hang_guard):  # noqa: F811
    """Two servers: the list of the second changes; the first step runs, the second is not
    called (refused as a step, named in the record)."""
    first = McpList(tmp_path / "one", tools=AUTO)
    other_state = tmp_path / "two" / "state"
    other_state.mkdir(parents=True)
    servers = {"synthetic": server_entry(first.server.state, tools=AUTO),
               "other": server_entry(other_state, tools=AUTO)}
    write_config(first.path, servers)
    step_b = {**BETA, "server": "other"}

    def change():
        write_config(first.path, {**servers, "other": server_entry(other_state, tools=AUTO,
                                                                    call=7)})

    import harness.mcp.plan_flow as plan_flow
    original = plan_flow.execute_plan

    def instead(data_dir_, approved, load_config, environ, **options):
        change()
        return original(data_dir_, approved, load_config, environ, **options)

    plan_flow.execute_plan = instead
    try:
        terminal = _run(conn, data_dir, first, scripted_mock(plan_reply(ALPHA, step_b)),
                        [PLAN_LINE])
    finally:
        plan_flow.execute_plan = original
    assert first.calls() == ["call get_project_metadata"]
    assert not (other_state / "starts.log").exists()
    assert _plans(conn)[0][4:] == ("list_changed", 2)
    assert "entry for other.get_project_metadata changed" in terminal.text


# -- migration 010 ---------------------------------------------------------------------------


def _upgrade_from_009(data_dir, tmp_path) -> sqlite3.Connection:
    up_to_9 = tmp_path / "migrations-009"
    up_to_9.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("00[1-9]_*.sql")):
        (up_to_9 / path.name).write_text(path.read_text("utf-8"), "utf-8")
    conn = connect(data_dir)
    assert migrate(conn, up_to_9) == list(range(1, 10))
    return conn


def _seed_plan(conn) -> None:
    session, request, plan = ("0190a000-0000-7000-8000-00000000000" + c for c in "123")
    with transaction(conn):
        conn.execute("INSERT INTO sessions (session_id, name, project_id, provider, remote_ref, "
                     "status, created_at, updated_at) VALUES (?, 'Vieja', NULL, 'mock', NULL, "
                     "'active', '2026-11-01T00:00:00+00:00', '2026-11-01T00:00:00+00:00')",
                     (session,))
        conn.execute("INSERT INTO requests (request_id, session_id, status, started_at) "
                     "VALUES (?, ?, 'completed', '2026-11-01T00:00:01+00:00')", (request, session))
        conn.execute("INSERT INTO plan_runs (plan_id, session_id, request_id, plan_sha256, "
                     "approval_hash, steps, deadline_s, shown_max_bytes, approval, means, "
                     "identity, status, created_at, expires_at) VALUES (?, ?, ?, ?, ?, 1, 20, "
                     "1024, 'consumed', 'code', 'p', 'completed', 'a', 'b')",
                     (plan, session, request, "a" * 64, "b" * 64))
        conn.execute("INSERT INTO tool_calls (call_id, server, tool, operation, "
                     "decision, reason, args_bytes, status, created_at, plan_id, plan_step) "
                     "VALUES ('c1', 'synthetic', 'get_project_metadata', 'read', "
                     "'allowed', 'allowed', 0, 'completed', 'a', ?, 1)", (plan,))


def test_a_database_at_009_upgrades_to_010_and_keeps_its_plans_and_their_calls(data_dir,
                                                                                tmp_path):
    conn = _upgrade_from_009(data_dir, tmp_path)
    _seed_plan(conn)
    before = rows(conn, "SELECT plan_id, approval, means, status FROM plan_runs")
    assert migrate(conn)[:1] == [10]
    assert rows(conn, "SELECT plan_id, approval, means, status FROM plan_runs") == before
    assert rows(conn, "SELECT entries_sha256 FROM plan_runs") == [(None,)]
    assert rows(conn, "PRAGMA foreign_key_check") == []
    assert rows(conn, "PRAGMA foreign_keys") == [(1,)]
    assert rows(conn, "SELECT plan_id FROM tool_calls") == [before[0][:1]]
    with pytest.raises(sqlite3.IntegrityError):  # the reference is still enforced
        with transaction(conn):
            conn.execute("UPDATE tool_calls SET plan_id = 'no-such-plan'")
    with transaction(conn):  # and `rule` is now a means
        conn.execute("UPDATE plan_runs SET means = 'rule', error_code = 'list_changed'")
    conn.close()


def test_a_rebuilding_migration_that_would_break_a_reference_is_refused(data_dir, tmp_path):
    """The negative control of the foreign-keys-off migrations: one that drops the table a
    reference points to is rolled back whole, and the keys are on again."""
    conn = _upgrade_from_009(data_dir, tmp_path)
    _seed_plan(conn)
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "010_broken.sql").write_text(f"{FOREIGN_KEYS_OFF}\nDROP TABLE plan_runs;\n",
                                           "utf-8")
    with pytest.raises(MigrationError):
        migrate(conn, broken)
    assert rows(conn, "SELECT COUNT(*) FROM plan_runs") == [(1,)]
    assert rows(conn, "SELECT MAX(version) FROM schema_migrations") == [(9,)]
    assert rows(conn, "PRAGMA foreign_keys") == [(1,)]
    conn.close()


def test_a_plan_recorded_before_010_never_runs(conn, data_dir, mcp, monkeypatch):
    """Its row has no binding (NULL): the executor takes it as altered."""
    def instead(data_dir_, approved, load_config, environ, **options):
        own = connect(data_dir_)  # this runs in the executor's thread
        try:
            with transaction(own):
                own.execute("UPDATE plan_runs SET entries_sha256 = NULL")
        finally:
            own.close()
        return execute_plan(data_dir_, approved, load_config, environ, **options)

    monkeypatch.setattr(flow, "execute_plan", instead)
    _run(conn, data_dir, mcp, scripted_mock(plan_reply(ALPHA)), [PLAN_LINE])
    assert mcp.starts() == 0
    assert _plans(conn)[0][4] == "plan_altered"


def test_the_bound_hash_is_what_the_box_shows(conn, data_dir, tmp_path, hang_guard):  # noqa: F811
    mcp = McpList(tmp_path / "box")
    terminal = _run(conn, data_dir, mcp, scripted_mock(plan_reply(ALPHA)), [PLAN_LINE], [CODE])
    plan = read_plan(plan_reply(ALPHA).replace("{{plan_nonce}}", "0" * 16), nonce="0" * 16,
                     config=mcp.load())
    (stored,) = rows(conn, "SELECT entries_sha256 FROM plan_runs")[0]
    assert stored == plan.entries_sha256  # the same list gives the same binding
    assert f"(sha256 {stored[:16]})" in terminal.text
    assert json.loads(plan.canonical)["steps"][0]["tool"] == "get_project_metadata"


# -- the full screen ---------------------------------------------------------------------------


async def test_the_full_screen_runs_a_plan_by_rule_without_the_box(tmp_path, mcp):
    from harness.shell.tui import ApprovalScreen
    from tests.tui_support import SIZE, Tui
    from tests.unit.test_shell_tui import _query

    data_dir = tmp_path / "datos"
    data_dir.mkdir()
    tui = Tui(data_dir, scripted_mock(plan_reply(ALPHA, BETA)), mcp_config=mcp.load)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.send(pilot, PLAN_LINE)
        await tui.until(pilot, lambda: any("completed: 2 of 2" in t
                                           for t in tui.blocks("harness")))
        assert not isinstance(tui.app.screen, ApprovalScreen)
        harness = "\n".join(tui.blocks("harness"))
        assert "running plan:" in harness and "allows by rule (auto_read)" in harness
        foreign = "\n".join(tui.blocks("foreign"))
        assert "synthetic.get_project_metadata  read  allowed  auto_read" in foreign
        await tui.ready(pilot)
        await tui.send(pilot, "/exit")
    assert mcp.calls() == ["call get_project_metadata"] * 2
    assert _query(tui.data_dir, "SELECT means FROM plan_runs") == ["rule"]


# -- the CLI -------------------------------------------------------------------------------------


def test_the_cli_runs_a_plan_by_rule_without_the_code(tmp_path, cli, conn, monkeypatch,
                                                      hang_guard):  # noqa: F811
    import harness.mcp.plan_cli as plan_cli

    mcp = McpList(tmp_path / "cli", tools=AUTO)
    responses = tmp_path / "respuestas.json"
    responses.write_text(json.dumps({"etiqueta alpha": plan_reply(ALPHA)}), "utf-8")
    env = {"HARNESS_PROVIDER": "mock", "HARNESS_MOCK_RESPONSES": str(responses),
           "HARNESS_MCP_CONFIG": str(mcp.path)}
    _, out, _ = cli("session", "create", "Plan sintético", **env)
    terminal = ScriptedTerminal([], [])
    monkeypatch.setattr(plan_cli, "TtyTerminal", lambda: terminal)
    code, out, err = cli("plan", out.strip(), QUESTION, **env)
    assert code == 0, err
    assert terminal.questions == []
    assert "running plan:" in err
    assert "| step 1 of 1 (a): synthetic.get_project_metadata  read  allowed  auto_read" in out
    assert mcp.calls() == ["call get_project_metadata"]
    assert rows(conn, "SELECT status, means FROM plan_runs") == [("completed", "rule")]
