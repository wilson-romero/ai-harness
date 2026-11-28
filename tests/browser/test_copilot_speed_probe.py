"""The probe's `speed` step against the synthetic chat (change copilot-turn-speed, D5): one
command measures the end signals with the fixed prompts, then the same fixed prompts with the
optimisations off, on, and on without a window, and prints the phase table of each.

The synthetic server counts every prompt it receives: the oracle for "nothing beyond the
fixed prompts, as many as announced".
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout

import pytest

from harness.providers.copilot_ui import load_measurement, measurement_path
from tests.browser.test_copilot_probe import clean_env, load_probe
from tests.browser.test_copilot_provider import write_ui
from tests.conftest import REPO_ROOT
from tests.copilot_app import CANARIES

MENU = REPO_ROOT / "tests" / "fixtures" / "copilot_ui" / "response-mode-menu.json"

pytestmark = pytest.mark.edge

QUESTIONS = 2


@pytest.fixture
def speed(tmp_path, monkeypatch, copilot_app):
    """A probe on a measured synthetic chat (as `measure` leaves it), 1 s window."""
    probe = load_probe()
    data = tmp_path / "data"
    clean_env(monkeypatch, HARNESS_DATA_DIR=str(data), HARNESS_REQUEST_TIMEOUT_S="40",
              HARNESS_EDGE_PROFILE=str(tmp_path / "edge-profile"))
    write_ui(data, stability_window_ms=1000)

    def run(url: str, *, window: bool = False, enter: str = "\n",
            extra: tuple[str, ...] = ()) -> tuple[int, str, dict]:
        monkeypatch.setenv("HARNESS_COPILOT_URL", url)
        if window:
            monkeypatch.delenv("HARNESS_TEST_HEADLESS")
        monkeypatch.setattr("sys.stdin", io.StringIO(enter))  # the person's Enter, or nothing
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):  # `say` writes to stderr
            code = probe.main(["speed", "--questions", str(QUESTIONS), *extra])
        files = sorted((data / "copilot").glob("probe-speed-[0-9]*.json"))
        return code, out.getvalue(), json.loads(files[-1].read_text(encoding="utf-8"))

    return probe, data, run


def test_speed_measures_both_paths_with_the_fixed_prompts_only(speed, copilot_app):
    probe, data, run = speed
    code, out, result = run(copilot_app.url())
    assert code == 0, out
    sends = probe.speed_sends(QUESTIONS)
    assert sends == 12 + 3 * QUESTIONS
    assert result["sends_used"] == sends == copilot_app.prompt_count  # announced = received
    assert {p.prompt for p in copilot_app.prompts} <= set(probe.SPEED_PROMPTS)
    assert f"at most {sends} fixed prompts" in out.split("end signals, conversation")[0]  # said before sending
    assert result["complete"] is True and result["headless"] == "usable"
    on = result["arms"]["on"]
    assert [r["path"] for r in on] == ["reload", "reuse"]
    assert all(r["end"] == "signal" for r in on)
    assert all(r["end"] == "window" and r["path"] == "reload" for r in result["arms"]["off"])
    measurement = load_measurement(data)
    assert measurement.fast_end is not None and measurement.fast_end.sends == 12
    assert measurement.fast_end.modes == ["auto"]  # no selector measured: auto only
    assert measurement.tab_reuse is not None and measurement.tab_reuse.questions == QUESTIONS - 1
    assert len(list((data / "copilot").glob("ui-*.json"))) == 1  # the old one, kept dated
    assert "phase (ms, median of questions 2..N)" in out and "headless: usable" in out
    assert f"sends: {sends} used of {sends} planned" in out
    raw = next((data / "copilot").glob("probe-speed-*.json")).read_text(encoding="utf-8")
    for text in (out, raw):
        for canary in (*CANARIES, "127.0.0.1", "word1"):
            assert canary not in text


def test_speed_refuses_a_fast_end_that_would_cut_a_late_block(speed, copilot_app):
    """A block appended 1.5 s after the end: every short window fires before it, so no fast
    end is written and the second arm keeps the old window (and the whole text)."""
    probe, data, run = speed
    code, out, result = run(copilot_app.url(late_block_ms="1500"))
    assert result["fast_end_candidate"] is None, result["fast_rules"]
    assert all(not s["valid"] and s["early"] > 0 for s in result["fast_rules"].values())
    assert all(r["whole"] for arm in result["arms"].values() for r in arm)
    assert all(r["end"] == "window" for r in result["arms"]["on"])
    measurement = json.loads(measurement_path(data).read_text(encoding="utf-8"))
    assert measurement.get("fast_end") is None and measurement.get("tab_reuse") is not None
    assert "fast end chosen: none" in out


def test_speed_without_measured_locators_sends_nothing(speed, copilot_app):
    probe, data, run = speed
    measurement_path(data).unlink()
    code, out, result = run(copilot_app.url())
    assert code != 0 and copilot_app.prompt_count == 0
    assert result["complete"] is False


@pytest.mark.parametrize("page, reason", [("login", "AuthenticationRequired"),
                                          ("other", "ProviderTimeout")])
def test_headless_that_behaves_differently_is_reported_not_usable(speed, copilot_app, page, reason):
    """With a window the page works; without one it shows a sign-in page or another
    structure. The provider refuses through its guards and sends nothing there; the run
    reports "not usable" and no time for that variant."""
    probe, data, run = speed
    copilot_app.headless_page = page
    code, out, result = run(copilot_app.url(), window=True)
    assert result["arms"]["on"] and all(r["whole"] for r in result["arms"]["on"])
    assert result["headless"] == f"not usable ({reason})"
    assert result["arms"]["headless"][0]["sends"] == 0
    assert copilot_app.prompt_count == 12 + 2 * QUESTIONS  # nothing typed without a window
    assert copilot_app.headless_hits.count(True) >= 1 and copilot_app.headless_hits.count(False) >= 2
    assert "headless: not usable" in out
    row = next(line for line in out.splitlines() if line.strip().startswith("total"))
    assert row.split()[-1] == "n/a"
    # What it writes is from the window arms only.
    assert load_measurement(data).tab_reuse is not None


# -- review 2026-11-28, finding 1d ------------------------------------------------------------


def test_speed_without_the_persons_enter_sends_nothing(speed, copilot_app):
    probe, data, run = speed
    code, out, result = run(copilot_app.url(), enter="")
    assert code != 0 and copilot_app.prompt_count == 0
    assert "not confirmed: nothing was sent" in out and result["error"] == "ProbeFailure"
    assert load_measurement(data).fast_end is None


def test_speed_refuses_a_fast_end_on_a_page_that_pauses_between_phases(speed, copilot_app):
    """The stop control hides for 0.8 s in the middle of every reply: the 500 ms rule fires in
    that gap and the signal comes back busy, so it is early on every send and never chosen;
    the 1000 ms rule outlasts the gap and stays valid (control: the rule is not refused for
    nothing). The window is the real page's 4 s: with the fixture's 1 s the old rule itself
    would end inside the 2.6 s pause."""
    probe, data, run = speed
    write_ui(data, stability_window_ms=4000)
    code, out, result = run(copilot_app.url(pause_ms="2600", flicker_ms="800"), extra=("--skip-headless",))
    rules = result["fast_rules"]
    assert rules["stop_hidden+500"]["early"] == 12 and not rules["stop_hidden+500"]["valid"]
    assert rules["stop_hidden+1000"]["early"] == 0 and rules["stop_hidden+1000"]["valid"]
    chosen = result["fast_end_candidate"]
    assert chosen is not None and (chosen["signal"], chosen["confirm_ms"]) != ("stop_hidden", 500)
    assert all(r["whole"] for arm in result["arms"].values() for r in arm), (chosen, result["arms"])
    assert result["early_endings"] == 0


def test_speed_refuses_a_fast_end_that_a_late_read_contradicts(speed, copilot_app):
    """A block 5 s after the end: sampling stops 4 s after the reply held still, before it;
    the read 5 s after that sees it, so every rule that fired before it is early."""
    probe, data, run = speed
    code, out, result = run(copilot_app.url(late_block_ms="5000"), extra=("--skip-headless",))
    assert result["fast_end_candidate"] is None, result["fast_rules"]
    assert all(s.get("late_changed") for s in result["end_sends"])
    assert measurement_path(data).is_file() and load_measurement(data).fast_end is None


def test_speed_with_deep_measured_sends_two_in_deep_and_records_the_modes(speed, copilot_app):
    probe, data, run = speed
    menu = json.loads(MENU.read_text(encoding="utf-8"))
    write_ui(data, stability_window_ms=1000, response_mode=menu)
    code, out, result = run(copilot_app.url(modes="menu"), extra=("--rounds", "1", "--skip-headless"))
    assert code == 0, out
    sends = probe.speed_sends(QUESTIONS, rounds=1, headless=False, deep=True)
    assert sends == 6 + 2 + 2 * QUESTIONS == result["sends_used"] == copilot_app.prompt_count
    assert [s["mode"] for s in result["end_sends"]] == ["auto"] * 6 + ["deep"] * 2
    assert [p.mode for p in copilot_app.prompts][6:8] == ["deep", "deep"]
    assert load_measurement(data).fast_end.modes == ["auto", "deep"]
    assert result["headless"] == "skipped (--skip-headless)"


def test_the_smallest_run_is_stated_in_the_help(speed, capsys):
    probe, data, run = speed
    with pytest.raises(SystemExit):
        probe.main(["speed", "--help"])
    text = " ".join(capsys.readouterr().out.split())
    # argparse may break the line inside "--skip-headless"
    assert "--rounds 1 --questions 2 --skip-" in text and "10 sends, 12 with deep" in text
    assert "--skip-headless" in text and "--rounds" in text
