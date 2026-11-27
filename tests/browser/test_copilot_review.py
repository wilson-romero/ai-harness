"""Defects found by the independent review of 2026-11-26 (task 8.18), each reproduced with
the synthetic chat first: a new session landing on another session's conversation, a late
history making the previous answer pass for the new one, a lost conversation that keeps its
identifier in the address, and four rules the tests did not defend (M1 to M4)."""

from __future__ import annotations

import sqlite3

import pytest
from playwright.async_api import Error as PlaywrightError

from harness.providers import copilot_web
from tests.browser.test_copilot_provider import (  # noqa: F401  (fixtures)
    app,
    env,
    new_session,
    request_states,
    session_row,
)

pytestmark = pytest.mark.edge


def users_in(app, conversation: str) -> list[str]:
    return [t["text"] for t in app.conversations[conversation] if t["role"] == "user"]


# -- 1: a new session never types into another session's conversation (SEC-02) ------------------


def test_a_new_session_that_lands_on_another_conversation_types_nothing(cli, env, data_dir, app):
    first = new_session(cli, env, "A")
    code, out, err = cli("ask", first, "de A ZQX-END-1", **env)
    assert code == 0, err
    ref_a = session_row(data_dir, first)[1]
    second = new_session(cli, env, "B")
    restoring = env | {"HARNESS_COPILOT_URL": app.url("/app", restore="1")}
    code, out, err = cli("ask", second, "de B ZQX-END-2", **restoring)
    assert code != 0
    assert request_states(data_dir, second) == ["failed"]
    assert users_in(app, ref_a) == ["de A ZQX-END-1"] and app.prompt_count == 1
    assert session_row(data_dir, second)[1] is None
    assert "nothing was typed" in err


def test_control_a_new_session_on_the_new_chat_address_gets_its_own_conversation(cli, env, data_dir, app):
    first = new_session(cli, env, "A")
    assert cli("ask", first, "de A ZQX-END-1", **env)[0] == 0
    second = new_session(cli, env, "B")
    code, out, err = cli("ask", second, "de B ZQX-END-2", **env)
    assert code == 0, err
    ref_a, ref_b = session_row(data_dir, first)[1], session_row(data_dir, second)[1]
    assert ref_b and ref_b != ref_a and users_in(app, ref_b) == ["de B ZQX-END-2"]


# -- 2: a history that arrives late never passes the previous answer for the new one -------------


def test_a_late_history_does_not_return_the_previous_answer(cli, env, data_dir, app):
    session = new_session(cli, env)
    assert cli("ask", session, "primera ZQX-END-1", **env)[0] == 0
    late = env | {"HARNESS_COPILOT_URL": app.url("/app", slowhist="1")}
    code, out, err = cli("ask", session, "segunda ZQX-END-2", **late)
    assert code == 0, err
    assert "ZQX-END-2" in out and "ZQX-END-1" not in out, out[-120:]
    ref = session_row(data_dir, session)[1]
    assert users_in(app, ref) == ["primera ZQX-END-1", "segunda ZQX-END-2"]


def test_control_without_a_late_history_the_second_answer_is_read(cli, env, app):
    session = new_session(cli, env)
    assert cli("ask", session, "primera ZQX-END-1", **env)[0] == 0
    code, out, err = cli("ask", session, "segunda ZQX-END-2", **env)
    assert code == 0 and "ZQX-END-2" in out and "ZQX-END-1" not in out


def test_a_long_conversation_showing_only_its_last_turns_goes_on(cli, env, data_dir, app):
    """The real list is virtualized (D6): a reopened long conversation may show fewer turns
    than were completed. Some turns, stable, are enough; the answer is the new one."""
    session = new_session(cli, env)
    for n in (1, 2):
        assert cli("ask", session, f"q{n} ZQX-END-{n}", **env)[0] == 0
    partial = env | {"HARNESS_COPILOT_URL": app.url("/app", window="1")}
    code, out, err = cli("ask", session, "q3 ZQX-END-3", **partial)
    assert code == 0, err
    assert "ZQX-END-3" in out and "ZQX-END-2" not in out
    assert request_states(data_dir, session) == ["completed"] * 3


# -- 3: a lost conversation that keeps its identifier in the address -----------------------------


def test_a_lost_conversation_that_keeps_its_address_is_lost_before_typing(cli, env, data_dir, app):
    session = new_session(cli, env)
    assert cli("ask", session, "primera ZQX-END-1", **env)[0] == 0
    ref = session_row(data_dir, session)[1]
    del app.conversations[ref]  # the platform no longer has it
    keep = env | {"HARNESS_COPILOT_URL": app.url("/app", keepurl="1")}
    code, out, err = cli("ask", session, "segunda ZQX-END-2", **keep)
    assert code != 0
    assert request_states(data_dir, session) == ["completed", "failed"]
    assert session_row(data_dir, session) == ("closed", ref)
    assert app.prompt_count == 1  # nothing typed
    assert "could not be found again" in err


def test_the_address_is_checked_again_when_the_answer_ends(cli, env, data_dir, app):
    """A bound session with no turn completed in its conversation (its only question was
    uncertain) reopens a conversation that is gone but keeps its address: 0 turns are
    expected, the prompt is typed, and the platform files it in another conversation. The
    answer belongs to that other conversation: uncertain, not shown, the session not moved."""
    session = new_session(cli, env)
    conn = sqlite3.connect(data_dir / "harness.sqlite3")
    with conn:
        conn.execute("UPDATE sessions SET remote_ref = 'deadbeefdeadbeef' WHERE session_id = ?", (session,))
    conn.close()
    keep = env | {"HARNESS_COPILOT_URL": app.url("/app", keepurl="1")}
    code, out, err = cli("ask", session, "a ciegas ZQX-END-3", **keep)
    assert request_states(data_dir, session) == ["uncertain"]
    assert "ZQX-END-3" not in out
    assert session_row(data_dir, session)[1] == "deadbeefdeadbeef"


# -- M1 to M4: rules the review found undefended -------------------------------------------------


def test_m1_a_failure_during_the_click_is_uncertain_and_never_retried(cli, env, data_dir, app, monkeypatch):
    calls: list = []

    async def failing_submit(self, composer):
        calls.append(1)
        raise PlaywrightError("synthetic failure during the click")

    monkeypatch.setattr(copilot_web._Turn, "submit", failing_submit)
    session = new_session(cli, env)
    code, out, err = cli("ask", session, "clic ZQX-END-1", **env)
    assert request_states(data_dir, session) == ["uncertain"]
    assert calls == [1]


def test_m2_the_page_is_checked_again_between_typing_and_sending(cli, env, data_dir, app, monkeypatch):
    original = copilot_web._editor_length
    moved: list = []

    async def then_sign_in(composer):
        got = await original(composer)
        if not moved:  # right after typing, the page goes to the sign-in page
            moved.append(1)
            await composer.page.goto(app.login_url(app.url()), wait_until="load")
        return got

    monkeypatch.setattr(copilot_web, "_editor_length", then_sign_in)
    session = new_session(cli, env)
    code, out, err = cli("ask", session, "mira ZQX-END-1", **env)
    assert request_states(data_dir, session) == ["authentication_required"]
    assert app.prompt_count == 0 and app.login_events == []


def test_m3_a_lost_key_press_is_repeated_only_once(cli, env, data_dir, app, monkeypatch):
    calls: list = []
    original = copilot_web._Turn.submit

    async def counting(self, composer):
        calls.append(1)
        return await original(self, composer)

    monkeypatch.setattr(copilot_web._Turn, "submit", counting)
    session = new_session(cli, env)
    deaf = env | {"HARNESS_COPILOT_URL": app.url("/app", deaf="1"), "HARNESS_REQUEST_TIMEOUT_S": "20"}
    code, out, err = cli("ask", session, "sorda ZQX-END-1", **deaf)
    assert request_states(data_dir, session) == ["uncertain"]
    assert len(calls) == 2 and app.prompt_count == 0


def test_m4_an_editor_that_cuts_the_prompt_sends_nothing(cli, env, data_dir, app):
    session = new_session(cli, env)
    short = env | {"HARNESS_COPILOT_URL": app.url("/app", maxlength="5")}
    code, out, err = cli("ask", session, "un prompt de más de cinco ZQX-END-1", **short)
    assert code != 0
    assert request_states(data_dir, session) == ["failed"]
    assert app.prompt_count == 0 and "would have been cut" in err


# -- 6: no second press after the page reacted ------------------------------------------------


def test_a_page_that_puts_the_prompt_back_after_a_notice_gets_it_once(cli, env, data_dir, app):
    """Review 2026-11-26, item 6: the prompt arrives, the page shows an error notice as a turn
    and puts the prompt back in the editor. The one repeated press is for a press the page
    lost (nothing changed in the thread); here the thread changed, so it is not pressed again."""
    session = new_session(cli, env)
    bounce = env | {"HARNESS_COPILOT_URL": app.url("/app", bounce="1"), "HARNESS_REQUEST_TIMEOUT_S": "20"}
    code, out, err = cli("ask", session, "rebote ZQX-END-1", **bounce)
    assert request_states(data_dir, session) == ["uncertain"]
    assert app.prompt_count == 1
