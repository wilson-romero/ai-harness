"""Locator discovery by behaviour, against two synthetic page shapes (spec `copilot-ui-probe`).

The two shapes share no selector: one sends with a button and names its parts with ids and
classes, the other sends with Enter from a contenteditable paragraph and uses `data-qa`
attributes. Discovery has to find both from what the pages do.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout

import pytest

from tests.browser.test_copilot_probe import TENANT_CANARY, clean_env, load_probe, make_fast
from tests.copilot_app import CANARIES

pytestmark = pytest.mark.edge


@pytest.fixture
def bare(tmp_path, monkeypatch, copilot_app):
    """A probe with no hand-written locators at all."""
    probe = load_probe()
    data = tmp_path / "data"
    clean_env(monkeypatch, HARNESS_DATA_DIR=str(data))
    make_fast(monkeypatch, probe, CONVERSATIONS=1, SIZES=(2000,))
    return probe, data


def run_step(probe, step: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = probe.main([step])
    return code, out.getvalue(), err.getvalue()


def discovered(data) -> dict:
    return json.loads((data / "copilot" / "discovered.json").read_text(encoding="utf-8"))


SHAPES = {
    # shape: (url parameters, send method, stop expected, aria-busy on another element)
    "button-send, ids and classes, stop": ({}, "button", True, False),
    "enter-send, contenteditable paragraph, data-qa, no stop": ({"ui": "enter"}, "enter", False, True),
    "enter-send, contenteditable paragraph, data-qa, stop": (
        {"ui": "enter", "stop": "1"}, "enter", True, True,
    ),
}


@pytest.mark.parametrize("shape", SHAPES)
def test_discovery_finds_the_controls_by_behaviour(shape, bare, copilot_app, monkeypatch):
    probe, data = bare
    params, method, stop, busy_region = SHAPES[shape]
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url(tenant=TENANT_CANARY, **params))
    code, out, err = run_step(probe, "discover")
    assert code == 0, out + err
    found = discovered(data)
    assert found["missing"] == []
    locators = found["locators"]
    assert locators["send_with"] == method
    assert ("stop" in locators) is stop
    assert ("busy_region" in locators) is busy_region
    assert "response_done_control" in locators
    assert found["facts"]["new_chat_verified"] is True
    assert found["facts"]["conversation_ref"]["kind"] == "path_segment"
    # the two first fixed prompts, nothing else
    assert [r.prompt.strip() for r in copilot_app.prompts] == list(probe.PROMPTS[:2])
    # the summary is tenant-free: no canary, no selector, no address
    for text in (out, err):
        for canary in (*CANARIES, TENANT_CANARY):
            assert canary not in text
        assert "[data-" not in text and "css" not in text and "127.0.0.1" not in text


def test_measure_discovers_then_measures(bare, copilot_app, monkeypatch):
    probe, data = bare
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url(ui="enter", stop="1"))
    code, out, err = run_step(probe, "measure")
    assert code == 0, out + err
    files = sorted((data / "copilot").glob("probe-measure-*.json"))
    measure = json.loads(files[-1].read_text(encoding="utf-8"))
    assert measure["complete"] is True
    assert measure["discovery"]["sends"] == 2
    assert measure["locators"]["send_with"] == "enter"
    assert measure["end_signal"] is not None
    assert measure["conversation_ref"] == {"kind": "path_segment", "index": 2}
    assert copilot_app.prompt_count == 2 + 4 + 1  # discovery, one conversation, one size
    # a second measure reuses what was discovered: no new discovery sends
    before = copilot_app.prompt_count
    assert run_step(probe, "measure")[0] == 0
    assert copilot_app.prompt_count == before + 4 + 1


def test_discovery_reports_a_missing_echo_and_does_not_guess(bare, copilot_app, monkeypatch):
    probe, data = bare
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url(ui="enter", echo="0"))
    code, out, err = run_step(probe, "discover")
    assert code == 1
    found = discovered(data)
    assert found["missing"] == ["user_turn"]
    assert "user_turn" not in found["locators"]
    assert "missing: user_turn" in out
    asks = [line for line in err.splitlines() if line.startswith("  user_turn:")]
    assert len(asks) == 1  # one instruction, for that one item
    # measure does not guess either: it stops before sending and names the same item
    sent = copilot_app.prompt_count
    code, out, err = run_step(probe, "measure")
    assert code == 1 and "locators missing: user_turn" in out
    assert copilot_app.prompt_count == sent


def test_a_signed_out_page_is_never_typed_into(bare, copilot_app, monkeypatch):
    """A landing page that offers to sign in may still show a prompt box. Neither discovery
    nor a measurement with hand-written locators may type into it."""
    probe, data = bare
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url(ui="signedout"))
    code, out, err = run_step(probe, "discover")
    assert code == 1
    assert "missing: signed_in" in out and "signed out" in err
    assert not (data / "copilot" / "discovered.json").exists()
    code, out, err = run_step(probe, "structure")
    assert code == 0 and "signed-out hints: 0" not in out
    (data / "copilot" / "candidates.json").write_text(json.dumps({
        "composer": {"css": "textarea"},
        "send_with": "enter",
        "new_conversation": {"css": "header a"},
        "user_turn": {"css": "main p"},
        "assistant_turn": {"css": "main div"},
    }), encoding="utf-8")
    code, out, err = run_step(probe, "measure")
    assert code == 1 and "signed out" in err
    assert copilot_app.prompt_count == 0


def test_the_chat_pages_show_no_signed_out_hint(bare, copilot_app, monkeypatch):
    probe, _ = bare
    for params in ({}, {"ui": "enter"}):
        monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url(**params))
        code, out, _ = run_step(probe, "structure")
        assert code == 0 and "signed-out hints: 0" in out


def test_a_hand_written_item_fills_the_gap_discovery_left(bare, copilot_app, monkeypatch):
    probe, data = bare
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url(ui="enter", echo="0"))
    assert run_step(probe, "discover")[0] == 1
    (data / "copilot" / "candidates.json").write_text(
        json.dumps({"user_turn": {"css": '[data-author="human"]'}}), encoding="utf-8"
    )
    sent = copilot_app.prompt_count
    code, out, err = run_step(probe, "measure")
    assert code == 0, out + err
    assert copilot_app.prompt_count == sent + 4 + 1  # no second discovery
