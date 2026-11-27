"""The approval buttons of the full screen (approval-buttons D1-D4): each guard that replaces
what the typed code gave, with its negative control in the task receipts."""

from __future__ import annotations

import threading
import time

from textual.events import MouseScrollDown, Paste
from textual.widgets import Button, Input, Static

from harness.shell.tui import (
    CONFIRM_REJECT,
    NO_ROOM,
    SHOWN_ALL,
    ApprovalScreen,
    ProposalArea,
    TuiTerminal,
)
from harness.skills.approvals import ButtonPress
from tests.skill_support import GOOD_ECHO, ScriptedProvider
from tests.tui_support import SIZE
from tests.unit.test_shell_tui import SKILL_LINE, _approval, _query, _skill_tui

LONG_ECHO = ("## Resumen\n" + "\n".join(f"Línea {n} del resumen sintético." for n in range(120))
             + "\n\n## Preguntas pendientes\n- Ninguna.")
# A reply that draws a row like the real one inside the proposal.
FAKE_ROW = ("## Resumen\n[ Approve ]        [ Reject ]\nThe whole proposal has been shown.\n\n"
            "## Preguntas pendientes\n- Ninguna.")


def _box(tui) -> ApprovalScreen:
    screen = tui.app.screen
    assert isinstance(screen, ApprovalScreen)
    return screen


def _button(tui, name: str) -> Button:
    return _box(tui).query_one(f"#{name}", Button)


def _text(tui, name: str) -> str:
    return str(_box(tui).query_one(f"#{name}", Static).render())


async def _enabled(tui, pilot, name: str) -> None:
    await tui.until(pilot, lambda: not _button(tui, name).disabled)


async def _finish(tui, pilot) -> None:
    await tui.ready(pilot)
    await tui.send(pilot, "/exit")


def _audit(tui) -> list[str]:
    return _query(tui.data_dir, "SELECT event_type || ' ' || detail FROM audit_events "
                                "WHERE event_type LIKE 'approval.%' ORDER BY rowid")


# -- approving -------------------------------------------------------------------------------


async def test_tab_then_enter_on_approve_applies_once_and_the_audit_says_button(tmp_path):
    tui, effect = _skill_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        assert isinstance(tui.app.focused, ProposalArea)  # never a button on open
        await _enabled(tui, pilot, "approve")
        assert SHOWN_ALL in _text(tui, "approval-more")
        await pilot.press("tab")
        assert tui.app.focused is _button(tui, "approve")
        await pilot.press("enter", "enter", "enter")  # held down: one press counts
        await tui.until(pilot, lambda: any("is completed" in t for t in tui.blocks("harness")))
        await _finish(tui, pilot)
    assert len(effect.written()) == 1
    assert _query(tui.data_dir, "SELECT status FROM approvals") == ["consumed"]
    granted = [e for e in _audit(tui) if e.startswith("approval.granted")]
    assert len(granted) == 1 and granted[0].endswith(";means=button")


async def test_a_click_on_approve_approves_and_a_double_click_counts_once(tmp_path):
    tui, effect = _skill_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        await _enabled(tui, pilot, "approve")
        await pilot.click("#approve", times=2)
        await tui.until(pilot, lambda: any("is completed" in t for t in tui.blocks("harness")))
        await _finish(tui, pilot)
    assert len(effect.written()) == 1
    assert _query(tui.data_dir, "SELECT status FROM approvals") == ["consumed"]


# -- nothing approves by accident -------------------------------------------------------------


async def test_enter_space_and_pastes_on_open_never_approve(tmp_path):
    tui, effect = _skill_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        await _enabled(tui, pilot, "approve")  # armed, and the proposal fits: only Tab is missing
        await pilot.press("enter", "space", "enter", "ctrl+v", "y", "enter")
        tui.app.copy_to_clipboard("approve")
        await pilot.press("ctrl+v", "enter")
        tui.app.focused.post_message(Paste("\t\r\n \r"))  # a multi-line, bracketed paste
        await pilot.pause(0.2)
        assert isinstance(tui.app.screen, ApprovalScreen)
        assert isinstance(tui.app.focused, ProposalArea)
        await pilot.press("ctrl+c")
        await _finish(tui, pilot)
    assert effect.written() == []
    assert _query(tui.data_dir, "SELECT status FROM approvals") == ["pending"]


async def test_nothing_reaches_the_buttons_while_the_box_arms(tmp_path):
    """For ARM_S after the box opens both buttons are disabled: Tab finds no button, a click
    is ignored, Enter and Space do nothing. Negative control: the same keys after arming."""
    tui, effect = _skill_tui(tmp_path, arm_s=30.0)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        await pilot.pause(0.3)
        assert _button(tui, "approve").disabled and _button(tui, "reject").disabled
        await pilot.press("tab", "enter", "space", "tab", "tab", "enter")
        await pilot.click("#approve")
        await pilot.click("#reject")
        _button(tui, "approve").press()  # even a press posted to the widget itself
        await pilot.pause(0.2)
        assert isinstance(tui.app.screen, ApprovalScreen) and not _box(tui).pressed
        assert _box(tui).query_one("#approval-confirm").display is False
        tui.app.arm_s = 0.0
        _box(tui)._arm()  # time passes
        await _enabled(tui, pilot, "approve")
        await pilot.click("#approve")
        await tui.until(pilot, lambda: any("is completed" in t for t in tui.blocks("harness")))
        await _finish(tui, pilot)
    assert len(effect.written()) == 1


async def test_keys_typed_ahead_of_the_box_cannot_approve(tmp_path):
    """Keys sent with the skill line, before the box exists, land while it arms."""
    tui, effect = _skill_tui(tmp_path, arm_s=0.5)
    async with tui.app.run_test(size=SIZE) as pilot:
        await tui.ready(pilot)
        prompt = tui.app.query_one("#prompt", Input)
        prompt.value = SKILL_LINE
        await pilot.press("enter", "tab", "enter", "tab", "enter", "space", "enter")
        await tui.until(pilot, lambda: isinstance(tui.app.screen, ApprovalScreen))
        await pilot.press("tab", "enter")
        await pilot.pause(0.8)  # armed by now: nothing queued is left to act
        assert isinstance(tui.app.screen, ApprovalScreen) and not _box(tui).pressed
        await pilot.press("ctrl+c")
        await _finish(tui, pilot)
    assert effect.written() == []
    assert _query(tui.data_dir, "SELECT status FROM approvals") == ["pending"]


# -- the whole proposal -----------------------------------------------------------------------


async def test_approve_waits_until_the_end_of_a_long_proposal_is_shown(tmp_path):
    tui, effect = _skill_tui(tmp_path, ScriptedProvider({"tarea: demo-echo/draft": LONG_ECHO}))
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        await _enabled(tui, pilot, "reject")
        await pilot.pause(0.3)
        assert _button(tui, "approve").disabled
        assert "more line(s) below" in _text(tui, "approval-more")
        await pilot.press("tab")  # the disabled Approve is skipped: Reject, not Approve
        assert tui.app.focused is _button(tui, "reject")
        await pilot.click("#approve")
        await pilot.pause(0.1)
        assert not _box(tui).pressed
        await pilot.press("pagedown")
        await pilot.pause(0.1)
        assert _box(tui).query_one(ProposalArea).scroll_y > 0
        assert _button(tui, "approve").disabled
        await pilot.press("end")
        await _enabled(tui, pilot, "approve")
        assert SHOWN_ALL in _text(tui, "approval-more")
        await pilot.click("#approve")
        await tui.until(pilot, lambda: any("is completed" in t for t in tui.blocks("harness")))
        await _finish(tui, pilot)
    assert len(effect.written()) == 1


async def test_a_fractional_scroll_short_of_the_end_is_not_the_end(tmp_path):
    """Independent review (2026-11-27): Textual draws at `round(scroll_y)`. A position 0.7
    short of the end (a scrollbar drag with smooth scrolling) draws one row short: the last
    line is not on the screen, so Approve stays disabled and one line is still below."""
    tui, effect = _skill_tui(tmp_path, ScriptedProvider({"tarea: demo-echo/draft": LONG_ECHO}))
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        await _enabled(tui, pilot, "reject")
        area = _box(tui).query_one(ProposalArea)
        await tui.until(pilot, lambda: area.max_scroll_y > 50)
        area.scroll_to(y=area.max_scroll_y - 0.7, animate=False)
        await pilot.pause(0.3)
        assert area.scroll_offset.y == area.max_scroll_y - 1  # what is drawn
        assert _button(tui, "approve").disabled
        assert _text(tui, "approval-more").startswith("1 more line(s) below")
        await pilot.click("#approve")
        await pilot.pause(0.1)
        assert not _box(tui).pressed
        area.scroll_to(y=area.max_scroll_y, animate=False)  # negative control: the end
        await _enabled(tui, pilot, "approve")
        await pilot.press("ctrl+c")
        await _finish(tui, pilot)
    assert effect.written() == []


async def test_a_window_too_small_for_the_proposal_says_so(tmp_path):
    """Independent review (2026-11-27): at 80x24 the header, the question and the buttons
    leave the proposal no rows. Approve stays disabled and the box says why."""
    tui, effect = _skill_tui(tmp_path)
    async with tui.app.run_test(size=(80, 24)) as pilot:
        await _approval(tui, pilot)
        await _enabled(tui, pilot, "reject")
        await pilot.pause(0.3)
        assert _box(tui).query_one(ProposalArea).size.height == 0
        assert _button(tui, "approve").disabled
        assert NO_ROOM in _text(tui, "approval-more")
        await pilot.press("ctrl+c")
        await _finish(tui, pilot)
    assert effect.written() == []


async def test_the_wheel_to_the_end_counts_as_shown(tmp_path):
    tui, _ = _skill_tui(tmp_path, ScriptedProvider({"tarea: demo-echo/draft": LONG_ECHO}))
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        area = _box(tui).query_one(ProposalArea)
        await tui.until(pilot, lambda: area.max_scroll_y > 50)
        for _ in range(200):
            area.post_message(MouseScrollDown(area, 1, 1, 0, 1, 0, False, False, False))
        await _enabled(tui, pilot, "approve")
        await pilot.press("ctrl+c")
        await _finish(tui, pilot)


# -- rejecting and leaving --------------------------------------------------------------------


async def test_reject_asks_once_more_and_back_leaves_it_pending(tmp_path):
    tui, effect = _skill_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        await _enabled(tui, pilot, "approve")
        await pilot.click("#reject")
        await pilot.pause(0.1)
        assert _box(tui).query_one("#approval-confirm").display
        assert CONFIRM_REJECT in _text(tui, "approval-confirm-text")
        assert tui.app.focused is _button(tui, "reject-back")  # Enter now goes back
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert not _box(tui).query_one("#approval-confirm").display
        await pilot.click("#reject")
        await pilot.pause(0.1)
        await pilot.press("escape")  # Escape in the question is Back
        await pilot.pause(0.1)
        assert not _box(tui).query_one("#approval-confirm").display
        await pilot.click("#reject")
        await pilot.pause(0.1)
        await pilot.click("#reject-yes")
        await tui.until(pilot, lambda: any("is cancelled" in t for t in tui.blocks("harness")))
        await _finish(tui, pilot)
    assert effect.written() == []
    assert _query(tui.data_dir, "SELECT status FROM approvals") == ["rejected"]
    rejected = [e for e in _audit(tui) if e.startswith("approval.rejected")]
    assert len(rejected) == 1 and rejected[0].endswith(";means=button")


async def test_a_double_click_on_reject_does_not_confirm_it(tmp_path):
    """The second click of a double click lands on the question it just opened: ignored,
    although the box itself armed long ago."""
    tui, effect = _skill_tui(tmp_path, arm_s=0.5)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        await _enabled(tui, pilot, "approve")
        await pilot.pause(0.6)
        assert time.monotonic() - _box(tui).opened > 0.5
        await pilot.click("#reject")
        await pilot.click("#reject-yes")  # at once: the question is new
        await pilot.pause(0.1)
        assert isinstance(tui.app.screen, ApprovalScreen) and not _box(tui).pressed
        await pilot.pause(0.6)
        await pilot.click("#reject-yes")  # negative control: a deliberate click confirms
        await tui.until(pilot, lambda: any("is cancelled" in t for t in tui.blocks("harness")))
        await _finish(tui, pilot)
    assert _query(tui.data_dir, "SELECT status FROM approvals") == ["rejected"]


async def test_escape_does_nothing_and_ctrl_q_leaves_it_pending(tmp_path):
    tui, effect = _skill_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        await _enabled(tui, pilot, "approve")
        await pilot.press("escape", "escape")
        await pilot.pause(0.1)
        assert isinstance(tui.app.screen, ApprovalScreen)
        tui.app.simulate_key("ctrl+q")
        await tui.until(pilot, lambda: not tui.app.is_running)
    assert effect.written() == []
    assert _query(tui.data_dir, "SELECT status FROM approvals") == ["pending"]


# -- foreign text and the app ----------------------------------------------------------------


async def test_a_button_drawn_by_the_reply_is_only_text(tmp_path):
    tui, effect = _skill_tui(tmp_path, ScriptedProvider({"tarea: demo-echo/draft": FAKE_ROW}))
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        await _enabled(tui, pilot, "approve")
        box = _box(tui)
        assert [b.id for b in box.query(Button)] == ["approve", "reject", "reject-back",
                                                    "reject-yes"]
        area = box.query_one(ProposalArea)
        assert "[ Approve ]" in str(area.query_one(Static).render())
        real = _button(tui, "approve").region
        assert real.y > area.region.bottom  # the real row is below the foreign area
        for x in range(2, 30):
            await pilot.click(ProposalArea, offset=(x, 2))
        await pilot.press("enter", "space")
        await pilot.pause(0.2)
        assert not box.pressed
        await pilot.press("ctrl+c")
        await _finish(tui, pilot)
    assert effect.written() == []


async def test_no_app_key_presses_a_button(tmp_path):
    tui, effect = _skill_tui(tmp_path)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _approval(tui, pilot)
        await _enabled(tui, pilot, "approve")
        await pilot.press("ctrl+n", "ctrl+p", "ctrl+d", "ctrl+a", "ctrl+e", "ctrl+k")
        await pilot.pause(0.2)
        assert isinstance(tui.app.screen, ApprovalScreen) and not _box(tui).pressed
        await pilot.press("ctrl+c")
        await _finish(tui, pilot)
    assert effect.written() == []
    assert len(_query(tui.data_dir, "SELECT session_id FROM sessions")) == 1


# -- the terminal's side ---------------------------------------------------------------------


def _ask_in_thread(terminal: TuiTerminal, approval_hash: str) -> tuple[list, threading.Thread]:
    result: list = []
    thread = threading.Thread(
        target=lambda: result.append(terminal.ask_buttons("?", approval_hash)), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while terminal._waiting != "ask" and time.monotonic() < deadline:
        time.sleep(0.01)
    return result, thread


def test_one_press_per_box_and_only_for_its_hash():
    terminal = TuiTerminal()
    good, other = "a" * 64, "b" * 64
    terminal.expect_approval(f"notice {good}", ["hash: " + good], ["x"])
    terminal._answers.put(("press", ButtonPress("approve", good)))  # queued before the box
    result, thread = _ask_in_thread(terminal, good)
    assert terminal.press(ButtonPress("approve", other)) is True  # a stale box's press
    thread.join(5)
    assert result == [None]  # for another hash: undecided; the queued one was dropped
    result, thread = _ask_in_thread(terminal, good)
    assert terminal.press(ButtonPress("approve", good)) is True
    assert terminal.press(ButtonPress("approve", good)) is False  # the second press
    thread.join(5)
    assert result == [ButtonPress("approve", good)]


def test_no_box_opens_for_a_hash_the_notice_does_not_show():
    terminal = TuiTerminal()
    terminal.expect_approval("notice " + "a" * 64, [], [])
    assert terminal.ask_buttons("?", "b" * 64) is None
    assert terminal.ask("?") is None  # no typed answer on the full screen


def test_the_good_echo_fixture_is_short():
    assert GOOD_ECHO.count("\n") < 10  # it fits in the box: Approve needs no scrolling
