"""What was hashed = what was shown = what runs (code-mode D7), and an approval that runs one
plan once, for its own request (task 4.4). Each test lets the conversation reach the approval
for real and then changes ONE of the three, or reuses the approval, just before the executor
runs: the executor refuses and the synthetic server is never started."""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import timedelta

import pytest

import harness.mcp.plan_flow as flow
from uuid import uuid7

from harness.mcp.plan import Plan, plan_hash
from harness.mcp.plan_run import execute_plan, plan_proposal
from harness.storage.database import open_database
from tests.mcp_support import hang_guard  # noqa: F401 - fixture
from tests.plan_support import ALPHA, BETA, QUESTION, McpList, plan_reply, rows, scripted_mock
from tests.shell_support import CODE, ScriptedTerminal, make_conversation

PLAN_LINE = f"/plan {QUESTION}"


@pytest.fixture
def mcp(tmp_path, hang_guard) -> McpList:  # noqa: F811
    return McpList(tmp_path / "mcp")


def _converse(conn, data_dir, mcp, monkeypatch, change):
    """Run one approved `/plan`, calling `change(approved, data_dir)` in place of the real
    executor; it returns the (approved, kwargs) the real executor then gets, or runs it."""
    reports = []

    def instead(data_dir_, approved, load_config, environ, **options):
        report = change(approved, data_dir_, load_config, environ, options)
        reports.append(report)
        return report

    monkeypatch.setattr(flow, "execute_plan", instead)
    terminal = ScriptedTerminal([PLAN_LINE], [CODE])
    provider = scripted_mock(plan_reply(ALPHA, BETA))
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider,
                                           mcp_config=mcp.load)
    asyncio.run(conversation.run())
    assert provider.calls == 1
    return terminal, reports


def _plan_row(conn):
    return rows(conn, "SELECT status, approval, error_code FROM plan_runs")


def _real(approved, data_dir, load_config, environ, options):
    return execute_plan(data_dir, approved, load_config, environ, **options)


def test_control_the_unchanged_plan_runs(conn, data_dir, mcp, monkeypatch):
    _, (report,) = _converse(conn, data_dir, mcp, monkeypatch, _real)
    assert report.status == "completed"
    assert mcp.calls() == ["call get_project_metadata"] * 2


def _other_canonical(plan: Plan) -> bytes:
    return plan.canonical.replace(b"demo-beta", b"demo-zeta")


def test_changed_what_runs_refuses(conn, data_dir, mcp, monkeypatch):
    """The plan handed to the executor runs other arguments; its hash and the box are the
    approved ones."""

    def change(approved, *rest):
        plan = approved.plan
        steps = list(plan.steps)
        steps[1] = dataclasses.replace(steps[1], arguments={"project": "demo-zeta"},
                                       canonical_arguments=b'{"project":"demo-zeta"}')
        altered = dataclasses.replace(plan, canonical=_other_canonical(plan),
                                      steps=tuple(steps))
        return _real(dataclasses.replace(approved, plan=altered), *rest)

    terminal, (report,) = _converse(conn, data_dir, mcp, monkeypatch, change)
    assert (report.status, report.error_code) == ("not_run", "plan_altered")
    assert mcp.starts() == 0
    assert _plan_row(conn) == [("not_run", "granted", "plan_altered")]
    assert "the plan is not the one approved; nothing was run" in terminal.text


def test_changed_bytes_the_steps_do_not_show_refuse(conn, data_dir, mcp, monkeypatch):
    """Only the canonical bytes change (another nonce in them); the steps, the hash and the
    box are the approved ones. Only the comparison of the bytes with their hash sees it."""

    def change(approved, *rest):
        plan = approved.plan
        canonical = plan.canonical.replace(plan.nonce.encode(), b"0123456789abcdef")
        assert canonical != plan.canonical
        return _real(dataclasses.replace(approved, plan=dataclasses.replace(
            plan, canonical=canonical)), *rest)

    _, (report,) = _converse(conn, data_dir, mcp, monkeypatch, change)
    assert report.error_code == "plan_altered" and mcp.starts() == 0


def test_changed_what_was_hashed_refuses(conn, data_dir, mcp, monkeypatch):
    """The recorded hash of the plan is changed after the approval."""

    def change(approved, data_dir_, *rest):
        other = open_database(data_dir_)
        try:
            other.execute("UPDATE plan_runs SET plan_sha256 = ?", ("0" * 64,))
            other.commit()
        finally:
            other.close()
        return _real(approved, data_dir_, *rest)

    _, (report,) = _converse(conn, data_dir, mcp, monkeypatch, change)
    assert report.error_code == "plan_altered" and mcp.starts() == 0


def test_changed_what_was_shown_refuses(conn, data_dir, mcp, monkeypatch):
    """The box showed (and the person approved) a content that is not the plan's: the
    approval's hash does not match what the executor writes again from the plan."""
    real_proposal = flow.plan_proposal

    def shown_otherwise(plan, **ids):
        proposal = real_proposal(plan, **ids)
        return dataclasses.replace(proposal, content=proposal.content.replace(
            "demo-beta", "demo-zeta"))

    monkeypatch.setattr(flow, "plan_proposal", shown_otherwise)
    terminal, (report,) = _converse(conn, data_dir, mcp, monkeypatch, _real)
    assert '"demo-zeta"' in terminal.text  # what the box showed
    assert report.error_code == "plan_altered" and mcp.starts() == 0


def test_an_approval_runs_once(conn, data_dir, mcp, monkeypatch):
    def twice(*arguments):
        first = _real(*arguments)
        second = _real(*arguments)
        return dataclasses.replace(first, detail=f"second={second.error_code}")

    _, (report,) = _converse(conn, data_dir, mcp, monkeypatch, twice)
    assert report.status == "completed" and report.detail == "second=approval_not_usable"
    assert mcp.calls() == ["call get_project_metadata"] * 2  # the first run only


def test_a_plan_whose_lock_is_held_elsewhere_runs_nothing(conn, data_dir, mcp, monkeypatch):
    """Review of `6b83412`, point 3: the plan's lock not obtained fails closed; the row is left
    to its holder (still granted, never consumed here)."""
    from harness.storage.locks import NamedLock

    def held(approved, data_dir_, *rest):
        holder = NamedLock(data_dir_, f"plan-{approved.plan_id}")
        assert holder.acquire()
        try:
            return _real(approved, data_dir_, *rest)
        finally:
            holder.release()

    _, (report,) = _converse(conn, data_dir, mcp, monkeypatch, held)
    assert (report.status, report.error_code) == ("not_run", "plan_in_use")
    assert mcp.starts() == 0
    assert _plan_row(conn) == [("awaiting_approval", "granted", None)]
    assert rows(conn, "SELECT outcome FROM audit_events WHERE event_type = 'plan.denied'") == [
        ("plan_in_use",)]


def test_an_approval_never_runs_the_plan_for_another_request(conn, data_dir, mcp, monkeypatch):
    def other_request(approved, *rest):
        return _real(dataclasses.replace(approved, request_id=uuid7()), *rest)

    _, (report,) = _converse(conn, data_dir, mcp, monkeypatch, other_request)
    assert report.error_code == "plan_altered" and mcp.starts() == 0


def test_an_approval_never_runs_another_plan_with_its_hash(conn, data_dir, mcp, monkeypatch):
    """Another plan id (another row) presented with this approval's hash."""

    def other_plan(approved, *rest):
        return _real(dataclasses.replace(approved, plan_id="0" * 8 + approved.plan_id[8:]),
                     *rest)

    _, (report,) = _converse(conn, data_dir, mcp, monkeypatch, other_plan)
    assert report.status == "not_run" and mcp.starts() == 0


def test_an_approval_that_expires_before_the_run_runs_nothing(conn, data_dir, mcp,
                                                              monkeypatch):
    def late(approved, data_dir_, load_config, environ, options):
        later = options["clock"]() + timedelta(seconds=901)
        return execute_plan(data_dir_, approved, load_config, environ,
                            **{**options, "clock": lambda: later})

    _, (report,) = _converse(conn, data_dir, mcp, monkeypatch, late)
    assert report.error_code == "approval_not_usable" and mcp.starts() == 0


def test_interrupted_after_its_first_step_it_never_runs_again(conn, data_dir, mcp,
                                                              monkeypatch):
    """Spec «Interrumpido a mitad»: Ctrl+C between steps 1 and 2 (the stop signal set as
    step 1 returns); step 2 is not called, and the same approval cannot run it again."""
    import harness.mcp.plan_run as plan_run

    real_call = plan_run.call_tool

    def interrupt_between(approved, data_dir_, load_config, environ, options):
        stop = options["stop"]

        def call_then_stop(*arguments, **keywords):
            report = real_call(*arguments, **keywords)
            stop.set("interrupted")  # what Ctrl+C does, once step 1 is done
            return report

        monkeypatch.setattr(plan_run, "call_tool", call_then_stop)
        first = execute_plan(data_dir_, approved, load_config, environ, **options)
        monkeypatch.setattr(plan_run, "call_tool", real_call)
        again = execute_plan(data_dir_, approved, load_config, environ,
                             clock=options["clock"])
        return dataclasses.replace(first, detail=f"again={again.error_code}")

    terminal, (report,) = _converse(conn, data_dir, mcp, monkeypatch, interrupt_between)
    assert (report.status, report.stopped_at) == ("interrupted", 2)
    assert [s.status for s in report.steps] == ["completed", "not_run"]
    assert report.detail == "again=approval_not_usable"
    assert mcp.calls() == ["call get_project_metadata"]
    assert _plan_row(conn) == [("interrupted", "consumed", "interrupted")]
    assert "stopped at step 2 of 2" in terminal.text


def test_a_plan_left_running_by_a_dead_process_is_interrupted_never_resumed(
        conn, data_dir, mcp, monkeypatch):
    from harness.mcp.plan_run import recover_plans
    from harness.storage.locks import NamedLock

    _converse(conn, data_dir, mcp, monkeypatch, _real)
    (plan_id,) = rows(conn, "SELECT plan_id FROM plan_runs")[0]
    conn.execute("UPDATE plan_runs SET status = 'running', error_code = NULL")
    conn.commit()
    alive = NamedLock(data_dir, f"plan-{plan_id}")
    assert alive.acquire()
    try:
        assert recover_plans(conn, data_dir) == 0  # control: its process still holds it
    finally:
        alive.release()
    assert recover_plans(conn, data_dir) == 1
    assert _plan_row(conn) == [("interrupted", "consumed", "abandoned")]
    assert mcp.calls() == ["call get_project_metadata"] * 2  # nothing ran again


def test_the_proposal_binds_the_nonce_session_and_request(conn, data_dir, mcp, monkeypatch):
    def check(approved, *rest):
        plan = approved.plan
        base = plan_proposal(plan, session_id=approved.session_id,
                             request_id=approved.request_id, plan_id=approved.plan_id)
        assert base.sha256 == approved.approval_hash
        canonical = plan.canonical.replace(plan.nonce.encode(), b"0123456789abcdef")
        other_nonce = dataclasses.replace(plan, nonce="0123456789abcdef", canonical=canonical,
                                          sha256=plan_hash(canonical))
        for changed in (
            plan_proposal(other_nonce, session_id=approved.session_id,
                          request_id=approved.request_id, plan_id=approved.plan_id),
            plan_proposal(plan, session_id=uuid7(), request_id=approved.request_id,
                          plan_id=approved.plan_id),
            plan_proposal(plan, session_id=approved.session_id, request_id=uuid7(),
                          plan_id=approved.plan_id),
        ):
            assert changed.sha256 != base.sha256
        return _real(approved, *rest)

    _, (report,) = _converse(conn, data_dir, mcp, monkeypatch, check)
    assert report.status == "completed"
