"""`/agent`: a question, a plan, its results back to the model, and again (code-mode A3).

The loop, turn by turn (a turn is exactly one question to the provider):

1. Turn 1 is a `/plan` question whose harness block says it is a loop (`vuelta 1 de N`).
2. The reply is shown. If the question did not complete whole (uncertain, failed, timed out,
   truncated), the loop stops: it is never read, never resent.
3. No plan: it is the final answer; the loop ends.
4. A plan the reader refuses: its reason is shown and, ONCE per loop, sent back so the model
   can correct it (a turn like any other); a second refusal stops the loop.
5. A valid plan is approved (by the rule `auto_read`, or by the person in the box, per turn)
   and run exactly as `/plan` runs it. Rejected, undecided, expired, interrupted, or stopped
   by the harness itself (the list changed, the plan was altered, its approval cannot be used,
   another process holds it): the loop stops and nothing more is sent. A step that fails
   (denied by the gateway, a tool error, a failed call, its own timeout or the plan's
   deadline) is a result like any other: the failure goes back as data and the model decides.
6. The results go back as data in turn k + 1 (`loop.results_turn`), shown first exactly as
   they are sent. After turn N (`HARNESS_LOOP_MAX_TURNS`), a plan's results (or the reason a
   plan was refused) go in ONE closing turn with no catalogue and no nonce, which asks for a
   summary; its reply is never read for a plan. So a loop makes at most N + 1 questions, and
   each one is a row of `loop_turns` with its turn number and the request it made.
7. Ctrl+C stops the question or the step in course and the loop: nothing more is sent.

Nothing leaves the machine unless the person typed `/agent` and the provider is named in
`HARNESS_LOOP_PROVIDERS` (checked by the caller, before anything is recorded). A provider
whose content is not synthetic gets, once per loop and before the first result is sent, a
harness line that says where the results go. What a loop stores: its row (`loop_runs`) and
one row per turn with the request, the kind of turn, the plan whose results it carried, and
the size and keyed hash of the harness's text of that turn (for turn 1, its block of
instructions; for the others, the whole text sent). Never the text: the question history
keeps only a short label of each turn after the first.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid7

from harness.core.contracts import LLMResponse, RequestStatus
from harness.core.errors import HarnessError
from harness.core.service import SessionService
from harness.mcp import plan_flow
from harness.mcp.audit import args_key
from harness.mcp.loop import (
    CORRECTIONS,
    LoopSettings,
    TurnTooLarge,
    closing_turn,
    correction_turn,
    results_block,
    results_turn,
)
from harness.mcp.plan import NoPlan, Refusal, read_plan_reply
from harness.mcp.plan_flow import PlanRequest, PlanSetting, PlanView
from harness.mcp.plan_prompt import build_catalogue, loop_instructions
from harness.memory.context import new_nonce
from harness.skills.approvals import Terminal
from harness.storage import repositories as repo
from harness.storage.database import transaction
from harness.storage.locks import NamedLock
from harness.text.safe_text import safe_line

AGENT_COMMAND = "/agent"
# A plan that ended so is the harness stopping itself, not something the model can act on:
# the loop stops and nothing more is sent.
STOPPING_CODES = frozenset({"interrupted", "list_changed", "plan_altered", "approval_not_usable",
                            "plan_in_use", "config_error", "abandoned"})


@dataclass(frozen=True)
class LoopOutcome:
    loop_id: str
    status: str  # completed, stopped, interrupted
    reason: str  # a word of migration 010's closed list (loop_runs)
    turns: int  # questions sent

    @property
    def ok(self) -> bool:
        return self.status == "completed"


@dataclass(frozen=True)
class _Turn:
    number: int
    kind: str  # question, results, correction, closing
    nonce: str | None  # None: the closing turn, never read for a plan
    plan_id: str | None = None  # the plan whose results this turn carries


class _Stop(Exception):  # noqa: N818 - a way out of the loop, not an error
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status, self.reason = status, reason


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _audit(conn: sqlite3.Connection, event: str, outcome: str, session_id: UUID,
           detail: str) -> None:
    repo.insert_audit(conn, event_type=event, outcome=outcome, actor="cli",
                      session_id=session_id, detail=detail)


def recover_loops(conn: sqlite3.Connection, data_dir: Path,
                  clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> int:
    """A loop left `running` by a process that is gone (its lock is free) becomes
    `interrupted` (`abandoned`): it is never resumed. A request it had in flight is the
    service's to recover (uncertain, never resent)."""
    running = [row[0] for row in conn.execute(
        "SELECT loop_id FROM loop_runs WHERE status = 'running'").fetchall()]
    recovered = 0
    for loop_id in running:
        lock = NamedLock(data_dir, f"loop-{loop_id}")
        if not lock.acquire():
            continue  # its process still runs it
        try:
            with transaction(conn):
                changed = conn.execute(
                    "UPDATE loop_runs SET status = 'interrupted', stop_reason = 'abandoned', "
                    "finished_at = ? WHERE loop_id = ? AND status = 'running'",
                    (_iso(clock()), loop_id)).rowcount
                if changed:
                    (session_id,) = conn.execute(
                        "SELECT session_id FROM loop_runs WHERE loop_id = ?",
                        (loop_id,)).fetchone()
                    _audit(conn, "loop.finished", "abandoned", UUID(session_id),
                           f"loop={loop_id};status=interrupted")
                recovered += changed
        finally:
            lock.release()
    return recovered


class _Record:
    """The loop's rows, written as it goes."""

    def __init__(self, conn: sqlite3.Connection, data_dir: Path, loop_id: str,
                 session_id: UUID, provider: str, max_turns: int,
                 clock: Callable[[], datetime]) -> None:
        self.conn, self.loop_id, self.session_id, self.clock = conn, loop_id, session_id, clock
        self.key = args_key(data_dir)
        with transaction(conn):
            conn.execute(
                "INSERT INTO loop_runs (loop_id, session_id, provider, max_turns, turns, "
                "corrections, status, created_at) VALUES (?, ?, ?, ?, 0, 0, 'running', ?)",
                (loop_id, str(session_id), provider[:64], max_turns, _iso(clock())))
            _audit(conn, "loop.started", "running", session_id,
                   f"loop={loop_id};max_turns={max_turns}")

    def link(self, turn: _Turn, text: str) -> Callable[[sqlite3.Connection, UUID], None]:
        """What the service calls in the very transaction that records the request: the
        turn's row, with the size and keyed hash of the text, never the text."""
        data = text.encode("utf-8")
        digest = hmac.new(self.key, data, hashlib.sha256).hexdigest()

        def link(conn: sqlite3.Connection, request_id: UUID) -> None:
            conn.execute(
                "INSERT INTO loop_turns (loop_id, turn, request_id, kind, plan_id, sent_bytes, "
                "sent_hmac, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (self.loop_id, turn.number, str(request_id), turn.kind, turn.plan_id,
                 len(data), digest, _iso(self.clock())))
            conn.execute("UPDATE loop_runs SET turns = ? WHERE loop_id = ?",
                         (turn.number, self.loop_id))

        return link

    def correction(self) -> None:
        with transaction(self.conn):
            self.conn.execute("UPDATE loop_runs SET corrections = corrections + 1 "
                              "WHERE loop_id = ?", (self.loop_id,))

    def finish(self, status: str, reason: str) -> int:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE loop_runs SET status = ?, stop_reason = ?, finished_at = ? "
                "WHERE loop_id = ? AND status = 'running'",
                (status, reason, _iso(self.clock()), self.loop_id))
            _audit(self.conn, "loop.finished", reason, self.session_id,
                   f"loop={self.loop_id};status={status}")
            (turns,) = self.conn.execute("SELECT turns FROM loop_runs WHERE loop_id = ?",
                                         (self.loop_id,)).fetchone()
        return int(turns)


async def run_loop(request: PlanRequest, *, service: SessionService, conn, view: PlanView,
                   terminal: Terminal, setting: PlanSetting, loop: LoopSettings,
                   provider_name: str, synthetic: bool,
                   state: Callable[[str], None] = lambda _: None,
                   monotonic: Callable[[], float] = time.monotonic) -> LoopOutcome:
    """The whole of one `/agent` (see the module docstring). `state` gets what the side
    panel shows whenever it changes: the turn and its phase with the loop's elapsed seconds
    (`turn 2 of 5: running step 1 of 2 (3 s)`), and "-" when the loop ends."""
    recover_loops(conn, setting.data_dir, setting.clock)
    loop_id = str(uuid7())
    lock = NamedLock(setting.data_dir, f"loop-{loop_id}")
    if not lock.acquire():  # never: the id is new; fail closed rather than run unlocked
        raise HarnessError("the loop's lock is held elsewhere; nothing was sent")
    try:
        record = _Record(conn, setting.data_dir, loop_id, request.session_id, provider_name,
                         loop.max_turns, setting.clock)
        try:
            await _Loop(request, service, conn, view, terminal, setting, loop, provider_name,
                        synthetic, state, record, monotonic).run()
        except _Stop as stop:
            status, reason = stop.status, stop.reason
        except Exception:
            record.finish("stopped", "error")
            state("-")
            raise
        except BaseException:  # Ctrl+C during a question: nothing more is sent
            record.finish("interrupted", "interrupted")
            state("-")
            raise
        turns = record.finish(status, reason)
        state("-")
        view.say(f"loop {loop_id}: {status} ({reason}) after {turns} send(s) to "
                 f"{provider_name}")
        return LoopOutcome(loop_id, status, reason, turns)
    finally:
        lock.release()


def _counter(turn: _Turn, loop: LoopSettings) -> str:
    if turn.kind == "closing":
        return f"closing turn ({turn.number} of at most {loop.max_turns + 1} sends)"
    return f"turn {turn.number} of {loop.max_turns}"


class _Loop:
    def __init__(self, request: PlanRequest, service: SessionService, conn, view: PlanView,
                 terminal: Terminal, setting: PlanSetting, loop: LoopSettings,
                 provider_name: str, synthetic: bool, state: Callable[[str], None],
                 record: _Record, monotonic: Callable[[], float] = time.monotonic) -> None:
        self.request, self.service, self.conn, self.view = request, service, conn, view
        self.terminal, self.loop = terminal, loop
        self.monotonic, self.started = monotonic, monotonic()
        self.turn: _Turn | None = None
        # Each step of a plan says it starts (from the executor's thread, through the
        # conversation's loop): the panel shows `running step k of n`.
        self.setting = dataclasses.replace(setting, progress=self._step)
        self.provider_name, self.state, self.record = provider_name, state, record
        self.warned = synthetic  # a synthetic provider's content never leaves the machine
        self.corrections = 0
        self.config = setting.load_config()
        self.catalogue = build_catalogue(self.config)

    def _phase(self, turn: _Turn, what: str) -> None:
        """The side panel's line: the turn, what is happening, and the loop's seconds."""
        self.turn = turn
        elapsed = int(self.monotonic() - self.started)
        self.state(f"{_counter(turn, self.loop)}: {what} ({elapsed} s)")

    def _step(self, position: int, total: int) -> None:
        if self.turn is not None:
            self._phase(self.turn, f"running step {position} of {total}")

    @property
    def tag(self) -> str:
        return f"loop {self.record.loop_id}"

    async def run(self) -> None:
        turn = _Turn(1, "question", new_nonce())
        assert turn.nonce is not None
        instructions = loop_instructions(turn.nonce, self.catalogue, turns=self.loop.max_turns)
        self.view.say(f"{self.tag}: {_counter(turn, self.loop)}: the question, with the "
                      f"catalogue of {len(self.catalogue.lines)} read tool(s); at most "
                      f"{self.loop.max_turns} turns and one closing turn "
                      "(HARNESS_LOOP_MAX_TURNS). Ctrl+C stops the loop")
        text = instructions
        while True:
            response = await self._ask(turn, text)
            nxt = await self._next(turn, response)
            text = self._compose(nxt)
            if not self.warned:
                self.view.say(f"{self.tag}: from here on, what the reads return goes to "
                              f"{self.provider_name}, a provider outside this machine; each "
                              "turn is shown here exactly as it is sent, before it goes")
                self.warned = True
            self.view.result(f"{self.tag}: {_counter(nxt[0], self.loop)}: sending "
                             f"{len(text)} characters to {self.provider_name}; exactly this "
                             "text, nothing else:", text)
            turn = nxt[0]

    async def _ask(self, turn: _Turn, text: str) -> LLMResponse:
        counter = _counter(turn, self.loop)
        self._phase(turn, f"sending {len(text)} characters and waiting for the reply")
        request = self.request
        async with self.view.waiting():
            if turn.kind == "question":
                return await self.service.ask_plan(
                    request.session_id, request.provider, request.question, text,
                    request.context, attachment=request.attachment,
                    stored_text=f"{AGENT_COMMAND} {request.question}",
                    link=self.record.link(turn, text))
            return await self.service.ask_loop_turn(
                request.session_id, request.provider, text,
                stored_text=f"{AGENT_COMMAND} {self.tag}: {counter} ({turn.kind})",
                link=self.record.link(turn, text))

    async def _next(self, turn: _Turn, response: LLMResponse):
        """What the reply leads to: the next turn and what it carries, or a `_Stop`."""
        view = self.view
        for warning in response.warnings:
            view.say(f"warning: {warning}")
        if response.status is not RequestStatus.COMPLETED or response.text is None:
            detail = safe_line(response.detail or "").text
            view.say(f"error: request {response.request_id} ended as {response.status}: "
                     f"{detail}; it is never read or resent, and the loop stops")
            raise _Stop("stopped", "reply_not_completed")
        view.reply(response.text)
        if response.truncated:
            view.say("warning: the reply was read only in part; it is never read for a plan, "
                     "and the loop stops")
            raise _Stop("stopped", "reply_truncated")
        if turn.kind == "closing":
            view.say(f"{self.tag}: the closing turn's reply is the summary; it is never read "
                     "for a plan")
            raise _Stop("completed", "cap")
        assert turn.nonce is not None
        reading = read_plan_reply(response, nonce=turn.nonce, config=self.config)
        last = turn.number >= self.loop.max_turns
        if isinstance(reading, NoPlan):
            view.say(f"{self.tag}: the reply holds no plan; it is the answer")
            raise _Stop("completed", "answer")
        if isinstance(reading, Refusal):
            step = f" (step {reading.step})" if reading.step else ""
            view.say(f"warning: plan refused: {reading.reason}{step}: {reading.detail}; "
                     "nothing was run")
            if last:
                return _Turn(turn.number + 1, "closing", None), None, None, reading
            if self.corrections >= CORRECTIONS:
                view.say(f"{self.tag}: a second refused plan stops the loop; nothing more is "
                         "sent")
                raise _Stop("stopped", "refused")
            self.corrections += 1
            self.record.correction()
            view.say(f"{self.tag}: the reason goes back once so the model can correct its "
                     "plan; another refusal stops the loop")
            return _Turn(turn.number + 1, "correction", new_nonce()), None, None, reading
        self._phase(turn, f"plan of {len(reading.steps)} step(s): approval")
        outcome = await plan_flow.approve_and_run(
            reading, self.request, response.request_id, self.config, self.conn, view,
            self.terminal, self.setting)
        if outcome.kind == "interrupted":
            raise _Stop("interrupted", "interrupted")
        if outcome.kind != "ran" or outcome.report is None:
            view.say(f"{self.tag}: the plan was not approved; the loop stops and nothing more "
                     "is sent")
            raise _Stop("stopped", "not_approved")
        report = outcome.report
        if report.status == "interrupted":
            raise _Stop("interrupted", "interrupted")
        if report.status == "not_run" or report.error_code in STOPPING_CODES:
            view.say(f"{self.tag}: the harness stopped the plan "
                     f"({report.error_code or report.status}); the loop stops and nothing "
                     "more is sent")
            raise _Stop("stopped", "plan_stopped")
        kind = "closing" if last else "results"
        nonce = None if last else new_nonce()
        return _Turn(turn.number + 1, kind, nonce, report.plan_id), report, reading, None

    def _compose(self, nxt) -> str:
        turn, report, plan, refusal = nxt
        try:
            if turn.kind != "closing":
                self.config = self.setting.load_config()  # the catalogue as the list is now
                self.catalogue = build_catalogue(self.config)
            if turn.kind == "correction":
                return correction_turn(refusal, turn=turn.number, turns=self.loop.max_turns,
                                       nonce=turn.nonce, catalogue=self.catalogue)
            block = results_block(report, plan) if report is not None else None
            marker = new_nonce()
            while block is not None and any(marker in line for line in block.lines):
                marker = new_nonce()  # 64 random bits: never, in practice
            if turn.kind == "closing":
                return closing_turn(turns=self.loop.max_turns, marker=marker, block=block,
                                    refusal=refusal)
            return results_turn(block, turn=turn.number, turns=self.loop.max_turns,
                                marker=marker, nonce=turn.nonce, catalogue=self.catalogue)
        except TurnTooLarge as exc:
            self.view.say(f"error: {exc}")
            raise _Stop("stopped", "turn_too_large") from None


def last_loop(conn: sqlite3.Connection, session_id: UUID) -> str:
    """What `/status` and the side panel say of the session's last loop: harness words only."""
    row = conn.execute(
        "SELECT status, stop_reason, turns, max_turns, created_at, finished_at FROM loop_runs "
        "WHERE session_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (str(session_id),)).fetchone()
    if row is None:
        return "-"
    status, reason, turns, cap, created, finished = row
    if status == "running":
        return f"running, turn {turns} of {cap}"
    try:
        took = (datetime.fromisoformat(finished) - datetime.fromisoformat(created))
        seconds = f", done in {max(0, int(took.total_seconds()))} s"
    except (TypeError, ValueError):
        seconds = ""
    return f"{status} ({reason}), {turns} send(s){seconds}"
