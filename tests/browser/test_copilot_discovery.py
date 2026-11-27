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


def test_discovery_on_a_feed_with_optimistic_echo_and_a_link_to_new_chat(bare, copilot_app, monkeypatch):
    """The shape seen on a real page: the sent message is replaced by a new copy that holds
    the marker too, turns sit deep in a virtualised feed, and "new chat" is a plain link to
    the app's own path. Discovery must not take the prompt for the reply."""
    probe, data = bare
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url("/feed"))
    code, out, err = run_step(probe, "discover")
    assert code == 0, out + err
    found = discovered(data)
    assert found["missing"] == []
    locators = found["locators"]
    assert locators["send_with"] == "enter"
    assert "stop" in locators and "response_done_control" in locators
    assert found["facts"]["new_chat_verified"] is True
    # the turn locators match the right sides: the reply locator never matches a message
    # that holds a prompt (the prompts carry the markers too)
    assert found["facts"]["user_hits"] == [1, 1]
    assert "user_turn" in locators and "assistant_turn" in locators
    assert locators["user_turn"] != locators["assistant_turn"]
    # the page puts the conversation id in its address when the server answers, before the
    # reply ends: discovery records when, as times only
    facts = found["facts"]
    assert facts["id_in_url_after_send_ms"] is not None
    assert facts["id_in_url_after_send_ms"] <= facts["reply_end_after_send_ms"]
    assert "conversation id in URL after send:" in out
    assert [r.prompt.strip() for r in copilot_app.prompts] == list(probe.PROMPTS[:2])
    for text in (out, err):
        for canary in CANARIES:
            assert canary not in text
        assert "[href" not in text and "127.0.0.1" not in text


def test_measure_on_the_feed_shape(bare, copilot_app, monkeypatch):
    probe, data = bare
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url("/feed"))
    code, out, err = run_step(probe, "measure")
    assert code == 0, out + err
    files = sorted((data / "copilot").glob("probe-measure-*.json"))
    measure = json.loads(files[-1].read_text(encoding="utf-8"))
    assert measure["complete"] is True
    assert measure["turns_visible_after_reopen"] == [4]
    assert measure["identity_recoverable"] is True
    assert measure["conversation_ref"]["prefix"] == ["feed", "thread"]
    assert measure["reopened_from_identifier"] == 1
    assert measure["sizes"] == [{"chars": 2000, "editor_chars": 2000, "accepted": True}]
    # P6 alone, with the measured locators: one send per size, nothing else
    sent = copilot_app.prompt_count
    code, out, err = run_step(probe, "sizes")
    assert code == 0, out + err
    assert "P6 prompt sizes: 2000:ok  max accepted: 2000" in out
    assert copilot_app.prompt_count == sent + 1
    first = [s for s in measure["sends"] if s["prompt"] == 1]
    assert first and all(s["id_in_url_ms"] is not None for s in first)
    later = [s for s in measure["sends"] if s["prompt"] > 1]
    assert all(s["id_in_url_ms"] is None for s in later)  # the address no longer changes


def test_a_lost_key_press_is_repeated_once_and_never_sends_twice(bare, copilot_app, monkeypatch):
    """The first Enter after each page load is lost (the page is still rendering): the probe
    sees that nothing left the editor and no turn was added, presses once more, and the
    server receives each prompt exactly once."""
    probe, data = bare
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url("/feed", lose_first="1"))
    code, out, err = run_step(probe, "measure")
    files = sorted((data / "copilot").glob("probe-measure-*.json"))
    measure = json.loads(files[-1].read_text(encoding="utf-8"))
    assert code == 0, out + err
    firsts = [s for s in measure["sends"] if s["prompt"] == 1]
    assert firsts and all(s["resubmitted"] and s["sent_confirmed"] for s in firsts)
    assert all(not s["resubmitted"] for s in measure["sends"] if s["prompt"] > 1)
    assert copilot_app.prompt_count == 2 + 4 + 1  # discovery, one conversation, one size
    assert "key press lost and repeated: 1" in out


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
    assert measure["conversation_ref"] == {
        "kind": "path_segment", "index": 2, "prefix": ["chat", "conversation"],
    }
    assert measure["reopened_from_identifier"] == 1  # reopened from the id, not the URL
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


def test_a_guest_address_is_refused_with_the_chat_path_measured_at_login(
    bare, copilot_app, monkeypatch
):
    """The configured address is the host's landing page, which offers to sign in even with a
    session: every step that would type says so and suggests the path where the chat was ready
    when the probe's login step ran. Nothing is typed."""
    probe, data = bare
    out_dir = data / "copilot"
    out_dir.mkdir(parents=True)
    (out_dir / "probe-login-20261124T000000000000Z.json").write_text(
        json.dumps({"step": "login", "ready_path": "/app"}), encoding="utf-8"
    )
    monkeypatch.setenv("HARNESS_COPILOT_URL", copilot_app.url("/guest"))
    code, out, err = run_step(probe, "discover")
    assert code == 1
    assert "guest page" in err
    assert f"set HARNESS_COPILOT_URL={copilot_app.base}/app" in err
    assert copilot_app.base not in out  # the summary stays tenant-free
    code, out, err = run_step(probe, "structure")
    assert code == 0 and f"{copilot_app.base}/app" in err
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
