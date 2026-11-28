"""Change copilot-turn-speed, without a browser: the measured entries of ui.json, the
switches, the timings file and the probe's fast-end rule on sampled sequences."""

from __future__ import annotations

import json

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
FAST = {"signal": "stop_hidden", "confirm_ms": 500, "sends": 8, "measured_at": "2026-11-27T00:00:00Z"}
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
    on = speed_for(Settings.from_env({}), m)
    assert on.reuse_tab is True and on.fast_end is not None
    no_reuse = speed_for(Settings.from_env({"HARNESS_COPILOT_REUSE_TAB": "off"}), m)
    assert no_reuse.reuse_tab is False and no_reuse.fast_end is not None
    no_fast = speed_for(Settings.from_env({"HARNESS_COPILOT_FAST_END": "off"}), m)
    assert no_fast.reuse_tab is True and no_fast.fast_end is None


@pytest.mark.parametrize("key", ["HARNESS_COPILOT_REUSE_TAB", "HARNESS_COPILOT_FAST_END",
                                 "HARNESS_COPILOT_TIMINGS", "HARNESS_COPILOT_HEADLESS"])
def test_a_switch_takes_only_on_or_off(key):
    with pytest.raises(InvalidInput, match=key):
        Settings.from_env({key: "1"})


def test_defaults():
    s = Settings.from_env({})
    assert (s.copilot_reuse_tab, s.copilot_fast_end, s.copilot_timings, s.copilot_headless) == (
        True, True, False, False)


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


def test_the_announced_sends(probe):
    assert probe.speed_sends(5) == 8 + 3 * 5 == 23
