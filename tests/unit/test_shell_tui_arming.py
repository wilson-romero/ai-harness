"""The arming of the approval box does not depend on the speed of the machine
(approval-buttons D9, second Windows run of 2026-11-27).

The box arms after ARM_S of silence (no key, paste or mouse button) counted from its first
paint, and an input read before the arming never acts, however late it is handled. Time is
the box's clock (`ApprovalScreen.clock`), replaced here by a clock the test moves; the same
clock stamps every Textual message (`Message.time`), so an event the application makes
itself (the Click after a MouseUp) carries test time too, whatever the machine's uptime.
Each input event is built with the read stamp the terminal driver gives it and handed to the
application the way the driver does (`App.post_message`). "The timer fires" is
`_arm_if_quiet`, called before each delivery as a due timer would be.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import textual.message
from textual import events
from textual.widgets import Button

from harness.shell.tui import ARM_S, ApprovalScreen
from tests.tui_support import SIZE
from tests.unit.test_shell_tui import SKILL_LINE, _query, _skill_tui

MOUNT = 1000.0  # the box is painted at this moment of the test clock
CHARS = {"tab": "\t", "enter": "\r", "space": " "}
# The keys a person typed ahead with the skill line (the burst of the typed-ahead test).
TYPED_AHEAD = ("tab", "enter", "tab", "enter", "space", "enter")
# Windows 11, test copy of 79cde60, arm_s=0.5, ms after the box's on_mount, three runs: the
# typed-ahead keys (first to last), then the test's own Tab and Enter. The fourth case is the
# first run's keys with the second run's Tab and Enter, in the order they would be read.
WINDOWS_TRACES = {
    "run 1": ((154, 250, 350, 450, 550, 601), 656, 702),
    "run 2": ((171, 230, 290, 350, 410, 452), 530, 602),
    "run 3": ((159, 220, 280, 340, 400, 458), 586, 663),
    "keys to 601, Tab 530, Enter 602": ((154, 250, 350, 450, 550, 601), 530, 602),
}


class Clock:
    def __init__(self) -> None:
        self.now = MOUNT

    def __call__(self) -> float:
        return self.now

    def at(self, ms: float) -> float:
        self.now = MOUNT + ms / 1000
        return self.now


@pytest.fixture
def clock(monkeypatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(ApprovalScreen, "clock", staticmethod(fake))
    monkeypatch.setattr(textual.message, "_time", SimpleNamespace(get_time=fake))
    return fake


async def _open(tui, pilot) -> ApprovalScreen:
    await tui.send(pilot, SKILL_LINE)
    return await tui.approval_box(pilot)


def _key(name: str, read: float) -> events.Key:
    event = events.Key(name, CHARS.get(name))
    event.time = read
    return event


def _click(box: ApprovalScreen, name: str, read: float) -> list[events.Event]:
    """MouseDown and MouseUp on a button, as the driver reports them; the application makes
    the Click itself when it handles the MouseUp."""
    region = box.query_one(f"#{name}", Button).region
    x, y = region.x + region.width // 2, region.y + region.height // 2
    made = []
    for cls in (events.MouseDown, events.MouseUp):
        event = cls(None, x, y, 0, 0, 1, False, False, False, screen_x=x, screen_y=y)
        event.time = read
        made.append(event)
    return made


async def _deliver(tui, pilot, clock: Clock, handled_ms: float, made: list) -> None:
    """Handle already-read events at `handled_ms`, after any timer that is due."""
    clock.at(handled_ms)
    box = tui.app.screen
    if isinstance(box, ApprovalScreen):
        box._arm_if_quiet()
    for event in made:
        tui.app.post_message(event)
    await pilot.pause()
    await pilot.pause(0.05)


async def _pending(tui, pilot, effect) -> None:
    assert isinstance(tui.app.screen, ApprovalScreen) and not tui.app.screen.pressed
    await pilot.press("ctrl+c")
    await tui.ready(pilot)
    await tui.send(pilot, "/exit")
    assert effect.written() == []
    assert _query(tui.data_dir, "SELECT status FROM approvals") == ["pending"]


async def _approved(tui, pilot, effect) -> None:
    await tui.until(pilot, lambda: any("is completed" in t for t in tui.blocks("harness")))
    await tui.ready(pilot)
    await tui.send(pilot, "/exit")
    assert len(effect.written()) == 1
    assert _query(tui.data_dir, "SELECT status FROM approvals") == ["consumed"]


async def _rejected(tui, pilot, effect) -> None:
    await tui.until(pilot, lambda: any("is cancelled" in t for t in tui.blocks("harness")))
    await tui.ready(pilot)
    await tui.send(pilot, "/exit")
    assert effect.written() == []
    assert _query(tui.data_dir, "SELECT status FROM approvals") == ["rejected"]


def test_the_box_reads_the_clock_input_events_are_stamped_with():
    assert abs(ApprovalScreen.clock() - events.Key("a", "a").time) < 0.05


@pytest.mark.parametrize("trace", WINDOWS_TRACES, ids=list(WINDOWS_TRACES))
async def test_the_windows_trace_replayed_approves_nothing(tmp_path, clock, trace):
    """Each key is handled when it is read, as on that machine. With the arming by the clock
    alone the box armed at +501 ms and the Tab and Enter after it approved (written=1)."""
    ahead, tab, enter = WINDOWS_TRACES[trace]
    tui, effect = _skill_tui(tmp_path, arm_s=ARM_S)
    async with tui.app.run_test(size=SIZE) as pilot:
        box = await _open(tui, pilot)
        reads = sorted([*zip(ahead, TYPED_AHEAD, strict=True), (tab, "tab"), (enter, "enter")])
        for ms, name in reads:
            await _deliver(tui, pilot, clock, ms, [_key(name, clock.at(ms))])
        assert not box.armed  # the silence restarted with each key
        await _pending(tui, pilot, effect)


@pytest.mark.parametrize("after_s", [0.6, 2.0])
@pytest.mark.parametrize("delivery", ["one chunk", "one by one"])
async def test_tab_and_enter_after_the_silence_approve(tmp_path, clock, after_s, delivery):
    """The legitimate case: nothing for ARM_S after the paint, then Tab and Enter."""
    tui, effect = _skill_tui(tmp_path, arm_s=ARM_S)
    async with tui.app.run_test(size=SIZE) as pilot:
        await _open(tui, pilot)
        ms = after_s * 1000
        if delivery == "one chunk":
            await _deliver(tui, pilot, clock, ms, [_key("tab", clock.at(ms)),
                                                   _key("enter", clock.at(ms))])
        else:
            await _deliver(tui, pilot, clock, ms, [_key("tab", clock.at(ms))])
            await _deliver(tui, pilot, clock, ms + 100, [_key("enter", clock.at(ms + 100))])
        await _approved(tui, pilot, effect)


@pytest.mark.parametrize("read_s", [0.0, 0.4])
@pytest.mark.parametrize("delivery", ["one chunk", "one by one"])
@pytest.mark.parametrize("kind", ["keys", "click"])
async def test_input_read_before_the_arming_never_acts_however_late_it_is_handled(
        tmp_path, clock, read_s, delivery, kind):
    """A busy loop: the input was read before the box armed and is handled after it."""
    tui, effect = _skill_tui(tmp_path, arm_s=ARM_S)
    async with tui.app.run_test(size=SIZE) as pilot:
        box = await _open(tui, pilot)
        read = MOUNT + read_s
        if kind == "keys":
            made = [_key("tab", read), _key("enter", read + (0.05 if delivery == "one by one"
                                                             else 0.0))]
        else:
            made = _click(box, "approve", read)
        clock.at(600)
        box._arm_if_quiet()  # due, and nothing was handled before it: it arms
        assert box.armed
        await tui.until(pilot, lambda: not box.query_one("#approve", Button).disabled)
        if delivery == "one by one":
            for event in made:
                await _deliver(tui, pilot, clock, 600, [event])
        else:
            await _deliver(tui, pilot, clock, 600, made)
        await _pending(tui, pilot, effect)


@pytest.mark.parametrize("kind", ["keys", "click"])
async def test_a_fresh_click_or_key_after_arming_still_approves(tmp_path, clock, kind):
    """Positive control for the test above: the same input, read after the arming."""
    tui, effect = _skill_tui(tmp_path, arm_s=ARM_S)
    async with tui.app.run_test(size=SIZE) as pilot:
        box = await _open(tui, pilot)
        clock.at(600)
        box._arm_if_quiet()
        await tui.until(pilot, lambda: not box.query_one("#approve", Button).disabled)
        made = ([_key("tab", clock.at(650)), _key("enter", clock.at(650))] if kind == "keys"
                else _click(box, "approve", clock.at(650)))
        await _deliver(tui, pilot, clock, 650, made)
        await _approved(tui, pilot, effect)


@pytest.mark.parametrize("read_s", [0.0, 0.4])
@pytest.mark.parametrize("kind", ["key", "click"])
async def test_input_before_the_arming_restarts_the_silence(tmp_path, clock, read_s, kind):
    tui, effect = _skill_tui(tmp_path, arm_s=ARM_S)
    async with tui.app.run_test(size=SIZE) as pilot:
        box = await _open(tui, pilot)
        ms = read_s * 1000
        made = ([_key("down", clock.at(ms))] if kind == "key"
                else _click(box, "approve", clock.at(ms)))
        await _deliver(tui, pilot, clock, ms, made)
        assert not box.armed
        clock.at(ms + 490)
        box._arm_if_quiet()
        assert not box.armed
        clock.at(ms + 500)
        box._arm_if_quiet()
        assert box.armed
        await _pending(tui, pilot, effect)


async def test_keys_read_before_a_late_arming_never_act(tmp_path):
    """The same busy loop with the real clock and no test clock: keys made (read) first, the
    arming next, the keys handled last. With the arming by the clock alone it approved."""
    tui, effect = _skill_tui(tmp_path, arm_s=3600.0)
    async with tui.app.run_test(size=SIZE) as pilot:
        box = await _open(tui, pilot)
        made = [events.Key("tab", "\t"), events.Key("enter", "\r")]
        box.opened -= 3600.0  # the arming time has passed
        box._arm()  # what the timer does, late
        await tui.until(pilot, lambda: not box.query_one("#approve", Button).disabled)
        for event in made:
            tui.app.post_message(event)
        await pilot.pause(0.2)
        await _pending(tui, pilot, effect)


# -- review of 2026-11-27: a stall, the confirmation, pastes, the filter of each widget ---------


def _burst(first_ms: float, last_ms: float) -> list[float]:
    """Read times every 100 ms, as a person typing on."""
    count = round((last_ms - first_ms) / 100) + 1
    return [first_ms + 100 * n for n in range(count)]


@pytest.mark.parametrize("stall_ms", [700, 2000])
@pytest.mark.parametrize("burst", ["ends before the stall ends", "goes on after the arming"])
@pytest.mark.parametrize("kind", ["keys", "mouse"])
async def test_a_stall_then_a_burst_across_the_arming_approves_nothing(
        tmp_path, clock, stall_ms, burst, kind):
    """The reviewer's sequence. Keys are read every 100 ms from +0.1 s while the loop stalls
    until `stall_ms`; when it runs again the arming timer goes first and arms with the
    silence counted from the paint. The keys already read come next. They were read before
    the arming, so it was no silence: the box disarms and counts from the last of them. The
    burst then goes on (Tab and Enter, or a click on Approve, read after that arming)."""
    tui, effect = _skill_tui(tmp_path, arm_s=ARM_S)
    async with tui.app.run_test(size=SIZE) as pilot:
        box = await _open(tui, pilot)
        reads = _burst(100, stall_ms - 100)
        queued = [_key("down", MOUNT + ms / 1000) for ms in reads]
        clock.at(stall_ms)
        box._arm_if_quiet()  # the timer runs first
        assert box.armed
        await _deliver(tui, pilot, clock, stall_ms, queued)
        assert not box.armed  # each earlier input restarts the interval
        last = reads[-1]
        if burst == "goes on after the arming":
            later = stall_ms + 50
            made = ([_key("tab", MOUNT + later / 1000), _key("enter", MOUNT + (later + 50) / 1000)]
                    if kind == "keys" else _click(box, "approve", MOUNT + later / 1000))
            await _deliver(tui, pilot, clock, later + 50, made)
            # Enter is read at +50; the Click is made by the application when it handles
            # the MouseUp, at +50, and stamped then.
            last = later + 50
            assert not box.armed
        clock.at(last + 490)
        box._arm_if_quiet()
        assert not box.armed  # not before the last input read + ARM_S
        clock.at(last + 500)
        box._arm_if_quiet()
        assert box.armed
        await _pending(tui, pilot, effect)


async def test_the_confirmation_ignores_input_read_just_after_it_appeared(tmp_path, clock):
    """The question of Reject arms like the box: Tab and Enter read 10 ms after it appeared,
    and handled 0.6 s later, do not confirm the rejection."""
    tui, effect = _skill_tui(tmp_path, arm_s=ARM_S)
    async with tui.app.run_test(size=SIZE) as pilot:
        box = await _open(tui, pilot)
        clock.at(600)
        box._arm_if_quiet()
        await _deliver(tui, pilot, clock, 650, _click(box, "reject", clock.at(650)))
        assert box.query_one("#approval-confirm").display
        queued = [_key("tab", MOUNT + 0.66), _key("enter", MOUNT + 0.66)]
        await _deliver(tui, pilot, clock, 1250, queued)  # the timer may have armed first
        assert isinstance(tui.app.screen, ApprovalScreen) and not box.pressed
        await pilot.press("ctrl+c")
        await tui.ready(pilot)
        await tui.send(pilot, "/exit")
    assert _query(tui.data_dir, "SELECT status FROM approvals") == ["pending"]


async def test_the_confirmation_accepts_input_after_its_silence(tmp_path, clock):
    """Positive control: 0.5 s of silence after the question, then Tab and Enter reject."""
    tui, effect = _skill_tui(tmp_path, arm_s=ARM_S)
    async with tui.app.run_test(size=SIZE) as pilot:
        box = await _open(tui, pilot)
        clock.at(600)
        box._arm_if_quiet()
        await _deliver(tui, pilot, clock, 650, _click(box, "reject", clock.at(650)))
        await tui.until(pilot, lambda: box.shown)  # the question is painted
        clock.at(1300)
        box._arm_if_quiet()
        assert box.armed
        await _deliver(tui, pilot, clock, 1300, [_key("tab", clock.at(1300)),
                                                 _key("enter", clock.at(1300))])
        await _rejected(tui, pilot, effect)


async def test_a_paste_restarts_the_silence(tmp_path, clock):
    tui, effect = _skill_tui(tmp_path, arm_s=ARM_S)
    async with tui.app.run_test(size=SIZE) as pilot:
        box = await _open(tui, pilot)
        paste = events.Paste("approve\r")
        paste.time = clock.at(400)
        await _deliver(tui, pilot, clock, 400, [paste])
        clock.at(600)
        box._arm_if_quiet()
        assert not box.armed
        clock.at(900)
        box._arm_if_quiet()
        assert box.armed
        await _pending(tui, pilot, effect)


@pytest.mark.parametrize("widget", ["#approve", "#reject", "#approval-content"])
async def test_each_widget_of_the_box_filters_input_read_before_the_arming(
        tmp_path, clock, widget):
    """Defence in depth: the proposal and each button judge the read time themselves, not
    only the box (a mutant that removes one widget's filter makes its case fail)."""
    tui, effect = _skill_tui(tmp_path, arm_s=ARM_S)
    async with tui.app.run_test(size=SIZE) as pilot:
        box = await _open(tui, pilot)
        clock.at(600)
        box._arm_if_quiet()
        target = box.query_one(widget)
        assert target.check_message_enabled(_key("enter", clock.at(610)))  # read after: passes
        assert box.armed
        assert not target.check_message_enabled(_key("enter", MOUNT + 0.3))  # read before
        assert not box.armed  # and the box disarms
        await _pending(tui, pilot, effect)


async def test_a_click_pressed_before_a_late_arming_never_presses_even_if_it_rearms(
        tmp_path, clock):
    """The button went down at +0.1 s and the loop stalled until +2 s: the MouseDown is
    dropped and disarms, and since the silence before it was long the box arms again. The
    button comes up at +2.05 s, after that arming, so the MouseUp passes and the application
    makes a new Click; its MouseDown was not new: it does not press."""
    tui, effect = _skill_tui(tmp_path, arm_s=ARM_S)
    async with tui.app.run_test(size=SIZE) as pilot:
        box = await _open(tui, pilot)
        down, up = _click(box, "approve", MOUNT + 0.1)
        clock.at(2000)
        box._arm_if_quiet()
        await tui.until(pilot, lambda: not box.query_one("#approve", Button).disabled)
        await _deliver(tui, pilot, clock, 2000, [down])
        await tui.until(pilot, lambda: box.armed)  # armed again: 1.9 s of silence before it
        await tui.until(pilot, lambda: not box.query_one("#approve", Button).disabled)
        up.time = MOUNT + 2.05
        await _deliver(tui, pilot, clock, 2050, [up])
        await _pending(tui, pilot, effect)
