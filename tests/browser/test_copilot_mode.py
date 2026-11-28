"""The response mode on the synthetic chat page (change response-mode, D3 and D4).

The synthetic server is the oracle: the page posts, with each prompt, the mode it was in when
it sent it, and the server counts the prompts. Nothing here talks to a real service.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.browser.edge import EdgeLauncher
from harness.providers.copilot_ui import measurement_path
from tests.conftest import REPO_ROOT, query
from tests.copilot_app import SyntheticCopilot

pytestmark = pytest.mark.edge

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "copilot_ui"
MENU = json.loads((FIXTURES / "response-mode-menu.json").read_text("utf-8"))
LISTBOX = json.loads((FIXTURES / "response-mode-listbox.json").read_text("utf-8"))


def write_ui(data_dir: Path, control: dict | None) -> None:
    data = json.loads((FIXTURES / "ui.json").read_text("utf-8"))
    if control is not None:
        data["response_mode"] = control
    path = measurement_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def launches(monkeypatch) -> list:
    calls = []
    original = EdgeLauncher._launch

    async def spy(self, playwright, profile):
        calls.append(profile)
        return await original(self, playwright, profile)

    monkeypatch.setattr(EdgeLauncher, "_launch", spy)
    return calls


@pytest.fixture
def run(cli, copilot_app: SyntheticCopilot, tmp_path: Path, data_dir: Path):
    """`main.py` against the synthetic page with the given page options; returns
    (exit code, stdout, stderr)."""

    def call(*args: str, page: dict | None = None) -> tuple[int, str, str]:
        env = {
            "HARNESS_DATA_DIR": str(data_dir),
            "HARNESS_PROVIDER": "copilot_web",
            "HARNESS_COPILOT_URL": copilot_app.url("/app", **(page or {})),
            "HARNESS_EDGE_PROFILE": str(tmp_path / "edge-profile"),
            "HARNESS_REQUEST_TIMEOUT_S": "40",
            "HARNESS_TEST_HEADLESS": "1",
            "HARNESS_CONCISE_ANSWERS": "off",
        }
        return cli(*args, **env)

    return call


def new_session(run) -> str:
    code, out, err = run("session", "create", "Modo")
    assert code == 0, err
    return out.strip()


def modes_of(data_dir: Path, session_id: str) -> list[tuple]:
    return query(data_dir, "SELECT status, requested_mode, confirmed_mode FROM requests"
                           " WHERE session_id = ? ORDER BY started_at", (session_id,))


# -- set and confirmed before sending ----------------------------------------------------------


@pytest.mark.parametrize("shape, control, mode", [
    ("menu", MENU, "deep"),
    ("listbox", LISTBOX, "quick"),
])
def test_the_mode_is_set_and_confirmed_before_sending(run, data_dir, copilot_app, shape, control,
                                                      mode):
    """Scenario «Modo puesto y confirmado», in both shapes of the control."""
    write_ui(data_dir, control)
    session_id = new_session(run)
    code, out, err = run("ask", session_id, "hola", "--mode", mode, page={"modes": shape})
    assert code == 0, err
    assert [p.mode for p in copilot_app.prompts] == [mode]  # the page was in it when it sent
    assert modes_of(data_dir, session_id) == [("completed", mode, mode)]


def test_a_page_already_in_the_mode_is_confirmed_as_it_is(run, data_dir, copilot_app):
    write_ui(data_dir, MENU)
    session_id = new_session(run)
    code, _, err = run("ask", session_id, "hola", "--mode", "deep",
                       page={"modes": "menu", "mode_start": "deep"})
    assert code == 0, err
    assert [p.mode for p in copilot_app.prompts] == ["deep"]
    assert modes_of(data_dir, session_id) == [("completed", "deep", "deep")]


def test_a_mode_the_page_applies_late_is_waited_for(run, data_dir, copilot_app):
    write_ui(data_dir, MENU)
    session_id = new_session(run)
    code, _, err = run("ask", session_id, "hola", "--mode", "quick",
                       page={"modes": "menu", "mode_late_ms": "1500"})
    assert code == 0, err
    assert [p.mode for p in copilot_app.prompts] == ["quick"]


# -- not confirmed: failed before anything is typed (SEC-07) ------------------------------------


def test_a_mode_that_cannot_be_confirmed_fails_before_typing(run, data_dir, copilot_app):
    """Scenario «El modo no se puede confirmar»."""
    write_ui(data_dir, MENU)
    session_id = new_session(run)
    code, out, err = run("ask", session_id, "hola", "--mode", "deep",
                         page={"modes": "menu", "mode_stuck": "1"})
    assert code != 0 and out == ""
    assert "could not be confirmed" in err and "nothing was sent" in err
    assert copilot_app.prompt_count == 0
    assert modes_of(data_dir, session_id) == [("failed", "deep", None)]
    assert query(data_dir, "SELECT status FROM sessions") != [("uncertain",)]


def test_a_control_missing_from_the_page_fails_before_typing(run, data_dir, copilot_app):
    """Scenario «El control no está en la página»: measured, but the page does not show it."""
    write_ui(data_dir, MENU)
    session_id = new_session(run)
    code, _, err = run("ask", session_id, "hola", "--mode", "quick")
    assert code != 0 and "nothing was sent" in err
    assert copilot_app.prompt_count == 0
    assert modes_of(data_dir, session_id) == [("failed", "quick", None)]


def test_without_the_measured_control_quick_and_deep_are_refused(run, data_dir, copilot_app,
                                                                launches):
    """Scenario «Copilot sin el control medido»: refused before anything is recorded or opened."""
    write_ui(data_dir, None)
    session_id = new_session(run)
    code, out, err = run("ask", session_id, "hola", "--mode", "deep", page={"modes": "menu"})
    assert code != 0 and out == ""
    assert "response-mode" in err and "Nothing was sent" in err
    assert query(data_dir, "SELECT count(*) FROM requests") == [(0,)]
    assert query(data_dir, "SELECT response_mode FROM sessions") == [("auto",)]
    assert launches == [] and copilot_app.prompt_count == 0


def test_without_the_measured_control_auto_leaves_the_page_as_it_is(run, data_dir, copilot_app):
    """Scenario «Automático siempre funciona»: the page stays in the mode it was in."""
    write_ui(data_dir, None)
    session_id = new_session(run)
    code, _, err = run("ask", session_id, "hola", "--mode", "auto",
                       page={"modes": "menu", "mode_start": "deep"})
    assert code == 0, err
    assert [p.mode for p in copilot_app.prompts] == ["deep"]  # untouched
    assert modes_of(data_dir, session_id) == [("completed", "auto", None)]


def test_auto_with_a_measured_automatic_option_brings_the_page_back(run, data_dir, copilot_app):
    """D2: a page left in deep by an earlier question goes back to its automatic option."""
    write_ui(data_dir, MENU)
    session_id = new_session(run)
    code, _, err = run("ask", session_id, "hola", page={"modes": "menu", "mode_start": "deep"})
    assert code == 0, err
    assert [p.mode for p in copilot_app.prompts] == ["auto"]
    assert modes_of(data_dir, session_id) == [("completed", "auto", "auto")]


def test_auto_never_blocks_a_question(run, data_dir, copilot_app):
    """D2, control: the automatic option cannot be confirmed; auto warns and goes on."""
    write_ui(data_dir, MENU)
    session_id = new_session(run)
    code, _, err = run("ask", session_id, "hola",
                       page={"modes": "menu", "mode_start": "deep", "mode_stuck": "1"})
    assert code == 0, err
    assert "automatic" in err and "warning" in err
    assert [p.mode for p in copilot_app.prompts] == ["deep"]


# -- the conversation does not change (SEC-02) ---------------------------------------------------


def test_choosing_a_mode_that_opens_another_conversation_fails_before_typing(run, data_dir,
                                                                            copilot_app):
    """Scenario «Elegir el modo abre otra conversación»."""
    write_ui(data_dir, MENU)
    session_id = new_session(run)
    page = {"modes": "menu", "mode_newchat": "1"}
    code, _, err = run("ask", session_id, "primera", page=page)  # auto: already auto, no click
    assert code == 0, err
    [(status, remote)] = query(data_dir, "SELECT status, remote_ref FROM sessions")
    assert remote is not None
    code, _, err = run("ask", session_id, "segunda", "--mode", "deep", page=page)
    assert code != 0 and "nothing was sent" in err and "conversation" in err
    assert copilot_app.prompt_count == 1  # only the first
    assert query(data_dir, "SELECT remote_ref FROM sessions") == [(remote,)]
    assert query(data_dir, "SELECT status FROM sessions") != [("closed",)]
    assert modes_of(data_dir, session_id)[-1] == ("failed", "deep", None)


# -- the page changes mode by itself (D4) --------------------------------------------------------


def test_a_fallback_during_the_answer_is_recorded(run, data_dir, copilot_app):
    """Scenario «La página vuelve a otro modo»."""
    write_ui(data_dir, MENU)
    session_id = new_session(run)
    code, out, err = run("ask", session_id, "hola", "--mode", "deep",
                         page={"modes": "menu", "mode_fallback": "quick"})
    assert code == 0 and out.strip(), err
    assert [p.mode for p in copilot_app.prompts] == ["deep"]  # it was sent in deep
    assert modes_of(data_dir, session_id) == [("completed", "deep", "quick")]
    assert "warning:" in err and "quick" in err
    _, history, _ = run("history", session_id)
    assert history.strip().split("\n")[-1].endswith("mode quick (asked deep)")


def test_no_fallback_keeps_the_mode(run, data_dir, copilot_app):
    """Control of the previous test, in the shape read from the button's label."""
    write_ui(data_dir, LISTBOX)
    session_id = new_session(run)
    code, _, err = run("ask", session_id, "hola", "--mode", "deep", page={"modes": "listbox"})
    assert code == 0, err
    assert modes_of(data_dir, session_id) == [("completed", "deep", "deep")]
    assert "switched" not in err


# -- review 2026-11-27 (independent review of 1572b0a) -------------------------------------------


def two_questions(run, data_dir, page: dict, mode: str) -> tuple[str, tuple[int, str, str]]:
    """A first question that binds the conversation (auto, no click), then a second one in
    `mode` that reopens it with the page options of `page`."""
    write_ui(data_dir, MENU)
    session_id = new_session(run)
    code, _, err = run("ask", session_id, "primera", page={"modes": "menu"})
    assert code == 0, err
    return session_id, run("ask", session_id, "segunda", "--mode", mode, page=page)


@pytest.mark.parametrize("mode, start", [("deep", "auto"), ("auto", "deep")])
def test_a_history_that_arrives_while_choosing_does_not_block(run, data_dir, copilot_app, mode,
                                                              start):
    """Finding 1: turns inserted above the thread while the mode is chosen (a late, virtualised
    history) are no new question; neither deep nor auto may fail for them."""
    session_id, (code, _, err) = two_questions(
        run, data_dir, {"modes": "menu", "mode_start": start, "mode_history": "1"}, mode)
    assert code == 0, err
    assert [p.mode for p in copilot_app.prompts] == ["auto", mode]
    assert modes_of(data_dir, session_id)[-1] == ("completed", mode, mode)


def test_a_new_turn_while_choosing_fails_before_typing(run, data_dir, copilot_app):
    """Control of finding 1: a user turn after the last one is a new question; nothing is
    typed and the session keeps its conversation."""
    session_id, (code, _, err) = two_questions(
        run, data_dir, {"modes": "menu", "mode_append": "1"}, "deep")
    assert code != 0 and "nothing was sent" in err and "conversation" in err
    assert copilot_app.prompt_count == 1
    assert modes_of(data_dir, session_id)[-1] == ("failed", "deep", None)


@pytest.mark.parametrize("mode, start", [("deep", "auto"), ("auto", "deep")])
def test_a_list_that_stays_open_fails_before_typing(run, data_dir, copilot_app, mode, start):
    """Finding 2: the list of modes does not close; nothing is typed under it, in any mode."""
    write_ui(data_dir, MENU)
    session_id = new_session(run)
    code, out, err = run("ask", session_id, "hola", "--mode", mode,
                         page={"modes": "menu", "mode_start": start, "mode_sticky": "1"})
    assert code != 0 and out == ""
    assert "stayed open" in err and "nothing was sent" in err
    assert copilot_app.prompt_count == 0
    assert modes_of(data_dir, session_id) == [("failed", mode, None)]


def test_a_disabled_option_leaves_no_list_open_under_the_prompt(run, data_dir, copilot_app):
    """Finding 2: the click on a disabled option fails; auto warns and goes on, with the list
    closed before anything is typed."""
    write_ui(data_dir, MENU)
    session_id = new_session(run)
    code, _, err = run("ask", session_id, "hola",
                       page={"modes": "menu", "mode_start": "deep", "mode_disabled": "auto"})
    assert code == 0, err
    assert "automatic response mode could not be confirmed" in err
    [prompt] = copilot_app.prompts
    assert prompt.mode == "deep" and prompt.list_open is False


def test_two_matching_options_leave_no_list_open(run, data_dir, copilot_app):
    write_ui(data_dir, MENU)
    session_id = new_session(run)
    code, _, err = run("ask", session_id, "hola",
                       page={"modes": "menu", "mode_start": "deep", "mode_twice": "1"})
    assert code == 0, err
    assert "2 visible elements" in err
    [prompt] = copilot_app.prompts
    assert prompt.list_open is False
    code, _, err = run("ask", session_id, "otra", "--mode", "quick",
                       page={"modes": "menu", "mode_twice": "1"})
    assert code != 0 and copilot_app.prompt_count == 1  # quick: failed, not typed


def test_a_reread_that_fails_keeps_the_mode_confirmed_before_sending(run, data_dir, copilot_app):
    """D4: after the answer the opener is doubled, so the mode cannot be read again; the
    record keeps the mode the prompt was sent in, with a warning."""
    write_ui(data_dir, MENU)
    session_id = new_session(run)
    code, _, err = run("ask", session_id, "hola", "--mode", "deep",
                       page={"modes": "menu", "mode_reread_fail": "1"})
    assert code == 0, err
    assert "could not be read again" in err
    assert modes_of(data_dir, session_id) == [("completed", "deep", "deep")]


def test_an_option_that_is_another_control_is_never_clicked(run, data_dir, copilot_app):
    """Finding 4: a loose locator (not exact) passes the schema but resolves to the new-chat
    button; the provider refuses to click it and nothing is typed."""
    loose = json.loads(json.dumps(MENU))
    loose["options"]["deep"] = {"role": "button", "name": "New synthetic chat", "exact": False}
    session_id, (code, _, err) = two_questions(run, data_dir, {"modes": "menu"}, "auto")
    assert code == 0, err
    write_ui(data_dir, loose)
    code, _, err = run("ask", session_id, "tercera", "--mode", "deep", page={"modes": "menu"})
    assert code != 0 and "nothing was sent" in err
    assert "another control" in err
    assert copilot_app.prompt_count == 2
    assert modes_of(data_dir, session_id)[-1] == ("failed", "deep", None)


async def test_a_retry_in_a_new_tab_does_not_keep_the_first_confirmation(copilot_app, data_dir,
                                                                        tmp_path, monkeypatch):
    """Finding 5: the first try confirms auto and then loses its tab before typing; the
    second try cannot confirm it. The record must not keep the first try's confirmation."""
    from harness.providers import copilot_web
    from tests.browser.test_copilot_conversation import Chat
    from tests.shell_support import ScriptedTerminal

    write_ui(data_dir, MENU)
    answers = iter([copilot_web.ResponseMode.AUTO, None])

    async def select(self, target):
        return next(answers)

    monkeypatch.setattr(copilot_web._ModeSelector, "select", select)
    original = copilot_web._Turn.put_prompt
    lost: list = []

    async def losing(self, page, *args):
        if not lost:
            lost.append(page)
            await page.close()
        return await original(self, page, *args)

    monkeypatch.setattr(copilot_web._Turn, "put_prompt", losing)
    chat = Chat(data_dir, tmp_path / "edge-profile", copilot_app.url("/app", modes="menu"),
                ScriptedTerminal(["uno ZQX-END-1", "/exit"]))
    try:
        assert await chat.conversation.run() == 0
        assert "trying once more in a new tab" in chat.terminal.text
        rows = [tuple(r) for r in chat.conn.execute(
            "SELECT status, requested_mode, confirmed_mode FROM requests")]
        assert rows == [("completed", "auto", None)]
    finally:
        chat.close()
