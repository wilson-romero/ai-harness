"""Running a skill inside a session (skill-engine D7-D14).

A run holds the session lock for the whole invocation of `run` or `resume`, and releases it on
finishing, on pausing for an approval and on any error. Inputs are never stored, only their
SHA-256 and size; step outputs are stored only when the session's provider is synthetic. A step
whose question may have reached the provider is never repeated without an explicit
`--retry-step`, and an effect runs only after its approval is consumed in the same transaction
that marks the step as applying.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

from harness.core.contracts import RequestStatus, Session
from harness.core.errors import HarnessError, InvalidIdentifier, InvalidInput, SessionBusy
from harness.core.service import SessionService
from harness.memory.context import ProjectContext
from harness.providers.base import LLMProvider
from harness.skills.approvals import (
    MAX_CONTENT_BYTES,
    Proposal,
    Terminal,
    TtyTerminal,
    decide,
    normalise_content,
    render_for_terminal,
)
from harness.skills.checks import check, parse_fields
from harness.skills.config import DEFAULT_APPROVAL_TTL_S
from harness.skills.definition import (
    ApprovalStep,
    LlmStep,
    Skill,
    ValidateStep,
    find_references,
    load_skill,
    validate_skill_name,
)
from harness.skills.effects import Effect, EffectContext, default_effects
from harness.skills.references import new_nonce, reference_key, render
from harness.storage import repositories as repo
from harness.storage.database import transaction
from harness.storage.locks import SessionLock

MAX_INPUT_BYTES = 64 * 1024
MAX_INPUTS_TOTAL_BYTES = 128 * 1024
MAX_PROMPT_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 128 * 1024
MAX_RUN_TIME_S = 1800
MAX_ATTEMPTS = 3

OPEN_RUN_STATES = ("pending", "running", "awaiting_approval", "uncertain")
FINAL_RUN_STATES = ("completed", "failed", "cancelled")

ContextBuilder = Callable[[str], ProjectContext]


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    status: str
    output: str | None = None
    message: str | None = None


@dataclass
class _Run:
    """What one invocation knows about the run it is advancing."""

    run_id: str
    session: Session
    provider: LLMProvider
    skill: Skill
    inputs: Mapping[str, str]
    outputs: dict[str, str] = field(default_factory=dict)  # this invocation's step outputs
    started: float = 0.0


@dataclass(frozen=True)
class _Proposed:
    """One `prepare`: the proposal (None if too large), where it goes and what it came from."""

    proposal: Proposal | None
    effect_ref: str | None
    source: str


def utc_iso(moment: datetime) -> str:
    """Fixed-width UTC timestamps, so that SQLite compares them as text correctly."""
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def parse_run_id(raw: str) -> str:
    try:
        value = UUID(raw)
    except (ValueError, AttributeError, TypeError):
        raise InvalidIdentifier(f"{raw!r} is not a valid run identifier") from None
    if str(value) != raw.lower():
        raise InvalidIdentifier(f"{raw!r} is not a valid run identifier")
    return str(value)


def inputs_manifest(inputs: Mapping[str, str]) -> str:
    manifest = {
        name: {
            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "bytes": len(value.encode("utf-8")),
        }
        for name, value in inputs.items()
    }
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"))


def step_marker(skill: str, step: str, attempt: int) -> str:
    return f"[skill {skill}/{step} intento {attempt}]"


class SkillEngine:
    def __init__(
        self,
        conn: sqlite3.Connection,
        data_dir: Path,
        sessions: SessionService,
        skills_root: Path | None,
        *,
        default_timeout_s: float,
        effects: Mapping[str, Effect] | None = None,
        terminal: Terminal | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        approval_ttl_s: int = DEFAULT_APPROVAL_TTL_S,
        context_builder: ContextBuilder | None = None,
        progress: Callable[[str], None] | None = None,
        run_time_limit_s: float = MAX_RUN_TIME_S,
    ) -> None:
        self._conn = conn
        self._data_dir = data_dir
        self._sessions = sessions
        self._root = skills_root
        self._default_timeout_s = default_timeout_s
        self._effects = dict(effects) if effects is not None else dict(default_effects())
        self._terminal = terminal or TtyTerminal()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        self._ttl_s = approval_ttl_s
        self._context_builder = context_builder
        self._progress = progress or (lambda _message: None)
        self._run_time_limit_s = run_time_limit_s

    # -- commands -------------------------------------------------------------------------------

    async def run(self, name: str, raw_session_id: str, inputs: Mapping[str, str]) -> RunOutcome:
        validate_skill_name(name)
        skill = load_skill(self._root, name, self._effects.keys())
        session = self._sessions.require_session(raw_session_id)
        provider = self._sessions.provider_for(session)
        manifest = self._check_inputs(skill, inputs)
        self._check_memory(skill, session)
        if (
            not provider.synthetic_content
            and skill.has_approval()
            and not self._terminal.is_interactive()
        ):
            raise InvalidInput(
                f"skill {name!r} needs an approval and provider {provider.name!r} does not keep "
                "its outputs, so the run could not be resumed later: run it in an interactive "
                "terminal"
            )
        lock = self._lock(session)
        try:
            open_run = self._conn.execute(
                "SELECT run_id, status FROM skill_runs WHERE session_id = ? AND status IN "
                "(?, ?, ?, ?)",
                (str(session.session_id), *OPEN_RUN_STATES),
            ).fetchone()
            if open_run is not None:
                raise InvalidInput(
                    f"session {session.session_id} already has an open run "
                    f"{open_run['run_id']} ({open_run['status']}); finish or cancel it first"
                )
            run_id = str(uuid7())
            now = utc_iso(self._clock())
            try:
                with transaction(self._conn):
                    self._conn.execute(
                        "INSERT INTO skill_runs (run_id, session_id, skill_name, skill_version, "
                        "skill_sha256, status, inputs_manifest, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?)",
                        (run_id, str(session.session_id), skill.name, skill.version,
                         skill.sha256, manifest, now, now),
                    )
                    for position, step in enumerate(skill.workflow.steps):
                        self._insert_step(run_id, step.id, position, step.kind, 1)
                    self._audit("skill.run", "started", session, run_id,
                                f"skill={skill.name};version={skill.version};sha256={skill.sha256}")
            except sqlite3.IntegrityError:
                raise InvalidInput(
                    f"session {session.session_id} already has an open run"
                ) from None
            self._progress(f"run {run_id}: {skill.name} {skill.version}")
            state = _Run(run_id, session, provider, skill, inputs, started=self._monotonic())
            return await self._advance(state)
        finally:
            lock.release()

    async def resume(
        self, raw_run_id: str, inputs: Mapping[str, str], retry_step: str | None = None
    ) -> RunOutcome:
        run_id = parse_run_id(raw_run_id)
        row = self._require_run(run_id)
        if row["status"] in FINAL_RUN_STATES:
            raise InvalidInput(f"run {run_id} is {row['status']}; there is nothing to resume")
        skill = self._load_same_skill(row)
        session = self._sessions.require_session(row["session_id"])
        provider = self._sessions.provider_for(session)
        lock = self._lock(session)
        try:
            row = self._require_run(run_id)  # re-read with the lock held
            if row["status"] in FINAL_RUN_STATES:
                raise InvalidInput(f"run {run_id} is {row['status']}; there is nothing to resume")
            if any(s["status"] in ("running", "applying")
                   for s in self._latest_steps(run_id).values()):
                # We hold the lock: whoever left these steps half done is gone.
                with transaction(self._conn):
                    _recover_run(self._conn, run_id, row["session_id"])
            latest = self._latest_steps(run_id)
            self._check_resume_inputs(row, skill, latest, inputs)
            state = _Run(run_id, session, provider, skill, inputs, started=self._monotonic())
            for key, step_row in latest.items():
                if step_row["kind"] == "approval" and step_row["status"] == "uncertain":
                    if retry_step == key:
                        raise InvalidInput(
                            f"step {key!r} of run {run_id} is an approval whose effect may "
                            "have been applied: it is never retried. `skill resume "
                            f"{run_id}` checks whether the effect is in place"
                        )
                    self._reconcile(state, key, step_row)
            latest = self._latest_steps(run_id)
            uncertain = [key for key, step in latest.items() if step["status"] == "uncertain"]
            if uncertain and retry_step is None:
                raise InvalidInput(
                    f"step {uncertain[0]!r} of run {run_id} is uncertain: its question may have "
                    f"reached the provider. Use `skill resume {run_id} --retry-step "
                    f"{uncertain[0]}` to ask again (the question may be duplicated in the "
                    f"conversation) or `skill cancel {run_id}`"
                )
            if retry_step is not None and retry_step not in uncertain:
                raise InvalidInput(
                    f"step {retry_step!r} is not an uncertain step of run {run_id}; nothing changed"
                )
            missing = self._missing_outputs(skill, latest)
            if missing:
                self._finish_run(run_id, session, "failed", "outputs_not_retained")
                return RunOutcome(
                    run_id, "failed",
                    message=f"the outputs of step(s) {', '.join(missing)} were not stored "
                    "(the provider's content is not synthetic); the run cannot continue",
                )
            if retry_step is not None:
                attempt = latest[retry_step]["attempt"]
                if attempt >= MAX_ATTEMPTS:
                    self._limit(session, run_id, retry_step, "attempts")
                    raise InvalidInput(
                        f"step {retry_step!r} already had {MAX_ATTEMPTS} attempts; "
                        f"cancel the run with `skill cancel {run_id}`"
                    )
                with transaction(self._conn):
                    step = skill.step(retry_step)
                    self._insert_step(run_id, retry_step, latest[retry_step]["position"],
                                      step.kind, attempt + 1)
                    self._audit("skill.step.reconciled", "retry", session, run_id,
                                f"step={retry_step};attempt={attempt + 1}")
            self._set_run(run_id, "running")
            return await self._advance(state)
        finally:
            lock.release()

    def cancel(self, raw_run_id: str) -> RunOutcome:
        run_id = parse_run_id(raw_run_id)
        row = self._require_run(run_id)
        session = self._sessions.require_session(row["session_id"])
        lock = SessionLock(self._data_dir, session.session_id)
        if not lock.acquire():
            raise SessionBusy(f"run {run_id} is in progress in another process; nothing changed")
        try:
            row = self._require_run(run_id)
            if row["status"] not in ("pending", "awaiting_approval", "uncertain"):
                raise InvalidInput(f"run {run_id} is {row['status']}; nothing changed")
            now = utc_iso(self._clock())
            with transaction(self._conn):
                for approval in self._conn.execute(
                    "SELECT approval_id, step_key, proposal_hash FROM approvals "
                    "WHERE run_id = ? AND status IN ('pending', 'granted')",
                    (run_id,),
                ).fetchall():
                    self._conn.execute(
                        "UPDATE approvals SET status = 'revoked', decided_at = ? "
                        "WHERE approval_id = ?",
                        (now, approval["approval_id"]),
                    )
                    self._audit("approval.revoked", "cancelled", session, run_id,
                                self._approval_detail(approval))
                self._conn.execute(
                    "UPDATE skill_runs SET status = 'cancelled', error_code = 'cancelled', "
                    "updated_at = ?, finished_at = ? WHERE run_id = ?",
                    (now, now, run_id),
                )
                self._audit("skill.run", "cancelled", session, run_id, None)
            return RunOutcome(run_id, "cancelled")
        finally:
            lock.release()

    def status(self, raw_run_id: str) -> dict[str, Any]:
        """Everything about a run except contents; takes no lock."""
        run_id = parse_run_id(raw_run_id)
        row = self._require_run(run_id)
        steps = self._conn.execute(
            "SELECT step_key, kind, attempt, status, error_code FROM skill_steps "
            "WHERE run_id = ? ORDER BY position, attempt",
            (run_id,),
        ).fetchall()
        approval = self._conn.execute(
            "SELECT approval_id, step_key, status, expires_at FROM approvals "  # no hash (8.2)
            "WHERE run_id = ? AND status IN ('pending', 'granted')",
            (run_id,),
        ).fetchone()
        return {"run": dict(row), "steps": [dict(s) for s in steps],
                "approval": dict(approval) if approval else None}

    def final_output(self, raw_run_id: str) -> str | None:
        run_id = parse_run_id(raw_run_id)
        row = self._require_run(run_id)
        skill_output = self._conn.execute(
            "SELECT s.output_text FROM skill_steps s WHERE s.run_id = ? AND s.status = "
            "'completed' AND s.step_key = (SELECT current_step FROM skill_runs WHERE run_id = ?) "
            "ORDER BY attempt DESC LIMIT 1",
            (run_id, run_id),
        ).fetchone()
        if row["status"] != "completed" or skill_output is None:
            return None
        return skill_output["output_text"]

    async def _apply_approval(self, raw_run_id: str, step_key: str, approval_id: str) -> bool:
        """Try to consume a given approval and run its effect, under the session lock.

        Not a command: it exists so that tests can try a second use of an approval, or the
        approval of another run, directly (D12). It takes the session lock like `run` and
        `resume` (review 8.9, 2026-11-24).
        """
        run_id = parse_run_id(raw_run_id)
        row = self._require_run(run_id)
        skill = self._load_same_skill(row)
        session = self._sessions.require_session(row["session_id"])
        provider = self._sessions.provider_for(session)
        lock = self._lock(session)
        try:
            state = _Run(run_id, session, provider, skill, {}, started=self._monotonic())
            step = skill.step(step_key)
            assert isinstance(step, ApprovalStep)
            proposed = self._propose(state, step)
            if proposed.proposal is None:
                return False
            outcome = await self._apply(state, step, approval_id, proposed)
            return outcome is None
        finally:
            lock.release()

    # -- the loop -------------------------------------------------------------------------------

    async def _advance(self, state: _Run) -> RunOutcome:
        skill = state.skill
        for step in skill.workflow.steps:
            latest = self._latest_steps(state.run_id)[step.id]
            if latest["status"] == "completed":
                continue
            if self._monotonic() - state.started >= self._run_time_limit_s:
                return self._stop(state, step.id, latest, "limit:run_time", limit="run_time")
            self._conn.execute(
                "UPDATE skill_runs SET current_step = ?, updated_at = ? WHERE run_id = ?",
                (step.id, utc_iso(self._clock()), state.run_id),
            )
            if isinstance(step, LlmStep):
                outcome = await self._llm(state, step, latest)
            elif isinstance(step, ValidateStep):
                outcome = self._validate(state, step, latest)
            else:
                outcome = await self._approval(state, step, latest)
            if outcome is not None:
                return outcome
        output = self._output(state, skill.workflow.output)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE skill_runs SET status = 'completed', current_step = ?, updated_at = ?, "
                "finished_at = ? WHERE run_id = ?",
                (skill.workflow.output, utc_iso(self._clock()), utc_iso(self._clock()),
                 state.run_id),
            )
            self._audit("skill.run", "completed", state.session, state.run_id, None)
        return RunOutcome(state.run_id, "completed", output=output)

    async def _llm(self, state: _Run, step: LlmStep, row: sqlite3.Row) -> RunOutcome | None:
        attempt = row["attempt"]
        prompt = render(state.skill.templates[step.template], self._values(state, step),
                        new_nonce())
        if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            return self._stop(state, step.id, row, "limit:prompt_bytes", limit="prompt_bytes")
        context = None
        if step.memory == "project":
            assert state.session.project_id is not None  # checked before the run
            if self._context_builder is None:
                raise InvalidInput("this step needs the project memory, which is not configured")
            context = self._context_builder(state.session.project_id)
        timeout_s = float(step.timeout_s or self._default_timeout_s)
        remaining = self._run_time_limit_s - (self._monotonic() - state.started)
        timeout_s = max(0.001, min(timeout_s, remaining))
        self._set_step(row, "running", started=True)
        self._progress(f"step {step.id} (llm, attempt {attempt})")
        response = await self._sessions.ask_with_lock_held(
            state.session.session_id,
            state.provider,
            prompt,
            context,
            stored_text=step_marker(state.skill.name, step.id, attempt),
            timeout_s=timeout_s,
        )
        self._conn.execute(
            "UPDATE skill_steps SET request_id = ? WHERE step_id = ?",
            (str(response.request_id), row["step_id"]),
        )
        if response.status is RequestStatus.UNCERTAIN:
            with transaction(self._conn):
                self._set_step(row, "uncertain", error_code=response.status.value, finished=True)
                self._set_run(state.run_id, "uncertain", error_code="step_uncertain")
                self._audit("skill.step", "uncertain", state.session, state.run_id,
                            f"step={step.id};attempt={attempt}")
            return RunOutcome(
                state.run_id, "uncertain",
                message=f"step {step.id!r} is uncertain: {response.detail}. Use `skill resume "
                f"{state.run_id} --retry-step {step.id}` or `skill cancel {state.run_id}`",
            )
        if response.status is not RequestStatus.COMPLETED or response.text is None:
            code = f"request_{response.status.value}"
            with transaction(self._conn):
                self._set_step(row, "failed", error_code=code, finished=True)
                self._finish_run_locked(state.run_id, state.session, "failed", code)
            return RunOutcome(state.run_id, "failed", message=f"step {step.id!r}: {response.detail}")
        if len(response.text.encode("utf-8")) > MAX_RESPONSE_BYTES:
            return self._stop(state, step.id, row, "limit:response_bytes", limit="response_bytes")
        self._complete(state, step.id, row, response.text)
        return None

    def _validate(self, state: _Run, step: ValidateStep, row: sqlite3.Row) -> RunOutcome | None:
        self._set_step(row, "running", started=True)
        result = check(step, self._output(state, step.of))
        if not result.ok:
            with transaction(self._conn):
                self._set_step(row, "failed", error_code=result.error_code, finished=True)
                self._finish_run_locked(state.run_id, state.session, "failed", result.error_code)
            return RunOutcome(state.run_id, "failed",
                              message=f"step {step.id!r} failed: {result.error_code}")
        assert result.output is not None
        self._complete(state, step.id, row, result.output)
        return None

    # -- approval -------------------------------------------------------------------------------

    def _propose(self, state: _Run, step: ApprovalStep) -> _Proposed:
        """The proposal from what is stored (and this invocation's outputs): one `prepare`.

        Everything after this works on the returned proposal: what is shown, hashed, consumed
        and applied is the same object (review 8.3, 2026-11-24).
        """
        effect = self._effects[step.effect]
        source = self._output(state, step.of)
        prepared = effect.prepare(self._effect_context(state, step), source)
        content = normalise_content(prepared.content)
        if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
            return _Proposed(None, prepared.effect_ref, source)
        proposal = Proposal(
            scope=effect.scope,
            session_id=str(state.session.session_id),
            run_id=state.run_id,
            step=step.id,
            skill_name=state.skill.name,
            skill_version=state.skill.version,
            skill_sha256=state.skill.sha256,
            target=prepared.target,
            content=content,
        )
        return _Proposed(proposal, prepared.effect_ref, source)

    async def _approval(
        self, state: _Run, step: ApprovalStep, row: sqlite3.Row
    ) -> RunOutcome | None:
        proposed = self._propose(state, step)
        proposal = proposed.proposal
        if proposal is None:
            return self._stop(state, step.id, row, "limit:proposal_bytes", limit="proposal_bytes")
        proposal_hash = proposal.sha256
        now = utc_iso(self._clock())
        live = self._live_approval(state.run_id, step.id)
        if live is not None and live["status"] == "pending" and live["expires_at"] <= now:
            with transaction(self._conn):
                self._set_approval(live["approval_id"], "expired", decided_at=now)
                self._audit("approval.expired", "expired", state.session, state.run_id,
                            self._approval_detail(live))
            live = None
        if live is not None and live["proposal_hash"] != proposal_hash:
            return self._revoke(state, step, row, live)
        if live is None:
            approval_id = str(uuid7())
            expires = utc_iso(self._clock() + timedelta(seconds=self._ttl_s))
            with transaction(self._conn):
                self._conn.execute(
                    "INSERT INTO approvals (approval_id, run_id, step_key, scope, proposal_hash, "
                    "status, created_at, expires_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                    (approval_id, state.run_id, step.id, proposal.scope, proposal_hash, now,
                     expires),
                )
                self._set_step(row, "awaiting_approval", started=True)
                self._set_run(state.run_id, "awaiting_approval")
                self._audit("approval.requested", "pending", state.session, state.run_id,
                            f"step={step.id};hash={proposal_hash}")
            live = self._live_approval(state.run_id, step.id)
            assert live is not None
        if live["status"] == "pending":
            waiting = RunOutcome(
                state.run_id, "awaiting_approval",
                # Never the hash or a part of it: the code is shown only next to the content,
                # inside the interactive prompt (review 8.2).
                message=f"step {step.id!r} is waiting for a human approval (approval "
                f"{live['approval_id']}, {live['status']}, expires {live['expires_at']} UTC); "
                f"run `skill resume {state.run_id}` in an interactive terminal",
            )
            if not self._terminal.is_interactive():
                self._set_awaiting(state, row)
                return waiting
            decision = decide(
                self._terminal,
                render_for_terminal(proposal, proposal_hash, live["expires_at"]),
                proposal_hash,
            )
            decided = utc_iso(self._clock())
            if decision == "undecided":
                self._set_awaiting(state, row)
                return waiting
            identity = self._terminal.identity()
            if decision == "rejected":
                with transaction(self._conn):
                    self._set_approval(live["approval_id"], "rejected", decided_at=decided,
                                       identity=identity)
                    self._audit("approval.rejected", "rejected", state.session, state.run_id,
                                self._approval_detail(live))
                    self._set_step(row, "failed", error_code="approval_rejected", finished=True)
                    self._finish_run_locked(state.run_id, state.session, "cancelled",
                                            "approval_rejected")
                return RunOutcome(state.run_id, "cancelled", message="the approval was rejected")
            if decided >= live["expires_at"]:
                # The prompt blocks until the person answers; an answer after the expiry is
                # never recorded as `granted` (review 8.8). A new approval is asked on resume.
                with transaction(self._conn):
                    self._set_approval(live["approval_id"], "expired", decided_at=decided)
                    self._audit("approval.expired", "expired", state.session, state.run_id,
                                self._approval_detail(live))
                    self._set_step(row, "awaiting_approval")
                    self._set_run(state.run_id, "awaiting_approval")
                return RunOutcome(
                    state.run_id, "awaiting_approval",
                    message=f"the approval of step {step.id!r} expired before the answer; "
                    f"nothing was applied. Run `skill resume {state.run_id}` to be asked again",
                )
            with transaction(self._conn):
                self._set_approval(live["approval_id"], "granted", decided_at=decided,
                                   identity=identity)
                self._audit("approval.granted", "granted", state.session, state.run_id,
                            self._approval_detail(live))
        return await self._apply(state, step, live["approval_id"], proposed)

    async def _apply(
        self, state: _Run, step: ApprovalStep, approval_id: str,
        proposed: _Proposed,
    ) -> RunOutcome | None:
        proposal = proposed.proposal
        assert proposal is not None
        row = self._latest_steps(state.run_id)[step.id]
        approval = self._conn.execute(
            "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
        ).fetchone()
        if approval is None:
            raise InvalidInput(f"approval {approval_id} does not exist")
        own = approval["run_id"] == state.run_id and approval["step_key"] == step.id
        # What the proposal was made from must still be what is stored: a change while the
        # person was reading revokes the approval. No second `prepare`: only the source is read.
        altered = self._output(state, step.of) != proposed.source
        if own and approval["status"] == "granted" and (
            altered or proposal.sha256 != approval["proposal_hash"]
        ):
            return self._revoke(state, step, row, approval)
        effect = self._effects[step.effect]
        effect_context = self._effect_context(state, step)
        now = utc_iso(self._clock())
        with transaction(self._conn):
            consumed = self._conn.execute(
                "UPDATE approvals SET status = 'consumed', consumed_at = ? WHERE approval_id = ? "
                "AND status = 'granted' AND proposal_hash = ? AND expires_at > ?",
                (now, approval_id, proposal.sha256, now),
            ).rowcount
            if consumed != 1:
                self._audit("approval.denied", "denied", state.session, state.run_id,
                            self._approval_detail(approval))
                if approval["status"] == "granted" and approval["expires_at"] <= now:
                    self._set_approval(approval_id, "expired")
                    self._audit("approval.expired", "expired", state.session, state.run_id,
                                self._approval_detail(approval))
            else:
                # One transaction: the approval is used, the step is `applying` with what will
                # be applied (its SHA-256, for `reconcile`) and the run is `running`, so that a
                # process that dies from here on is always found by `recover_runs` (review 8.1).
                content = proposal.content.encode("utf-8")
                self._conn.execute(
                    "UPDATE skill_steps SET status = 'applying', prepared_at = ?, effect_ref = ?, "
                    "output_sha256 = ?, output_bytes = ? WHERE step_id = ?",
                    (now, proposed.effect_ref, hashlib.sha256(content).hexdigest(), len(content),
                     row["step_id"]),
                )
                self._set_run(state.run_id, "running")
                self._audit("approval.consumed", "consumed", state.session, state.run_id,
                            self._approval_detail(approval))
        if consumed != 1:
            if own and row["status"] not in ("completed", "failed"):
                # This run's own approval could not be used (expired): ask again on resume.
                self._set_awaiting(state, row)
            return RunOutcome(
                state.run_id, self._require_run(state.run_id)["status"],
                message="the approval could not be used (already used, expired or for another "
                "proposal); nothing was applied",
            )
        try:
            effect.apply(effect_context, proposal)
        except Exception as exc:  # the effect failed: never retried by itself
            with transaction(self._conn):
                self._set_step(row, "failed", error_code=f"effect_{type(exc).__name__}",
                               finished=True)
                self._finish_run_locked(state.run_id, state.session, "failed", "effect_failed")
            return RunOutcome(state.run_id, "failed", message=f"the effect failed: {exc}")
        self._complete(state, step.id, row, proposal.content)
        return None

    def _reconcile(self, state: _Run, key: str, row: sqlite3.Row) -> None:
        """An approval step interrupted after its approval was consumed (review 8.1).

        The effect says whether the content approved (by its SHA-256) is in place:
        - `applied`: the step completes without applying anything again;
        - `absent`: nothing happened; a new attempt of the step asks a person for a new approval;
        - `conflict` (or anything unknown): the step stays `uncertain` and a person must look;
          the resume is refused with an error (exit code 1) and nothing changes.
        """
        step = state.skill.step(key)
        assert isinstance(step, ApprovalStep)
        effect = self._effects[step.effect]
        context = self._effect_context(state, step)
        expected = row["output_sha256"]
        result = (effect.reconcile(context, row["effect_ref"], expected)
                  if expected is not None else "conflict")
        detail = f"step={key};attempt={row['attempt']}"
        if result == "applied":
            stored = None
            if state.provider.synthetic_content:
                proposed = self._propose(state, step)
                if proposed.proposal is not None and hashlib.sha256(
                    proposed.proposal.content.encode("utf-8")
                ).hexdigest() == expected:
                    stored = proposed.proposal.content
            with transaction(self._conn):
                self._conn.execute(
                    "UPDATE skill_steps SET status = 'completed', output_text = ?, "
                    "error_code = NULL, finished_at = ? WHERE step_id = ?",
                    (stored, utc_iso(self._clock()), row["step_id"]),
                )
                if stored is not None:
                    state.outputs[key] = stored
                self._audit("skill.step.reconciled", "applied", state.session, state.run_id,
                            detail)
            return
        if result == "absent":
            if row["attempt"] >= MAX_ATTEMPTS:
                self._limit(state.session, state.run_id, key, "attempts")
                raise InvalidInput(
                    f"step {key!r} already had {MAX_ATTEMPTS} attempts; cancel the run with "
                    f"`skill cancel {state.run_id}`"
                )
            with transaction(self._conn):
                self._insert_step(state.run_id, key, row["position"], step.kind,
                                  row["attempt"] + 1)
                self._audit("skill.step.reconciled", "absent", state.session, state.run_id,
                            detail)
            return
        with transaction(self._conn):
            self._audit("skill.step.reconciled", "conflict", state.session, state.run_id, detail)
        raise InvalidInput(
            f"step {key!r} of run {state.run_id} was interrupted while applying its effect and "
            "the effect cannot tell whether it is in place (conflict): a person must check the "
            f"target, then `skill cancel {state.run_id}`; nothing was applied again"
        )

    def _revoke(
        self, state: _Run, step: ApprovalStep, row: sqlite3.Row, approval: sqlite3.Row
    ) -> RunOutcome:
        with transaction(self._conn):
            self._set_approval(approval["approval_id"], "revoked",
                               decided_at=utc_iso(self._clock()))
            self._audit("approval.revoked", "altered", state.session, state.run_id,
                        self._approval_detail(approval))
            self._audit("approval.denied", "denied", state.session, state.run_id,
                        self._approval_detail(approval))
            self._set_step(row, "failed", error_code="approval_altered", finished=True)
            self._finish_run_locked(state.run_id, state.session, "failed", "approval_altered")
        return RunOutcome(state.run_id, "failed",
                          message="the proposal changed after it was approved; nothing applied")

    def _set_awaiting(self, state: _Run, row: sqlite3.Row) -> None:
        with transaction(self._conn):
            self._set_step(row, "awaiting_approval")
            self._set_run(state.run_id, "awaiting_approval")

    def _live_approval(self, run_id: str, step_key: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM approvals WHERE run_id = ? AND step_key = ? AND status IN "
            "('pending', 'granted')",
            (run_id, step_key),
        ).fetchone()

    def _set_approval(self, approval_id: str, status: str, *, decided_at: str | None = None,
                      identity: str | None = None) -> None:
        self._conn.execute(
            "UPDATE approvals SET status = ?, decided_at = COALESCE(?, decided_at), "
            "identity = COALESCE(?, identity), channel = CASE WHEN ? IS NULL THEN channel "
            "ELSE 'tty' END WHERE approval_id = ?",
            (status, decided_at, identity, identity, approval_id),
        )

    @staticmethod
    def _approval_detail(approval: sqlite3.Row) -> str:
        return (f"approval={approval['approval_id']};step={approval['step_key']};"
                f"hash={approval['proposal_hash']}")

    def _effect_context(self, state: _Run, step: ApprovalStep) -> EffectContext:
        return EffectContext(str(state.session.session_id), state.run_id, step.id,
                             state.skill.name)

    # -- values and outputs ---------------------------------------------------------------------

    def _output(self, state: _Run, step_key: str) -> str:
        """A completed step's output: the stored one if any, else this invocation's."""
        row = self._latest_steps(state.run_id).get(step_key)
        if row is not None and row["status"] == "completed" and row["output_text"] is not None:
            return row["output_text"]
        if step_key in state.outputs:
            return state.outputs[step_key]
        raise InvalidInput(f"the output of step {step_key!r} is not available")

    def _values(self, state: _Run, step: LlmStep) -> dict[str, Any]:
        references, _ = find_references(state.skill.templates[step.template])
        values: dict[str, Any] = {}
        for reference in references:
            key = reference_key(reference)
            if reference.input is not None:
                values[key] = state.inputs.get(reference.input, "")
            elif reference.field is not None:
                fields = parse_fields(self._output(state, reference.step))
                value = fields.get(reference.field)
                if value is None:
                    values[key] = ""
                elif isinstance(value, (str, list)):
                    values[key] = value
                else:
                    values[key] = json.dumps(value)
            else:
                values[key] = self._output(state, reference.step)
        return values

    def _complete(self, state: _Run, step_key: str, row: sqlite3.Row, output: str) -> None:
        data = output.encode("utf-8")
        stored = output if state.provider.synthetic_content else None
        state.outputs[step_key] = output
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE skill_steps SET status = 'completed', output_sha256 = ?, "
                "output_bytes = ?, output_text = ?, error_code = NULL, finished_at = ? "
                "WHERE step_id = ?",
                (hashlib.sha256(data).hexdigest(), len(data), stored, utc_iso(self._clock()),
                 row["step_id"]),
            )
            self._audit("skill.step", "completed", state.session, state.run_id,
                        f"step={step_key};attempt={row['attempt']};bytes={len(data)}")

    # -- checks before running ------------------------------------------------------------------

    @staticmethod
    def _check_inputs(skill: Skill, inputs: Mapping[str, str]) -> str:
        declared = skill.workflow.inputs
        for name in inputs:
            if name not in declared:
                raise InvalidInput(f"skill {skill.name!r} does not declare an input {name!r}")
        for name, spec in declared.items():
            if spec.required and name not in inputs:
                raise InvalidInput(f"input {name!r} is required")
        total = 0
        for name, value in inputs.items():
            size = len(value.encode("utf-8"))
            if size > MAX_INPUT_BYTES:
                raise InvalidInput(f"input {name!r} is larger than {MAX_INPUT_BYTES} bytes")
            total += size
        if total > MAX_INPUTS_TOTAL_BYTES:
            raise InvalidInput(f"the inputs are larger than {MAX_INPUTS_TOTAL_BYTES} bytes")
        return inputs_manifest(inputs)

    @staticmethod
    def _check_memory(skill: Skill, session: Session) -> None:
        needs = any(isinstance(s, LlmStep) and s.memory == "project" for s in skill.workflow.steps)
        if needs and session.project_id is None:
            raise InvalidInput(
                f"skill {skill.name!r} uses the project memory and session {session.session_id} "
                "has no project; create a session with --project"
            )

    def _load_same_skill(self, row: sqlite3.Row) -> Skill:
        try:
            skill = load_skill(self._root, row["skill_name"], self._effects.keys())
        except HarnessError as exc:
            raise InvalidInput(
                f"skill {row['skill_name']!r} cannot be loaded any more ({exc}); the run was not "
                f"changed"
            ) from None
        if skill.sha256 != row["skill_sha256"]:
            raise InvalidInput(
                f"skill {skill.name!r} changed on disk: the run used {row['skill_sha256']} and "
                f"the skill is now {skill.sha256}; the run was not changed (cancel it with "
                f"`skill cancel {row['run_id']}`)"
            )
        return skill

    def _check_resume_inputs(
        self, row: sqlite3.Row, skill: Skill, latest: dict[str, sqlite3.Row],
        inputs: Mapping[str, str],
    ) -> None:
        manifest = json.loads(row["inputs_manifest"])
        for name, value in inputs.items():
            if name not in manifest:
                raise InvalidInput(f"input {name!r} was not part of run {row['run_id']}")
            if hashlib.sha256(value.encode("utf-8")).hexdigest() != manifest[name]["sha256"]:
                raise InvalidInput(
                    f"input {name!r} is not the one the run started with (different SHA-256); "
                    "nothing changed"
                )
        needed: set[str] = set()
        for step in skill.workflow.steps:
            if latest[step.id]["status"] == "completed" or not isinstance(step, LlmStep):
                continue
            references, _ = find_references(skill.templates[step.template])
            needed.update(r.input for r in references if r.input is not None)
        for name in sorted(needed & set(manifest)):
            if name not in inputs:
                raise InvalidInput(
                    f"input {name!r} must be given again with --input or --input-file to resume "
                    "(inputs are never stored)"
                )

    def _missing_outputs(self, skill: Skill, latest: dict[str, sqlite3.Row]) -> list[str]:
        needed: set[str] = set()
        for step in skill.workflow.steps:
            if latest[step.id]["status"] == "completed":
                continue
            if isinstance(step, LlmStep):
                references, _ = find_references(skill.templates[step.template])
                needed.update(r.step for r in references if r.step is not None)
            else:
                needed.add(step.of)
        return sorted(
            key for key in needed
            if latest[key]["status"] == "completed" and latest[key]["output_text"] is None
        )

    # -- storage helpers ------------------------------------------------------------------------

    def _lock(self, session: Session) -> SessionLock:
        lock = SessionLock(self._data_dir, session.session_id)
        if not lock.acquire():
            raise SessionBusy(f"session {session.session_id} is busy in another process")
        return lock

    def _require_run(self, run_id: str) -> sqlite3.Row:
        row = self._conn.execute("SELECT * FROM skill_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise InvalidInput(f"run {run_id} does not exist")
        return row

    def _latest_steps(self, run_id: str) -> dict[str, sqlite3.Row]:
        rows = self._conn.execute(
            "SELECT * FROM skill_steps WHERE run_id = ? ORDER BY position, attempt", (run_id,)
        ).fetchall()
        return {row["step_key"]: row for row in rows}  # the last attempt wins

    def _insert_step(self, run_id: str, key: str, position: int, kind: str, attempt: int) -> None:
        self._conn.execute(
            "INSERT INTO skill_steps (step_id, run_id, step_key, position, kind, attempt, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
            (str(uuid7()), run_id, key, position, kind, attempt),
        )

    def _set_step(self, row: sqlite3.Row, status: str, *, error_code: str | None = None,
                  started: bool = False, finished: bool = False) -> None:
        now = utc_iso(self._clock())
        self._conn.execute(
            "UPDATE skill_steps SET status = ?, error_code = COALESCE(?, error_code), "
            "started_at = CASE WHEN ? THEN COALESCE(started_at, ?) ELSE started_at END, "
            "finished_at = CASE WHEN ? THEN ? ELSE finished_at END WHERE step_id = ?",
            (status, error_code, started, now, finished, now, row["step_id"]),
        )

    def _set_run(self, run_id: str, status: str, *, error_code: str | None = None) -> None:
        self._conn.execute(
            "UPDATE skill_runs SET status = ?, error_code = COALESCE(?, error_code), "
            "updated_at = ? WHERE run_id = ?",
            (status, error_code, utc_iso(self._clock()), run_id),
        )

    def _finish_run_locked(self, run_id: str, session: Session, status: str, code: str) -> None:
        now = utc_iso(self._clock())
        self._conn.execute(
            "UPDATE skill_runs SET status = ?, error_code = ?, updated_at = ?, finished_at = ? "
            "WHERE run_id = ?",
            (status, code, now, now, run_id),
        )
        self._audit("skill.run", status, session, run_id, f"error={code}")

    def _finish_run(self, run_id: str, session: Session, status: str, code: str) -> None:
        with transaction(self._conn):
            self._finish_run_locked(run_id, session, status, code)

    def _stop(self, state: _Run, step_key: str, row: sqlite3.Row, code: str, *,
              limit: str) -> RunOutcome:
        with transaction(self._conn):
            self._set_step(row, "failed", error_code=code, finished=True)
            self._audit("skill.limit", limit, state.session, state.run_id,
                        f"step={step_key};limit={limit}")
            self._finish_run_locked(state.run_id, state.session, "failed", code)
        return RunOutcome(state.run_id, "failed", message=f"step {step_key!r} stopped: {code}")

    def _limit(self, session: Session, run_id: str, step_key: str, limit: str) -> None:
        with transaction(self._conn):
            self._audit("skill.limit", limit, session, run_id, f"step={step_key};limit={limit}")

    def _audit(self, event: str, outcome: str, session: Session, run_id: str,
               detail: str | None) -> None:
        repo.insert_audit(self._conn, event_type=event, outcome=outcome, actor="cli",
                          session_id=session.session_id, run_id=run_id, detail=detail)


def recover_runs(conn: sqlite3.Connection, data_dir: Path) -> list[str]:
    """Runs left by a dead process (D10). A run whose session is locked is alive.

    A run is looked at when it is `running` or when any of its steps is `running` or `applying`,
    whatever the run's own state says (review 8.1, 2026-11-24): an `applying` step always
    becomes `uncertain`, so that its effect is reconciled and never simply applied again.
    """
    recovered = []
    rows = conn.execute(
        "SELECT run_id, session_id FROM skill_runs r WHERE r.status NOT IN "
        "('completed', 'failed', 'cancelled') AND (r.status = 'running' OR EXISTS ("
        "SELECT 1 FROM skill_steps s WHERE s.run_id = r.run_id AND s.status IN "
        "('running', 'applying')))"
    ).fetchall()
    for run in rows:
        lock = SessionLock(data_dir, UUID(run["session_id"]))
        if not lock.acquire():
            continue
        try:
            with transaction(conn):
                _recover_run(conn, run["run_id"], run["session_id"])
            recovered.append(run["run_id"])
        finally:
            lock.release()
    return recovered


def _recover_run(conn: sqlite3.Connection, run_id: str, session_id: str) -> None:
    """Mark what a dead process left half done; the caller holds the lock and a transaction."""
    steps = conn.execute(
        "SELECT * FROM skill_steps WHERE run_id = ? AND status IN ('running', 'applying')",
        (run_id,),
    ).fetchall()
    uncertain = False
    for step in steps:
        if step["kind"] == "validate":
            new_status = "pending"
        else:
            new_status, uncertain = "uncertain", True
        request_id = step["request_id"]
        if request_id is None and step["kind"] == "llm":
            found = conn.execute(
                "SELECT request_id FROM requests WHERE session_id = ? AND "
                "started_at >= ? ORDER BY started_at DESC LIMIT 1",
                (session_id, step["started_at"] or ""),
            ).fetchone()
            request_id = found["request_id"] if found else None
        conn.execute(
            "UPDATE skill_steps SET status = ?, request_id = ?, error_code = "
            "CASE WHEN ? = 'uncertain' THEN 'interrupted' ELSE error_code END "
            "WHERE step_id = ?",
            (new_status, request_id, new_status, step["step_id"]),
        )
    status = "uncertain" if uncertain else "pending"
    conn.execute(
        "UPDATE skill_runs SET status = ?, error_code = CASE WHEN ? = 'uncertain' "
        "THEN 'interrupted' ELSE error_code END WHERE run_id = ?",
        (status, status, run_id),
    )
    repo.insert_audit(conn, event_type="skill.run", outcome=status, actor="recovery",
                      session_id=UUID(session_id), run_id=run_id, detail="recovered")
