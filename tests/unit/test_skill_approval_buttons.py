"""The engine's side of the approval buttons (approval-buttons D1): a press is an object only
the full screen's terminal returns, for the hash it was asked for; the typed code stays the
only way everywhere else, and the audit trail says which one decided."""

from __future__ import annotations

import pytest

from harness.shell.terminal import ConsoleTerminal, TtyTerminal
from harness.skills.approvals import (
    ButtonApprovalTerminal,
    ButtonPress,
    Verdict,
    decide,
)
from tests.skill_support import ApprovingTerminal, FakeTerminal
from tests.unit.test_skill_approval import _approval, _engine, _run

HASH = "c" * 64


class ButtonTerminal(FakeTerminal):
    """A full screen whose person presses `choice` (or nothing) in the box it is asked for."""

    def __init__(self, choice: str | None, *, for_hash: str | None = None) -> None:
        super().__init__()
        self.choice = choice
        self.for_hash = for_hash
        self.asked: list[str] = []

    def ask_buttons(self, question: str, approval_hash: str) -> ButtonPress | None:
        self.asked.append(approval_hash)
        if self.choice is None:
            return None
        return ButtonPress(self.choice, self.for_hash or approval_hash)  # type: ignore[arg-type]


def _detail(conn, event: str) -> str:
    row = conn.execute("SELECT detail FROM audit_events WHERE event_type = ?", (event,)).fetchone()
    return row[0]


def test_a_press_for_the_hash_asked_grants_and_the_audit_says_button(conn, data_dir, tmp_path):
    terminal = ButtonTerminal("approve")
    engine, session, effect, _ = _engine(conn, data_dir, tmp_path, terminal)
    outcome = _run(engine, session)
    assert outcome.status == "completed" and len(effect.written()) == 1
    assert terminal.questions == 0  # the typed question is never asked on the full screen
    approval = _approval(conn)[0]
    assert terminal.asked == [approval["proposal_hash"]]
    assert approval["status"] == "consumed" and approval["identity"] == "persona-local"
    assert _detail(conn, "approval.granted").endswith(";means=button")


def test_a_press_for_another_hash_leaves_it_pending(conn, data_dir, tmp_path):
    engine, session, effect, _ = _engine(conn, data_dir, tmp_path,
                                         ButtonTerminal("approve", for_hash=HASH))
    outcome = _run(engine, session)
    assert outcome.status == "awaiting_approval" and effect.written() == []
    assert _approval(conn)[0]["status"] == "pending"


def test_a_confirmed_reject_press_rejects(conn, data_dir, tmp_path):
    engine, session, effect, _ = _engine(conn, data_dir, tmp_path, ButtonTerminal("reject"))
    assert _run(engine, session).status == "cancelled"
    assert _approval(conn)[0]["status"] == "rejected" and effect.written() == []
    assert _detail(conn, "approval.rejected").endswith(";means=button")


def test_no_press_leaves_it_pending(conn, data_dir, tmp_path):
    engine, session, effect, _ = _engine(conn, data_dir, tmp_path, ButtonTerminal(None))
    assert _run(engine, session).status == "awaiting_approval"
    assert _approval(conn)[0]["status"] == "pending"


def test_the_typed_code_is_recorded_as_code(conn, data_dir, tmp_path):
    engine, session, effect, _ = _engine(conn, data_dir, tmp_path, ApprovingTerminal())
    assert _run(engine, session).status == "completed"
    assert _detail(conn, "approval.granted").endswith(";means=code")


def test_the_plain_conversation_and_the_cli_have_no_button_path():
    """By construction: neither terminal has `ask_buttons`, so `decide` asks for the code."""
    assert not isinstance(ConsoleTerminal(), ButtonApprovalTerminal)
    assert not isinstance(TtyTerminal(), ButtonApprovalTerminal)
    assert not isinstance(FakeTerminal(), ButtonApprovalTerminal)
    assert isinstance(ButtonTerminal("approve"), ButtonApprovalTerminal)


@pytest.mark.parametrize("answer", [
    ButtonPress("approve", HASH),  # an object handed to the typed question
    "approve", "Approve", "[ Approve ]", "button", "granted",
    f"ButtonPress(choice='approve', approval_hash='{HASH}')",
])
def test_nothing_typed_or_handed_to_the_typed_question_is_a_press(answer):
    terminal = FakeTerminal([answer, answer, answer])  # type: ignore[list-item]
    assert decide(terminal, "notice", HASH) == Verdict("undecided")


def test_the_typed_code_still_grants_without_buttons():
    terminal = FakeTerminal([HASH[:8]])
    assert decide(terminal, "notice", HASH) == Verdict("granted", "code")
