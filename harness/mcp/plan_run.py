"""A plan of code mode once read: what is approved, how it is recorded and how it runs (D7, D9,
D10, D11, D12; code-mode slice 2).

What is shown, hashed and run is one thing. The approval content is written here from the
validated `Plan` (one line per step: server, tool, canonical arguments, the policy's decision,
what it reads), and the approval hash is the hash of a `Proposal` of `approvals.py` with that
content, the plan's own hash (which covers its nonce), the session, the question's request and
the plan's id. Before the first step, `execute_plan` writes that proposal again from the plan
it was handed and requires the same hash, requires the plan's canonical bytes to give its own
hash, and reads the steps it runs back from those bytes: a byte changed in any of the three
(what was hashed, what was shown, what would run) refuses the whole plan before anything
starts. The approval is then consumed in one statement (granted, this hash, not expired):
it can be used once.

Each step goes through `gateway.call_tool`, the path of `mcp call`: the policy is decided again
with the allowlist as it is now (the person may have edited it while the box was open), the
`tool_calls` row carries the plan's id and the step's position, the server's own deadlines and
result limit hold. The first step that is denied, fails or times out stops the plan; nothing
is retried. The whole plan has a deadline (the sum of its steps' session budgets, at most
`MAX_DEADLINE_S`); a `StopSignal` (Ctrl+C, or that deadline) ends the step in course and its
process tree, and the steps after it are not called.

A result is text from outside the harness: cleaned, redacted and bounded by `render`, and in
all at most `SHOWN_MAX_BYTES` of a plan's results are kept. It is only for the person in this
slice: `StepResult` is shaped so that a later slice can bound and mark it as data, but nothing
here sends anything to a provider.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid7

from harness.core.errors import HarnessError
from harness.mcp.audit import PlanLink, args_key, recover_stale
from harness.mcp.config import LoadedConfig
from harness.mcp.gateway import COMPLETED, DENIED, TIMEOUT, CallReport, call_tool, server_log
from harness.mcp.plan import PLAN_FORMAT, Plan, plan_hash
from harness.mcp.policy import canonical_json, parse_arguments
from harness.skills.approvals import Proposal, Verdict, normalise_content
from harness.storage import repositories as repo
from harness.storage.database import open_database, transaction
from harness.storage.locks import NamedLock

PLAN_SCOPE = "code-mode.plan"
PLAN_SKILL_NAME = "code-mode"  # the `skill` fields of a Proposal name the plan's reader
SHOWN_MAX_BYTES = 256 * 1024
MAX_DEADLINE_S = 300
IDENTITY_CHARS = 64
APPROVAL_STATEMENT = ("only the plan in this box runs: the reply above is the model's text "
                      "and may show something else")
BUTTON_QUESTION = "Approve runs these reads now; Reject runs nothing."
CUT_NOTICE = "[the plan's results passed {limit} bytes; the rest of this one is not shown]"


def deadline_s(plan: Plan, config: LoadedConfig) -> int:
    """The whole plan's deadline (D10): the sum of its steps' session budgets (startup and
    call of their server), never more than MAX_DEADLINE_S. A read that runs out of it has no
    effect to reconcile."""
    total = sum(config.servers[step.server].startup_timeout_s
                + config.servers[step.server].call_timeout_s for step in plan.steps)
    return max(1, min(MAX_DEADLINE_S, total))


# -- what is approved ---------------------------------------------------------------------------


def step_lines(plan: Plan) -> list[str]:
    """The approval content: for each step its server, tool, canonical arguments and the
    policy's decision (always `allowed`, or the plan would have been refused), then what it
    reads in plain words. Written by the harness from the validated plan alone, so that the
    executor can write it again from the plan it is handed."""
    lines: list[str] = []
    for position, step in enumerate(plan.steps, start=1):
        lines.append(f"step {position} of {len(plan.steps)} ({step.id}): "
                     f"{step.server}.{step.tool}  {step.operation}  allowed")
        lines.append(f"  args: {step.canonical_arguments.decode('utf-8')}")
        lines.append(f"  reads: {_reads(step.server, step.tool, step.arguments)}")
    lines.append(f"plan sha256: {plan.sha256}")
    return lines


def _reads(server: str, tool: str, arguments: Mapping[str, object]) -> str:
    values = ", ".join(f"{name} = {json.dumps(arguments[name], ensure_ascii=False)}"
                       for name in sorted(arguments))
    return f"tool {tool} of server {server}, " + (f"with {values}" if values
                                                  else "with no arguments")


def plan_proposal(plan: Plan, *, session_id: UUID | str, request_id: UUID | str,
                  plan_id: str) -> Proposal:
    """The Proposal approved for a plan (D7): its content is `step_lines`, unchanged by
    `normalise_content` because the reader refused every string it would change (D5)."""
    content = "\n".join(step_lines(plan))
    if normalise_content(content) != content:  # never, by D5; refuse rather than show another
        raise HarnessError("the plan cannot be shown as it is hashed; nothing was run")
    return Proposal(
        scope=PLAN_SCOPE,
        session_id=str(session_id),
        run_id=plan_id,
        step=str(request_id),
        skill_name=PLAN_SKILL_NAME,
        skill_version=PLAN_FORMAT,
        skill_sha256=plan.sha256,
        target=None,
        content=content,
    )


def approval_header(proposal: Proposal, plan: Plan, approval_hash: str, expires_at: str,
                    deadline: int) -> list[str]:
    """The harness's lines above the plan in the box (D9): the statement, what the plan is,
    the hash and the expiry. None of them comes from the reply."""
    return [
        "Plan approval requested",
        f"  {APPROVAL_STATEMENT}",
        f"  request:  {proposal.step} (the /plan question)",
        f"  plan:     {proposal.run_id}, {len(plan.steps)} step(s), every one a read of the "
        "local MCP list",
        f"  deadline: {deadline} s for the whole plan; the first step that fails stops it",
        "  results:  shown here only; nothing is sent back to the provider",
        f"  hash:     {approval_hash}",
        f"  expires:  {expires_at} (UTC)",
    ]


# -- the record ---------------------------------------------------------------------------------


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def record_plan(conn: sqlite3.Connection, *, plan_id: str, session_id: UUID, request_id: UUID,
                plan: Plan, approval_hash: str, deadline: int, now: datetime,
                ttl_s: int) -> str:
    """The plan's row, awaiting its approval; returns when the approval expires (UTC, ISO).
    Rows of this session still awaiting an approval belong to a process that is gone (the
    caller holds the session): they are closed as abandoned first."""
    expires = iso(now + timedelta(seconds=ttl_s))
    with transaction(conn):
        conn.execute(
            "UPDATE plan_runs SET approval = 'undecided', status = 'not_run', "
            "error_code = 'abandoned', finished_at = ? "
            "WHERE session_id = ? AND status = 'awaiting_approval'",
            (iso(now), str(session_id)),
        )
        conn.execute(
            "INSERT INTO plan_runs (plan_id, session_id, request_id, plan_sha256, "
            "approval_hash, steps, deadline_s, shown_max_bytes, approval, status, created_at, "
            "expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'awaiting_approval', ?, ?)",
            (plan_id, str(session_id), str(request_id), plan.sha256, approval_hash,
             len(plan.steps), deadline, SHOWN_MAX_BYTES, iso(now), expires),
        )
        _audit(conn, "plan.approval.requested", "pending", session_id, request_id,
               f"plan={plan_id};hash={approval_hash};steps={len(plan.steps)}")
    return expires


def record_verdict(conn: sqlite3.Connection, *, plan_id: str, verdict: Verdict,
                   identity: str, now: datetime) -> str:
    """The person's decision on the plan's row; returns the approval state it leaves:
    `granted`, `rejected`, `undecided`, or `expired` for a grant after the expiry (the
    prompt blocks until an answer, so the expiry is checked after it, as for a skill)."""
    row = conn.execute("SELECT session_id, request_id, expires_at FROM plan_runs "
                       "WHERE plan_id = ?", (plan_id,)).fetchone()
    decided = iso(now)
    state = verdict.decision
    if state == "granted" and decided >= row["expires_at"]:
        state = "expired"
    means = verdict.means if state != "undecided" else None
    status = "awaiting_approval" if state == "granted" else "not_run"
    error = None if state == "granted" else state
    with transaction(conn):
        conn.execute(
            "UPDATE plan_runs SET approval = ?, means = ?, identity = ?, decided_at = ?, "
            "status = ?, error_code = ?, finished_at = ? "
            "WHERE plan_id = ? AND approval = 'pending'",
            (state, means, identity[:IDENTITY_CHARS] if means else None, decided, status,
             error, decided if error else None, plan_id),
        )
        detail = f"plan={plan_id}" + (f";means={means}" if means else "")
        _audit(conn, f"plan.approval.{state}", state, UUID(row["session_id"]),
               UUID(row["request_id"]), detail)
    return state


def _audit(conn: sqlite3.Connection, event: str, outcome: str, session_id: UUID | None,
           request_id: UUID | None, detail: str) -> None:
    repo.insert_audit(conn, event_type=event, outcome=outcome, actor="cli",
                      session_id=session_id, request_id=request_id, detail=detail)


# -- running ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ApprovedPlan:
    """What the executor is handed: the plan as it was read, and what binds its approval."""

    plan: Plan
    plan_id: str
    session_id: UUID
    request_id: UUID
    approval_hash: str


@dataclass(frozen=True)
class StepResult:
    """One step as it ended. `text` is foreign text, already cleaned, redacted and bounded:
    the tool's result (completed) or its own error message (`error_code` "tool_error"), else
    empty. `detail` is the harness's explanation of a failure. Shaped so that a later slice
    can bound and mark `text` as data before it goes anywhere (A3)."""

    position: int
    step_id: str
    server: str
    tool: str
    status: str  # completed, denied, failed, timeout, interrupted, not_run
    error_code: str | None = None
    detail: str = ""
    text: str = ""
    redactions: int = 0
    result_bytes: int = 0
    duration_ms: int = 0
    cut: bool = False  # the plan's shown bound cut this text
    call_id: str | None = None


@dataclass(frozen=True)
class PlanReport:
    plan_id: str
    status: str  # completed, failed, interrupted, timeout, not_run
    steps: tuple[StepResult, ...] = ()
    stopped_at: int | None = None
    error_code: str | None = None
    detail: str = ""
    shown_bytes: int = 0


@dataclass
class _Clocks:
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    monotonic: Callable[[], float] = time.monotonic


def steps_from_canonical(canonical: bytes) -> list[tuple[str, str, str, bytes]]:
    """(id, server, tool, canonical arguments) of each step, read back from the plan's own
    canonical bytes: what runs is what was hashed."""
    data = json.loads(canonical.decode("utf-8"))
    return [(step["id"], step["server"], step["tool"], canonical_json(step["args"]))
            for step in data["steps"]]


def execute_plan(
    data_dir: Path,
    approved: ApprovedPlan,
    load_config: Callable[[], LoadedConfig],
    environ: Mapping[str, str],
    *,
    stop: object | None = None,
    clock: Callable[[], datetime] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> PlanReport:
    """Check, consume and run an approved plan, in the calling thread, with a database
    connection of its own (D10). Never raises for what a step does; returns the report."""
    from harness.mcp.client import StopSignal

    stopper = stop if isinstance(stop, StopSignal) else StopSignal()
    clocks = _Clocks(now=clock or (lambda: datetime.now(UTC)), monotonic=monotonic)
    conn = open_database(data_dir)
    lock = NamedLock(data_dir, f"plan-{approved.plan_id}")
    lock.acquire()
    try:
        recover_plans(conn, data_dir)
        return _execute(conn, data_dir, approved, load_config, environ, stopper, clocks)
    finally:
        lock.release()
        conn.close()


def _refuse_before(conn: sqlite3.Connection, approved: ApprovedPlan, code: str, detail: str,
                   now: datetime, *, consumed: bool) -> PlanReport:
    with transaction(conn):
        if consumed:
            conn.execute(
                "UPDATE plan_runs SET status = 'failed', error_code = ?, finished_at = ? "
                "WHERE plan_id = ?", (code, iso(now), approved.plan_id))
        else:
            conn.execute(
                "UPDATE plan_runs SET status = 'not_run', error_code = ?, finished_at = ? "
                "WHERE plan_id = ? AND status = 'awaiting_approval'",
                (code, iso(now), approved.plan_id))
        _audit(conn, "plan.denied", code, approved.session_id, approved.request_id,
               f"plan={approved.plan_id}")
    return PlanReport(approved.plan_id, "failed" if consumed else "not_run", error_code=code,
                      detail=detail)


def _execute(conn: sqlite3.Connection, data_dir: Path, approved: ApprovedPlan,
             load_config: Callable[[], LoadedConfig], environ: Mapping[str, str],
             stop: object, clocks: _Clocks) -> PlanReport:
    plan = approved.plan
    now = clocks.now()
    row = conn.execute("SELECT * FROM plan_runs WHERE plan_id = ?",
                       (approved.plan_id,)).fetchone()
    if row is None:
        with transaction(conn):
            _audit(conn, "plan.denied", "approval_not_usable", None, None,
                   f"plan={approved.plan_id}")
        return PlanReport(approved.plan_id, "not_run", error_code="approval_not_usable",
                          detail="this plan is not recorded; nothing was run")
    claimed = approved
    # From here on, the rows and the audit name the plan's own session and request.
    approved = dataclasses.replace(approved, session_id=UUID(row["session_id"]),
                                   request_id=UUID(row["request_id"]))
    # What was hashed = what was shown = what runs (D7): any byte changed refuses the plan.
    steps = steps_from_canonical(plan.canonical)
    altered = (
        plan_hash(plan.canonical) != plan.sha256
        or plan.sha256 != row["plan_sha256"]
        or claimed.approval_hash != row["approval_hash"]
        or [(s.id, s.server, s.tool, s.canonical_arguments) for s in plan.steps] != steps
    )
    if not altered:
        try:
            # Written again from the plan and the ids it was handed with: another request,
            # session or nonce gives another hash.
            proposal = plan_proposal(plan, session_id=claimed.session_id,
                                     request_id=claimed.request_id, plan_id=claimed.plan_id)
            altered = proposal.sha256 != row["approval_hash"]
        except HarnessError:
            altered = True
    if altered:
        return _refuse_before(conn, approved, "plan_altered",
                              "the plan is not the one approved; nothing was run", now,
                              consumed=False)
    with transaction(conn):
        consumed = conn.execute(
            "UPDATE plan_runs SET approval = 'consumed', status = 'running', started_at = ? "
            "WHERE plan_id = ? AND approval = 'granted' AND approval_hash = ? "
            "AND expires_at > ?",
            (iso(now), approved.plan_id, approved.approval_hash, iso(now)),
        ).rowcount
        if consumed == 1:
            _audit(conn, "plan.approval.consumed", "consumed", approved.session_id,
                   approved.request_id, f"plan={approved.plan_id}")
    if consumed != 1:
        return _refuse_before(conn, approved, "approval_not_usable",
                              "the approval cannot be used (not granted, already used, expired "
                              "or for another plan); nothing was run", now, consumed=False)
    try:
        # The allowlist as it is now: the person may have edited it while the box was open.
        config = load_config()
    except HarnessError:
        return _refuse_before(conn, approved, "config_error",
                              "the MCP list cannot be read now; nothing was run", now,
                              consumed=True)
    return _run_steps(conn, data_dir, approved, config, environ, stop, clocks, steps,
                      int(row["deadline_s"]))


def _run_steps(conn: sqlite3.Connection, data_dir: Path, approved: ApprovedPlan,
               config: LoadedConfig, environ: Mapping[str, str], stop: object,
               clocks: _Clocks, steps: list[tuple[str, str, str, bytes]],
               deadline: int) -> PlanReport:
    from harness.mcp.client import StopSignal

    assert isinstance(stop, StopSignal)
    key = args_key(data_dir)
    recover_stale(conn, data_dir)
    timer = threading.Timer(deadline, stop.set, args=("deadline",))
    timer.daemon = True
    timer.start()
    results: list[StepResult] = []
    shown = 0
    status, code, detail = COMPLETED, None, ""
    try:
        for position, (step_id, server, tool, arguments) in enumerate(steps, start=1):
            if stop.is_set():
                status, code = _stopped(stop)
                detail = "stopped before this step; it was not called"
                results.append(StepResult(position, step_id, server, tool, "not_run", code,
                                          detail))
                break
            parsed = parse_arguments(arguments.decode("utf-8"))
            try:
                report = call_tool(conn, data_dir, config, server, tool, parsed, key,
                                   lambda name=server: server_log(data_dir, name), environ,
                                   plan=PlanLink(approved.plan_id, position), stop=stop)
            except KeyboardInterrupt as interrupt:
                outcome = getattr(interrupt, "outcome", None)
                status, code = _stopped(stop)
                detail = ("the plan's deadline passed during this step; its process tree was "
                          "ended" if code == "deadline" else
                          "interrupted during this step; its process tree was ended")
                results.append(StepResult(position, step_id, server, tool, "interrupted",
                                          code, detail, duration_ms=getattr(
                                              outcome, "duration_ms", 0)))
                break
            result, shown = _step_result(position, step_id, server, tool, report, config,
                                         shown)
            results.append(result)
            if result.status != COMPLETED:
                status = "failed"
                code = {DENIED: "denied", TIMEOUT: "timeout"}.get(
                    result.status, "tool_error" if result.error_code == "tool_error"
                    else "call_failed")
                detail = result.detail
                break
    finally:
        timer.cancel()
    stopped_at = results[-1].position if status != COMPLETED else None
    with transaction(conn):
        conn.execute(
            "UPDATE plan_runs SET status = ?, stopped_at = ?, error_code = ?, finished_at = ? "
            "WHERE plan_id = ? AND status = 'running'",
            (status, stopped_at, code, iso(clocks.now()), approved.plan_id),
        )
        _audit(conn, "plan.finished", status, approved.session_id, approved.request_id,
               f"plan={approved.plan_id};steps_run={sum(r.status != 'not_run' for r in results)}"
               + (f";stopped_at={stopped_at}" if stopped_at else ""))
    return PlanReport(approved.plan_id, status, tuple(results), stopped_at, code, detail, shown)


def _stopped(stop: object) -> tuple[str, str]:
    reason = getattr(stop, "reason", None)
    return ("timeout", "deadline") if reason == "deadline" else ("interrupted", "interrupted")


def _step_result(position: int, step_id: str, server: str, tool: str, report: CallReport,
                 config: LoadedConfig, shown: int) -> tuple[StepResult, int]:
    from harness.mcp.commands import _explain

    outcome = report.outcome
    duration = outcome.duration_ms if outcome is not None else 0
    size = outcome.call_bytes if outcome is not None else 0
    if report.status == DENIED:
        decision = report.decision
        detail = f"denied: {decision.reason}" + (f": {decision.detail}" if decision.detail
                                                 else "")
        return StepResult(position, step_id, server, tool, DENIED, decision.reason, detail,
                          duration_ms=duration, call_id=report.call_id), shown
    text, redactions, cut = "", 0, False
    if report.rendered is not None:
        text, cut = _bounded(report.rendered.text, SHOWN_MAX_BYTES - shown)
        shown += len(text.encode("utf-8"))
        redactions = report.rendered.redactions
    if report.status == COMPLETED:
        return StepResult(position, step_id, server, tool, COMPLETED, None, "", text,
                          redactions, size, duration, cut, report.call_id), shown
    if report.error_code == "tool_error":
        detail = "the tool reported an error"
    else:
        entry = config.servers[server]
        detail = _explain(outcome, entry, entry.tools[tool].max_result_bytes)
    return StepResult(position, step_id, server, tool, report.status, report.error_code,
                      detail, text, redactions, size, duration, cut, report.call_id), shown


def _bounded(text: str, room: int) -> tuple[str, bool]:
    data = text.encode("utf-8")
    if len(data) <= room:
        return text, False
    kept = data[:max(0, room)].decode("utf-8", errors="ignore")
    return kept, True


def recover_plans(conn: sqlite3.Connection, data_dir: Path) -> int:
    """A plan left `running` by a process that is gone is `interrupted` (abandoned): its lock
    is free. Never resumed: its approval was consumed before its first step (D12)."""
    running = [r[0] for r in conn.execute(
        "SELECT plan_id FROM plan_runs WHERE status = 'running'").fetchall()]
    recovered = 0
    for plan_id in running:
        lock = NamedLock(data_dir, f"plan-{plan_id}")
        if not lock.acquire():
            continue
        try:
            with transaction(conn):
                recovered += conn.execute(
                    "UPDATE plan_runs SET status = 'interrupted', error_code = 'abandoned', "
                    "finished_at = ? WHERE plan_id = ? AND status = 'running'",
                    (iso(datetime.now(UTC)), plan_id),
                ).rowcount
        finally:
            lock.release()
    return recovered


def new_plan_id() -> str:
    return str(uuid7())
