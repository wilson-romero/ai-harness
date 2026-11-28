"""Change copilot-turn-speed, without a browser: the measured entries of ui.json, the
switches, the timings file and the probe's fast-end rule on sampled sequences."""

from __future__ import annotations

import json
import os
import stat

import pytest
from pydantic import ValidationError

from harness.config import Settings
from harness.core.errors import InvalidInput
from harness.providers import copilot_timings
from harness.providers.copilot_timings import TurnTimings, read_for, record, timings_path
from harness.providers.copilot_ui import UiMeasurement
from harness.providers.copilot_web import TurnSpeed, speed_for
from tests.browser.test_copilot_probe import load_probe
from tests.conftest import REPO_ROOT

SYNTHETIC = REPO_ROOT / "tests" / "fixtures" / "copilot_ui" / "ui.json"
FAST = {"signal": "stop_hidden", "confirm_ms": 500, "sends": 12, "modes": ["auto"],
        "measured_at": "2026-11-27T00:00:00Z"}
REUSE = {"questions": 4, "measured_at": "2026-11-27T00:00:00Z"}


def measurement(**changes) -> UiMeasurement:
    return UiMeasurement.model_validate(json.loads(SYNTHETIC.read_text(encoding="utf-8")) | changes)


# -- ui.json -----------------------------------------------------------------------------------


def test_a_measurement_without_the_new_entries_is_still_accepted():
    m = measurement()
    assert m.fast_end is None and m.tab_reuse is None


@pytest.mark.parametrize("change", [{"confirm_ms": 299}, {"confirm_ms": 2001}, {"sends": 0},
                                    {"signal": "text_stable_1000"}, {"extra": 1}])
def test_a_fast_end_outside_its_bounds_is_refused(change):
    with pytest.raises(ValidationError):
        measurement(fast_end=FAST | change)


def test_a_fast_end_needs_the_control_it_watches():
    data = json.loads(SYNTHETIC.read_text(encoding="utf-8"))
    del data["locators"]["stop"]
    with pytest.raises(ValidationError, match="stop"):
        UiMeasurement.model_validate(data | {"fast_end": FAST})
    assert UiMeasurement.model_validate(data | {"fast_end": FAST | {"signal": "send_ready"}})


# -- switches ----------------------------------------------------------------------------------


def test_without_the_measurement_both_optimisations_stay_off():
    assert speed_for(Settings.from_env({}), measurement()) == TurnSpeed()


def test_each_switch_turns_off_only_its_own_optimisation():
    m = measurement(fast_end=FAST, tab_reuse=REUSE)
    on = speed_for(Settings.from_env({"HARNESS_COPILOT_REUSE_TAB": "on"}), m)
    assert on.reuse_tab is True and on.fast_end is not None
    no_reuse = speed_for(Settings.from_env({"HARNESS_COPILOT_REUSE_TAB": "off"}), m)
    assert no_reuse.reuse_tab is False and no_reuse.fast_end is not None
    no_fast = speed_for(Settings.from_env({"HARNESS_COPILOT_FAST_END": "off",
                                           "HARNESS_COPILOT_REUSE_TAB": "on"}), m)
    assert no_fast.reuse_tab is True and no_fast.fast_end is None


@pytest.mark.parametrize("key", ["HARNESS_COPILOT_REUSE_TAB", "HARNESS_COPILOT_FAST_END",
                                 "HARNESS_COPILOT_TIMINGS", "HARNESS_COPILOT_HEADLESS"])
def test_a_switch_takes_only_on_or_off(key):
    with pytest.raises(InvalidInput, match=key):
        Settings.from_env({key: "1"})


def test_defaults():
    s = Settings.from_env({})
    # Review 2026-11-28, finding 5: reusing the tab stays off until the owner turns it on.
    assert (s.copilot_reuse_tab, s.copilot_fast_end, s.copilot_timings, s.copilot_headless) == (
        False, True, False, False)


def test_tab_reuse_measured_but_not_switched_on_stays_off():
    assert speed_for(Settings.from_env({}), measurement(tab_reuse=REUSE)).reuse_tab is False


def test_a_fast_end_says_in_which_modes_it_was_measured():
    with pytest.raises(ValidationError):
        measurement(fast_end={k: v for k, v in FAST.items() if k != "modes"})
    with pytest.raises(ValidationError):
        measurement(fast_end=FAST | {"modes": []})
    with pytest.raises(ValidationError):
        measurement(fast_end=FAST | {"modes": ["fast"]})
    assert measurement(fast_end=FAST | {"modes": ["auto", "deep"]}).fast_end.modes == ["auto", "deep"]


# -- timings file ------------------------------------------------------------------------------


def test_timings_are_appended_and_trimmed(tmp_path, monkeypatch):
    monkeypatch.setattr(copilot_timings, "TRIM_AT_BYTES", 2_000)
    monkeypatch.setattr(copilot_timings, "KEEP_LINES", 5)
    for n in range(30):
        t = TurnTimings(request_id=f"r{n}", session_id="s", outcome="answered")
        t.add("navigate", 0.25)
        record(tmp_path, t)
    lines = timings_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert 5 <= len(lines) < 30
    found = read_for(tmp_path, ["r0", "r29"])
    assert list(found) == ["r29"] and found["r29"].phases_ms == {"navigate": 250}


def test_a_timings_file_that_cannot_be_written_never_fails_the_question(tmp_path):
    (tmp_path / "copilot").write_text("a file where the directory should be", encoding="utf-8")
    record(tmp_path, TurnTimings(request_id="r", session_id="s"))  # no exception


def test_the_line_names_path_end_and_phases():
    t = TurnTimings(request_id="r", session_id="s", path="reload", declined="idle",
                    end="signal", outcome="answered")
    t.add("navigate", 0.4)
    t.total_ms = 1500
    assert t.line().startswith("timings (s): answered, path reload (idle), end signal, total 1.5")


# -- the probe's fast-end rule on sampled sequences --------------------------------------------


@pytest.fixture(scope="module")
def probe():
    return load_probe()


def samples(probe, steps):
    """steps: (t_ms, stop_visible, reply) tuples; the reply is hashed as the probe does."""
    return [probe.Sample(t_ms=t, turn=reply is not None, digest=None, content_digest=None,
                         has_text=bool(reply), has_marker=bool(reply and "END" in reply),
                         stop_visible=stop, send_ready=not stop, done=None, busy=None,
                         reply_digest=probe.text_hash(reply) if reply is not None else None)
            for t, stop, reply in steps]


def test_the_rule_fires_after_the_signal_and_the_text_held_still(probe):
    s = samples(probe, [(0, True, None), (100, True, "a"), (200, False, "a END"),
                        (500, False, "a END"), (800, False, "a END")])
    assert probe.fast_fire(s, "stop_hidden", 500) == 800


def test_the_rule_never_fires_without_seeing_the_page_busy(probe):
    s = samples(probe, [(t, False, "a END") for t in range(0, 3000, 100)])
    assert probe.fast_fire(s, "stop_hidden", 500) is None


def test_a_flickering_signal_restarts_the_confirmation(probe):
    s = samples(probe, [(0, True, "a"), (100, False, "a"), (400, True, "a"), (500, False, "a"),
                        (800, False, "a b END"), (1300, False, "a b END")])
    assert probe.fast_fire(s, "stop_hidden", 500) == 1300


def test_text_that_changes_after_the_signal_restarts_the_confirmation(probe):
    s = samples(probe, [(0, True, "a"), (100, False, "a END"), (400, False, "a END late"),
                        (700, False, "a END late"), (900, False, "a END late")])
    assert probe.fast_fire(s, "stop_hidden", 500) == 900


def test_an_early_rule_is_never_valid_and_none_is_chosen(probe):
    sends = [{"rules": {"stop_hidden+500": {"met": True, "early": n == 3, "delay_ms": 100}}}
             for n in range(8)]
    summary = probe.summarise_fast(sends, 8)
    assert summary["stop_hidden+500"]["valid"] is False
    assert probe.choose_fast(summary) is None


def test_a_rule_met_on_fewer_sends_than_planned_is_not_valid(probe):
    sends = [{"rules": {"stop_hidden+500": {"met": True, "early": False, "delay_ms": 100}}}
             for _ in range(7)]
    assert probe.summarise_fast(sends, 8)["stop_hidden+500"]["valid"] is False


def test_the_soonest_valid_rule_is_chosen(probe):
    good = {"met": True, "early": False}
    sends = [{"rules": {"stop_hidden+500": good | {"delay_ms": 520},
                        "stop_hidden+1000": good | {"delay_ms": 1020}}} for _ in range(8)]
    assert probe.choose_fast(probe.summarise_fast(sends, 8)) == {"signal": "stop_hidden",
                                                                 "confirm_ms": 500}


def test_on_a_tie_the_signal_measure_chose_wins(probe):
    good = {"met": True, "early": False, "delay_ms": 520}
    sends = [{"rules": {"aria_busy+500": good, "stop_hidden+500": good}} for _ in range(8)]
    summary = probe.summarise_fast(sends, 8)
    assert probe.choose_fast(summary)["signal"] == "aria_busy"  # control: by name alone
    assert probe.choose_fast(summary, "stop_hidden")["signal"] == "stop_hidden"


# -- review 2026-11-28: timings never change a question; private; tampered lines skipped ------

owner_only = pytest.mark.skipif(not hasattr(os, "getuid"), reason="no POSIX mode bits here")


def answered(request_id: str = "r1") -> TurnTimings:
    t = TurnTimings(request_id=request_id, session_id="s", outcome="answered")
    t.add("navigate", 0.25)
    return t


def test_a_corrupt_timings_file_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(copilot_timings, "TRIM_AT_BYTES", 1_000)
    path = timings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe not utf-8 \x80" * 200 + b"\n")
    record(tmp_path, answered())  # no exception, whatever the file holds
    assert "r1" in read_for(tmp_path, ["r1"])
    path.read_text(encoding="utf-8")  # the trim still ran: the bytes were read as replaced


def test_a_directory_in_place_of_the_timings_file_never_raises(tmp_path):
    timings_path(tmp_path).mkdir(parents=True)
    record(tmp_path, answered())


@owner_only
def test_an_unwritable_timings_directory_never_raises(tmp_path):
    (tmp_path / "copilot").mkdir()
    (tmp_path / "copilot").chmod(0o500)
    try:
        record(tmp_path, answered())
    finally:
        (tmp_path / "copilot").chmod(0o700)


def test_recording_never_raises_whatever_goes_wrong(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(copilot_timings.json, "dumps", broken)
    record(tmp_path, answered())


@owner_only
def test_the_timings_file_and_its_folder_are_owner_only(tmp_path, monkeypatch):
    monkeypatch.setattr(copilot_timings, "TRIM_AT_BYTES", 300)
    previous = os.umask(0o022)
    try:
        for n in range(5):  # the third line passes 300 bytes: the trimmed copy too
            record(tmp_path, answered(f"r{n}"))
    finally:
        os.umask(previous)
    path = timings_path(tmp_path)
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


GOOD = {"request_id": "r1", "session_id": "s", "path": "reload", "declined": None,
        "end": "window", "attempts": 1, "outcome": "answered", "phases_ms": {"navigate": 400},
        "total_ms": 400, "at": "2026-11-28T00:00:00+00:00", "early_endings": 0}


@pytest.mark.parametrize("change", [
    {"total_ms": "abc"}, {"total_ms": -1}, {"total_ms": 10**12}, {"total_ms": True},
    {"attempts": "1"}, {"attempts": 99}, {"phases_ms": {"navigate": "1"}},
    {"phases_ms": {"navigate": -5}}, {"phases_ms": []}, {"session_id": 7},
    {"session_id": "\x1b[2J"}, {"at": "\x1b]0;x\x07"}, {"early_endings": "x"},
    {"request_id": "r1", "extra": 1},
])
def test_a_line_with_a_bad_field_is_skipped(tmp_path, change):
    path = timings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(GOOD | change) + "\n", encoding="utf-8")
    assert read_for(tmp_path, ["r1"]) == {}


def test_control_a_good_line_is_read(tmp_path):
    path = timings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(GOOD) + "\n", encoding="utf-8")
    assert read_for(tmp_path, ["r1"])["r1"].total_ms == 400


def test_a_deeply_nested_line_is_skipped(tmp_path):
    path = timings_path(tmp_path)
    path.parent.mkdir(parents=True)
    # 2000 levels: within the line bound (4096), beyond what json.loads can nest
    path.write_text("[" * 2000 + "]" * 2000 + "\n" + json.dumps(GOOD) + "\n",
                    encoding="utf-8")
    assert list(read_for(tmp_path, ["r1"])) == ["r1"]  # control: the good line still reads


def test_nesting_beyond_the_parser_is_skipped(tmp_path, monkeypatch):
    """Defence in depth behind the line bound: a JSON nested past what the parser can take
    (RecursionError) is skipped too."""
    monkeypatch.setattr(copilot_timings, "MAX_LINE", 10**7)
    path = timings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("[" * 200_000 + "]" * 200_000 + "\n" + json.dumps(GOOD) + "\n",
                    encoding="utf-8")
    assert list(read_for(tmp_path, ["r1"])) == ["r1"]


def test_an_overlong_line_is_skipped(tmp_path):
    path = timings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(GOOD) + " " * 5000 + "\n", encoding="utf-8")  # valid, too long
    assert read_for(tmp_path, ["r1"]) == {}


# -- review 2026-11-28: the probe's rule ------------------------------------------------------


def test_busy_seen_before_the_reply_exists_does_not_count(probe):
    """The signal already busy before the answer appears (a stale stop button) is not the
    reply being busy: without busy seen on the reply, the rule never fires."""
    s = samples(probe, [(0, True, None), (100, False, None), (200, False, "a"),
                        (800, False, "a END"), (1500, False, "a END")])
    assert probe.fast_fire(s, "stop_hidden", 500) is None


def test_busy_again_after_the_rule_fired_is_early(probe):
    """The text never changes, so only the signal coming back to busy shows the end was
    early (an idle gap between two phases of the reply)."""
    s = samples(probe, [(0, True, "a END"), (100, False, "a END"), (700, False, "a END"),
                        (900, True, "a END"), (1000, False, "a END"), (5000, False, "a END")])
    analysis = probe.analyse_fast(s, probe_locators(), late_digest=probe.text_hash("a END"))
    assert analysis["rules"]["stop_hidden+500"]["early"] is True


def test_a_late_read_that_differs_makes_the_rule_early(probe):
    s = samples(probe, [(0, True, "a"), (100, False, "a END"), (700, False, "a END"),
                        (5000, False, "a END")])
    good = probe.analyse_fast(s, probe_locators(), late_digest=probe.text_hash("a END"))
    assert good["rules"]["stop_hidden+500"]["early"] is False  # control
    late = probe.analyse_fast(s, probe_locators(), late_digest=probe.text_hash("a END cites"))
    assert late["rules"]["stop_hidden+500"]["early"] is True
    assert late["late_changed"] is True


def test_the_planned_sends_and_the_smallest_run(probe):
    assert probe.speed_sends(5) == 2 * 6 + 3 * 5 == 27
    assert probe.speed_sends(5, deep=True) == 2 * 6 + 2 + 3 * 5
    assert probe.speed_sends(2, rounds=1, headless=False) == 6 + 2 * 2 == 10
    assert len(probe.SPEED_PROMPTS) == 6 and set(probe.PROMPTS) < set(probe.SPEED_PROMPTS)


def probe_locators():
    from harness.providers.copilot_ui import Locators

    return Locators.model_validate(json.loads(SYNTHETIC.read_text(encoding="utf-8"))["locators"])


def test_last_timings_is_a_stable_public_attribute(tmp_path):
    """The agent loop on develop reads `provider.last_timings`: None before any question, and
    a `TurnTimings` with these fields after (fields may be added, never removed)."""
    from harness.providers.copilot_web import CopilotWebProvider

    provider = CopilotWebProvider(Settings.from_env({"HARNESS_DATA_DIR": str(tmp_path)}))
    assert provider.last_timings is None
    assert {"request_id", "session_id", "path", "declined", "end", "attempts", "outcome",
            "phases_ms", "total_ms", "early_endings"} <= set(TurnTimings.__dataclass_fields__)


def arm(early: int = 0, n: int = 2) -> list[dict]:
    return [{"error": None, "whole": True, "outcome": "answered", "sends": 1,
             "same_conversation": True, "path": "reload" if q == 0 else "reuse",
             "early_endings": early if q == 1 else 0} for q in range(n)]


@pytest.mark.parametrize("early, written", [(0, True), (1, False)])
def test_finish_speed_refuses_a_rule_the_provider_found_early(probe, early, written):
    result = {"questions": 2, "end_sends": [{}] * 12, "end_sends_planned": 12,
              "fast_end_candidate": {"signal": "stop_hidden", "confirm_ms": 500, "modes": ["auto"]},
              "measured_at": "2026-11-28T00:00:00Z",
              "arms": {"off": arm(), "on": arm(early), "headless": arm()}}
    probe.finish_speed(result)
    assert ("fast_end" in result["write"]) is written and result["early_endings"] == early
    assert "tab_reuse" in result["write"]  # the reuse is measured apart
