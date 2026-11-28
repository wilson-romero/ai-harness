"""The probe's `response-mode` step against the synthetic chat page (change response-mode, D7).

The person is played by two stand-ins: one opens the selector in the page and "presses Enter",
the other answers which option is which mode, by the synthetic labels. The server is the
oracle: it counts the prompts and records every mode the page switched to.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from harness.providers.copilot_ui import load_measurement, measurement_path
from tests.browser.test_copilot_probe import SYNTHETIC_UI, clean_env, load_probe
from tests.copilot_app import CANARIES, SyntheticCopilot

pytestmark = pytest.mark.edge

LABELS = {"auto": "Synthetic automatic", "quick": "Synthetic brisk", "deep": "Synthetic pondering"}
OPENERS = "#synthetic-mode-trigger, [data-testid='synthetic-mode-picker']"


async def person_opens_the_selector(context) -> bool:
    page = [p for p in context.pages if not p.is_closed()][-1]
    await page.locator(OPENERS).first.click(timeout=15_000)
    return True


def person_maps_by_label(options: list[dict]) -> dict[str, int]:
    names = [option["name"] for option in options]
    return {mode: names.index(label) for mode, label in LABELS.items() if label in names}


@pytest.fixture
def probe_env(tmp_path, monkeypatch):
    probe = load_probe()
    data = tmp_path / "data"
    clean_env(monkeypatch, HARNESS_DATA_DIR=str(data))
    target = measurement_path(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(SYNTHETIC_UI.read_text("utf-8"), "utf-8")
    monkeypatch.setattr(probe, "wait_for_person", person_opens_the_selector)
    monkeypatch.setattr(probe, "choose_modes", person_maps_by_label)
    return probe, data


def run_step(probe, monkeypatch, app: SyntheticCopilot, **page: str) -> tuple[int, str]:
    monkeypatch.setenv("HARNESS_COPILOT_URL", app.url("/app", **page))
    out = io.StringIO()
    with redirect_stdout(out):
        code = probe.main(["response-mode"])
    return code, out.getvalue()


def saved_texts(data: Path, out: str) -> list[str]:
    files = [p.read_text("utf-8") for p in (data / "copilot").glob("*.json")]
    return [out, *files]


def test_the_menu_shape_is_measured_without_sending(probe_env, copilot_app, monkeypatch):
    """Scenario «Medida en la página sintética»."""
    probe, data = probe_env
    code, out = run_step(probe, monkeypatch, copilot_app, modes="menu", mode_start="quick")
    assert code == 0, out
    control = load_measurement(data).response_mode
    assert control is not None
    assert set(control.options) == {"auto", "quick", "deep"}
    assert control.options["deep"].role == "menuitemradio"
    assert control.options["deep"].name == LABELS["deep"]
    assert control.readback == "checked_option"  # the button's label never names the mode
    assert copilot_app.prompt_count == 0  # nothing was sent
    assert copilot_app.mode_events[-1] == "quick"  # the page is left in the mode it was in
    assert set(copilot_app.mode_events) == {"auto", "quick", "deep"}  # each mode was confirmed
    assert len(list((data / "copilot").glob("ui-*.json"))) == 1  # the old measurement, kept
    assert "response mode: confirmed auto, quick, deep" in out
    assert "left as found: yes" in out
    for text in saved_texts(data, out):
        for canary in CANARIES:
            assert canary not in text


def test_the_listbox_shape_reads_the_mode_from_the_button(probe_env, copilot_app, monkeypatch):
    probe, data = probe_env
    code, out = run_step(probe, monkeypatch, copilot_app, modes="listbox")
    assert code == 0, out
    control = load_measurement(data).response_mode
    assert control.readback == "trigger_label"
    assert control.trigger.test_id == "synthetic-mode-picker"
    assert control.labels["quick"] == LABELS["quick"]
    assert copilot_app.prompt_count == 0 and copilot_app.mode_events[-1] == "auto"


def test_a_page_without_a_selector_leaves_the_measurement_alone(probe_env, copilot_app,
                                                                monkeypatch):
    """Scenario «Sin control que medir»."""
    probe, data = probe_env
    before = measurement_path(data).read_bytes()

    async def nothing_to_open(context) -> bool:
        return True

    monkeypatch.setattr(probe, "wait_for_person", nothing_to_open)
    code, out = run_step(probe, monkeypatch, copilot_app)
    assert code == 1
    assert "response mode: no open selector found" in out
    assert measurement_path(data).read_bytes() == before
    assert copilot_app.prompt_count == 0


def test_a_selector_that_does_not_change_is_not_written(probe_env, copilot_app, monkeypatch):
    """Negative control: the options are found, but choosing one changes nothing, so no
    locator is confirmed and ui.json stays as it was."""
    probe, data = probe_env
    before = measurement_path(data).read_bytes()
    code, out = run_step(probe, monkeypatch, copilot_app, modes="menu", mode_stuck="1")
    assert code == 1
    assert "not confirmed" in out
    assert measurement_path(data).read_bytes() == before
    result = json.loads(sorted((data / "copilot").glob("probe-response-mode-*.json"))[-1]
                        .read_text("utf-8"))
    assert result["complete"] is False and result.get("response_mode") is None


def test_measure_keeps_the_measured_mode_control(probe_env, copilot_app, monkeypatch, tmp_path):
    """`assemble` keeps the latest complete response-mode result in a rebuilt ui.json."""
    probe, data = probe_env
    code, _ = run_step(probe, monkeypatch, copilot_app, modes="menu")
    assert code == 0
    found = probe.response_mode_of(data / "copilot")
    assert found["response_mode"]["readback"] == "checked_option"
    assert probe.response_mode_of(tmp_path) == {}


# -- review 2026-11-27: the probe writes only a reading that tells modes apart, on a page that
# -- stayed in its conversation and was left as found (findings 3 and 8) -------------------------


def assert_not_written(data: Path, before: bytes, code: int, out: str, says: str) -> None:
    assert code == 1, out
    assert says in out
    assert measurement_path(data).read_bytes() == before
    result = json.loads(sorted((data / "copilot").glob("probe-response-mode-*.json"))[-1]
                        .read_text("utf-8"))
    assert result["complete"] is False and result.get("response_mode") is None


def test_a_reading_that_cannot_tell_modes_apart_is_not_written(probe_env, copilot_app,
                                                               monkeypatch):
    """Finding 3: the opener always carries the label of deep, and only deep (the mode the
    page is in) is mapped; reading deep after choosing deep proves nothing."""
    probe, data = probe_env
    before = measurement_path(data).read_bytes()
    monkeypatch.setattr(probe, "choose_modes", lambda options: {
        "deep": [o["name"] for o in options].index(LABELS["deep"])})
    code, out = run_step(probe, monkeypatch, copilot_app, modes="menu", mode_start="deep",
                         mode_label=LABELS["deep"])
    assert_not_written(data, before, code, out, "not confirmed")


@pytest.mark.parametrize("page", [{"mode_navigate": "1"}, {"mode_append": "1"}],
                         ids=["address", "turns"])
def test_a_selector_that_changes_the_conversation_is_not_written(probe_env, copilot_app,
                                                                 monkeypatch, page):
    probe, data = probe_env
    before = measurement_path(data).read_bytes()
    code, out = run_step(probe, monkeypatch, copilot_app, modes="menu", **page)
    assert_not_written(data, before, code, out, "changed the conversation")
    assert copilot_app.prompt_count == 0


def test_an_unknown_starting_mode_is_not_written(probe_env, copilot_app, monkeypatch):
    """The page starts in auto, which the person does not map: the probe cannot leave the
    page as it found it, so nothing is written."""
    probe, data = probe_env
    before = measurement_path(data).read_bytes()
    monkeypatch.setattr(probe, "choose_modes", lambda options: {
        mode: [o["name"] for o in options].index(LABELS[mode]) for mode in ("quick", "deep")})
    code, out = run_step(probe, monkeypatch, copilot_app, modes="menu")
    assert_not_written(data, before, code, out, "starting mode")


def test_without_a_measurement_the_turns_cannot_be_checked(probe_env, copilot_app, monkeypatch):
    """No ui.json yet: the user turns cannot be located, so whether choosing a mode changes
    the conversation is unknown; the result is not complete."""
    probe, data = probe_env
    measurement_path(data).unlink()
    code, out = run_step(probe, monkeypatch, copilot_app, modes="menu")
    assert code == 1, out
    assert "measure first" in out
    result = json.loads(sorted((data / "copilot").glob("probe-response-mode-*.json"))[-1]
                        .read_text("utf-8"))
    assert result["complete"] is False and result.get("response_mode") is None
    assert probe.response_mode_of(data / "copilot") == {}
