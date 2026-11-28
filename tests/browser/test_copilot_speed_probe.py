"""The probe's `speed` step against the synthetic chat (change copilot-turn-speed, D5): one
command measures the end signals with the fixed prompts, then the same fixed prompts with the
optimisations off, on, and on without a window, and prints the phase table of each.

The synthetic server counts every prompt it receives: the oracle for "nothing beyond the
fixed prompts, as many as announced".
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest

from harness.providers.copilot_ui import load_measurement, measurement_path
from tests.browser.test_copilot_probe import clean_env, load_probe
from tests.browser.test_copilot_provider import write_ui
from tests.copilot_app import CANARIES

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

    def run(url: str, *, window: bool = False) -> tuple[int, str, dict]:
        monkeypatch.setenv("HARNESS_COPILOT_URL", url)
        if window:
            monkeypatch.delenv("HARNESS_TEST_HEADLESS")
        out = io.StringIO()
        with redirect_stdout(out):
            code = probe.main(["speed", "--questions", str(QUESTIONS)])
        files = sorted((data / "copilot").glob("probe-speed-[0-9]*.json"))
        return code, out.getvalue(), json.loads(files[-1].read_text(encoding="utf-8"))

    return probe, data, run


def test_speed_measures_both_paths_with_the_fixed_prompts_only(speed, copilot_app):
    probe, data, run = speed
    code, out, result = run(copilot_app.url())
    assert code == 0, out
    sends = probe.speed_sends(QUESTIONS)
    assert sends == 8 + 3 * QUESTIONS
    assert result["sends_used"] == sends == copilot_app.prompt_count  # announced = received
    assert {p.prompt for p in copilot_app.prompts} <= set(probe.PROMPTS)
    assert result["complete"] is True and result["headless"] == "usable"
    on = result["arms"]["on"]
    assert [r["path"] for r in on] == ["reload", "reuse"]
    assert all(r["end"] == "signal" for r in on)
    assert all(r["end"] == "window" and r["path"] == "reload" for r in result["arms"]["off"])
    measurement = load_measurement(data)
    assert measurement.fast_end is not None and measurement.fast_end.sends == 8
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
    assert copilot_app.prompt_count == 8 + 2 * QUESTIONS  # nothing typed without a window
    assert copilot_app.headless_hits.count(True) >= 1 and copilot_app.headless_hits.count(False) >= 2
    assert "headless: not usable" in out
    row = next(line for line in out.splitlines() if line.strip().startswith("total"))
    assert row.split()[-1] == "n/a"
    # What it writes is from the window arms only.
    assert load_measurement(data).tab_reuse is not None
