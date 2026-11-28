"""`/plan`: one question, one plan, one approval, the reads, the results (code-mode slice 2).

The steps, in order, and what stops each:

1. The catalogue from the local allowlist (`plan_prompt`); no read tool, or a catalogue over
   its bounds, stops here: nothing recorded, nothing sent.
2. One question to the provider, with a new nonce and the harness's instructions first
   (`SessionService.ask_plan`): the provider's size check runs on the whole text before
   anything is recorded; a timeout after the send leaves the request `uncertain`, never resent.
3. The reply is shown as any reply. It is read for a plan only here, only because the person
   typed `/plan`, and only if it completed whole (`read_plan_reply`). No plan: it is the
   answer. A refusal: its reason is shown and nothing more happens (no repair, no resend).
4. The plan's approval (D9): the box (buttons) on the full screen, the typed code elsewhere,
   with the harness's header and the steps written by the harness from the validated plan;
   the approval is bound to the plan's id, its hash (which covers the nonce), the session and
   the question's request, and expires.
5. The steps run in a worker thread (`plan_run.execute_plan`), which Ctrl+C stops through a
   `StopSignal`; each step's result is shown as text from outside the harness, under a line
   the harness writes. Nothing goes back to the provider: exactly one question per `/plan`.

The conversation and the `plan` command show it through a `PlanView`; neither adds a way to
approve: the only answer that runs a plan is `approvals.decide` granting this plan's hash.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from harness.core.contracts import RequestStatus
from harness.core.service import SessionService
from harness.mcp.config import LoadedConfig
from harness.mcp.plan import NoPlan, Plan, Refusal, read_plan_reply
from harness.mcp.plan_prompt import build_catalogue, plan_instructions
from harness.mcp.plan_run import (
    BUTTON_QUESTION,
    SHOWN_MAX_BYTES,
    ApprovedPlan,
    PlanReport,
    StepResult,
    approval_header,
    deadline_s,
    execute_plan,
    new_plan_id,
    plan_proposal,
    record_plan,
    record_verdict,
)
from harness.memory.context import ProjectContext, new_nonce
from harness.providers.base import LLMProvider
from harness.skills.approvals import Terminal, Verdict, decide
from harness.text.safe_text import safe_line

PLAN_COMMAND = "/plan"


class PlanView(Protocol):
    """Where the steps of `/plan` are shown. Every method gets harness text except `reply`
    (the provider's reply) and the `text` of `result` (a tool's result): those are foreign
    and the view shows them as such."""

    def say(self, text: str) -> None: ...

    def reply(self, text: str) -> None: ...

    def result(self, header: str, text: str) -> None: ...

    def approval(self, header: list[str], content: list[str]) -> str:
        """Lay out the notice and hand it to the terminal; return the text `decide` shows."""
        ...

    def waiting(self) -> AbstractAsyncContextManager[None]: ...


@dataclass(frozen=True)
class PlanRequest:
    question: str
    session_id: UUID
    provider: LLMProvider
    context: ProjectContext | None = None
    attachment: str | None = None


@dataclass(frozen=True)
class PlanOutcome:
    """How one `/plan` ended: `answer` (the reply held no plan), `refused` (it held one the
    reader refused, or the question did not complete), `not_approved` (rejected, expired or
    undecided), `interrupted` (Ctrl+C at the code prompt: recorded as undecided) or `ran` (the
    executor was called; `report` says what it did)."""

    kind: str
    report: PlanReport | None = None

    @property
    def ok(self) -> bool:
        return self.kind == "answer" or (self.kind == "ran" and self.report is not None
                                         and self.report.status == "completed")


@dataclass(frozen=True)
class PlanSetting:
    """What the flow needs from outside; tests replace any of it."""

    data_dir: Path
    environ: Mapping[str, str]
    load_config: Callable[[], LoadedConfig]
    ttl_s: int
    confirm_rejection: bool = True
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


async def run_plan(request: PlanRequest, *, service: SessionService, conn, view: PlanView,
                   terminal: Terminal, setting: PlanSetting) -> PlanOutcome:
    """The whole of one `/plan` (see the module docstring)."""
    config = setting.load_config()
    catalogue = build_catalogue(config)
    nonce = new_nonce()
    instructions = plan_instructions(nonce, catalogue)
    left_out = (f"; {catalogue.write_tools} write tool(s) left out" if catalogue.write_tools
                else "")
    view.say(f"plan: catalogue of {len(catalogue.lines)} read tool(s) from "
             f"{catalogue.servers} server(s){left_out}")
    async with view.waiting():
        response = await service.ask_plan(
            request.session_id, request.provider, request.question, instructions,
            request.context, attachment=request.attachment,
            stored_text=f"{PLAN_COMMAND} {request.question}",
        )
    for warning in response.warnings:
        view.say(f"warning: {warning}")
    if response.status is RequestStatus.COMPLETED and response.text is not None:
        view.reply(response.text)
    else:
        detail = safe_line(response.detail or "").text
        view.say(f"error: request {response.request_id} ended as {response.status}: {detail}")
    reading = read_plan_reply(response, nonce=nonce, config=config)
    if isinstance(reading, NoPlan):
        view.say("plan: the reply holds no plan; it is the answer, and nothing was run")
        return PlanOutcome("answer")
    if isinstance(reading, Refusal):
        step = f" (step {reading.step})" if reading.step else ""
        view.say(f"warning: plan refused: {reading.reason}{step}: {reading.detail}; nothing "
                 "was run, and nothing is asked again")
        return PlanOutcome("refused")
    return await _approve_and_run(reading, request, response.request_id, config, service, conn,
                                  view, terminal, setting)


async def _approve_and_run(plan: Plan, request: PlanRequest, request_id: UUID,
                           config: LoadedConfig, service: SessionService, conn,
                           view: PlanView, terminal: Terminal,
                           setting: PlanSetting) -> PlanOutcome:
    plan_id = new_plan_id()
    deadline = deadline_s(plan, config)
    proposal = plan_proposal(plan, session_id=request.session_id, request_id=request_id,
                             plan_id=plan_id)
    approval_hash = proposal.sha256
    expires = record_plan(conn, plan_id=plan_id, session_id=request.session_id,
                          request_id=request_id, plan=plan, approval_hash=approval_hash,
                          deadline=deadline, now=setting.clock(), ttl_s=setting.ttl_s)
    header = approval_header(proposal, plan, approval_hash, expires, deadline)
    # The box shows the very content that was hashed, line by line (D7).
    shown = view.approval(header, proposal.content.split("\n"))
    if terminal.is_interactive():
        verdict = decide(terminal, shown, approval_hash,
                         confirm_rejection=setting.confirm_rejection,
                         button_question=BUTTON_QUESTION)
    else:
        verdict = Verdict("undecided")
    interrupted = _withdraw_pending_interrupt()
    if interrupted:
        verdict = Verdict("undecided")  # whatever was typed after the Ctrl+C grants nothing
    state = record_verdict(conn, plan_id=plan_id, verdict=verdict,
                           identity=terminal.identity(), now=setting.clock())
    if interrupted:
        view.say(f"interrupted: plan {plan_id} was not approved; nothing was run, and this "
                 "approval cannot be used again")
        return PlanOutcome("interrupted")
    if state != "granted":
        view.say({
            "rejected": f"plan: {plan_id} was rejected; nothing was run",
            "expired": f"plan: {plan_id}: the approval expired before the answer; nothing "
                       "was run. Ask /plan again for a new one",
            "undecided": f"plan: {plan_id} was not approved; nothing was run, and this "
                         "approval cannot be used again",
        }[state])
        return PlanOutcome("not_approved")
    view.say(f"plan: {plan_id} approved; running {len(plan.steps)} step(s) in order, "
             f"{deadline} s at most (Ctrl+C stops it)")
    approved = ApprovedPlan(plan, plan_id, request.session_id, request_id, approval_hash)
    report = await run_in_thread(functools.partial(
        execute_plan, setting.data_dir, approved, setting.load_config, setting.environ,
        clock=setting.clock,
    ))
    show_report(view, report, len(plan.steps), deadline)
    return PlanOutcome("ran", report)


def _withdraw_pending_interrupt() -> bool:
    """True if this task was cancelled while the code prompt blocked it (Ctrl+C under
    `asyncio.run` only marks the task: `input()` keeps waiting). The cancellation is withdrawn
    so that the caller's cleanup (closing the provider) is not cut by it on its first await;
    the interruption is reported by the outcome instead."""
    task = asyncio.current_task()
    if task is None or not task.cancelling():
        return False
    while task.cancelling():
        task.uncancel()  # at zero this also clears the pending CancelledError (3.13+)
    return True


async def run_in_thread(execute: Callable[..., PlanReport]) -> PlanReport:
    """Run the plan in a worker thread (the MCP client runs its own event loop) and turn a
    cancellation of this task (Ctrl+C) into a stop of the plan: the step in course and its
    process tree end, the following ones are not called, and the report still comes back."""
    from harness.mcp.client import StopSignal

    stop = StopSignal()
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, functools.partial(execute, stop=stop))
    while True:
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            stop.set("interrupted")
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()  # the interruption is reported by the plan itself


def step_header(result: StepResult, total: int) -> str:
    where = f"step {result.position} of {total} ({result.step_id}): {result.server}.{result.tool}"
    if result.status == "completed":
        return (f"{where} completed in {result.duration_ms} ms, {result.result_bytes} bytes, "
                f"{result.redactions} credential(s) redacted")
    if result.status == "not_run":
        return f"{where} not run: {result.detail}"
    word = "interrupted" if result.status == "interrupted" else "error"
    return f"{word}: {where} {result.status}: {result.detail}"


def show_report(view: PlanView, report: PlanReport, total: int, deadline: int) -> None:
    for result in report.steps:
        header = step_header(result, total)
        if result.text:
            view.result(header, result.text)
        else:
            view.say(header)
        if result.cut:
            view.say(f"[the plan's results passed {SHOWN_MAX_BYTES} bytes; the rest is not "
                     "shown]")
    where = f"plan {report.plan_id}"
    run = sum(r.status != "not_run" for r in report.steps)
    if report.status == "completed":
        view.say(f"plan: {report.plan_id} completed: {run} of {total} step(s); the results "
                 "are only on this screen, nothing was sent to the provider")
    elif report.status == "interrupted":
        view.say(f"interrupted: {where} stopped at step {report.stopped_at} of {total}; the "
                 "steps after it were not called, and it is never run again with this "
                 "approval")
    elif report.status == "timeout":
        view.say(f"error: {where} ran out of its {deadline} s deadline at step "
                 f"{report.stopped_at} of {total}; the steps after it were not called")
    elif report.status == "not_run":
        view.say(f"error: {where} was not run: {report.detail}")
    else:
        stopped = f" at step {report.stopped_at} of {total}" if report.stopped_at else ""
        view.say(f"error: {where} failed{stopped}: {report.detail or report.error_code}; the "
                 "steps after it were not called, and nothing is retried")
