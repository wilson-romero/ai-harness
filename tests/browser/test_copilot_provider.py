"""The Copilot Web provider end to end against the synthetic chat (tasks 4.2 to 6.2).

The synthetic server is the oracle: it records every prompt it receives, in which conversation,
and every key press or click on its sign-in page. Nothing here talks to a real service.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path

import pytest
from playwright._impl.out_of_process import PlaywrightClient
from playwright.async_api import Error as PlaywrightError

from harness.browser.edge import EdgeLauncher
from harness.config import Settings
from harness.core.service import SessionService
from harness.providers.copilot_ui import measurement_path
from harness.providers.copilot_web import REPLY_MAX_CHARS, CopilotWebProvider
from harness.providers.registry import provider_factory
from harness.storage.database import DATABASE_NAME, open_database
from tests.conftest import REPO_ROOT, query, run_main
from tests.copilot_app import CANARY_REPLY, HUGE_REPLY_CHARS, SyntheticCopilot, wait_until

pytestmark = pytest.mark.edge

SYNTHETIC_UI = REPO_ROOT / "tests" / "fixtures" / "copilot_ui" / "ui.json"
PROMPT_CANARY = "ZZ-CANARY-PROMPT-5521"
# The feed shape: Enter sends, a rich editor with zero-width anchors, an optimistic copy of the
# sent message, the identifier under a two-word path (see app-feed.html).
FEED_UI = {
    "locators": {
        "composer": {"css": ".rich-input"},
        "send_with": "enter",
        "new_conversation": {"css": "a.nav-entry[href='/feed']"},
        "user_turn": {"css": "article.turn-human"},
        "assistant_turn": {"css": "[data-part='bot-wrapper']"},
        "stop": {"css": ".halt-button"},
        "response_done_control": {"css": "[data-part='copy-reply']"},
        "busy_region": {"css": "[role='feed']"},
    },
    "conversation_ref": {"kind": "path_segment", "index": 2, "prefix": ["feed", "thread"]},
}


# -- set-up -------------------------------------------------------------------------------------


def write_ui(data_dir: Path, **changes) -> None:
    data = json.loads(SYNTHETIC_UI.read_text(encoding="utf-8"))
    data.update(changes)
    path = measurement_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def app(copilot_app: SyntheticCopilot, data_dir: Path) -> SyntheticCopilot:
    write_ui(data_dir)
    return copilot_app


@pytest.fixture
def env(app: SyntheticCopilot, tmp_path: Path, data_dir: Path) -> dict[str, str]:
    """Environment of a Copilot command against the synthetic chat."""
    return {
        "HARNESS_DATA_DIR": str(data_dir),
        "HARNESS_PROVIDER": "copilot_web",
        "HARNESS_COPILOT_URL": app.url(),
        "HARNESS_EDGE_PROFILE": str(tmp_path / "edge-profile"),
        "HARNESS_REQUEST_TIMEOUT_S": "40",
        "HARNESS_TEST_HEADLESS": "1",
    }


@pytest.fixture
def launches(monkeypatch) -> list:
    calls = []
    original = EdgeLauncher._launch

    async def spy(self, playwright, profile):
        calls.append(profile)
        return await original(self, playwright, profile)

    monkeypatch.setattr(EdgeLauncher, "_launch", spy)
    return calls


def new_session(cli, env, name="S") -> str:
    code, out, err = cli("session", "create", name, **env)
    assert code == 0, err
    return out.strip()


def session_row(data_dir: Path, session_id: str) -> tuple:
    return query(data_dir, "SELECT status, remote_ref FROM sessions WHERE session_id = ?", (session_id,))[0]


def request_states(data_dir: Path, session_id: str) -> list[str]:
    rows = query(
        data_dir,
        "SELECT status FROM requests WHERE session_id = ? ORDER BY started_at",
        (session_id,),
    )
    return [row[0] for row in rows]


def prompts_in(app: SyntheticCopilot, conversation: str) -> list[str]:
    return [turn["text"] for turn in app.conversations[conversation] if turn["role"] == "user"]


class Harness:
    """The service with a Copilot provider in this process, so a test can act on the browser
    (close it) while a question runs."""

    def __init__(self, env: dict[str, str], data_dir: Path) -> None:
        self.settings = Settings.from_env(env)
        self.launcher = EdgeLauncher.from_settings(self.settings)
        self.conn = open_database(data_dir)
        self.service = SessionService(
            self.conn,
            data_dir,
            lambda name: CopilotWebProvider(self.settings, self.launcher),
            "copilot_web",
            self.settings.request_timeout_s,
        )

    def close(self) -> None:
        self.conn.close()


@pytest.fixture
def harness(env, data_dir):
    made = []

    def build(**overrides: str) -> Harness:
        h = Harness(env | overrides, data_dir)
        made.append(h)
        return h

    yield build
    for h in made:
        h.close()


# -- 4.2: registered, checked before anything opens ---------------------------------------------


def test_session_created_with_copilot_opens_no_browser(cli, env, data_dir, launches):
    session_id = new_session(cli, env, "Integraciones")
    assert query(data_dir, "SELECT provider, status FROM sessions") == [("copilot_web", "created")]
    assert launches == []
    assert session_id


@pytest.mark.parametrize("measurement", ["absent", "incomplete"])
def test_missing_measurement_refuses_before_anything(cli, env, data_dir, launches, measurement):
    session_id = new_session(cli, env)
    path = measurement_path(data_dir)
    if measurement == "absent":
        path.unlink()
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(complete=False, missing=["end_signal"], end_signal=None)
        path.write_text(json.dumps(data), encoding="utf-8")
    code, out, err = cli("ask", session_id, "hola", **env)
    assert code != 0 and out == ""
    assert ("no Copilot measurement" in err) if measurement == "absent" else ("end_signal" in err)
    assert query(data_dir, "SELECT count(*) FROM requests") == [(0,)]
    assert launches == []


def test_prompt_too_long_is_refused_before_the_browser(cli, env, data_dir, launches, app):
    session_id = new_session(cli, env)
    code, out, err = cli(
        "ask", session_id, "x" * 51, **env, HARNESS_COPILOT_MAX_PROMPT_CHARS="50"
    )
    assert code != 0 and out == ""
    assert "51 characters" in err and "50" in err
    assert query(data_dir, "SELECT count(*) FROM requests") == [(0,)]
    assert launches == [] and app.prompt_count == 0


def test_the_variable_can_only_lower_the_measured_limit(cli, env, data_dir, launches):
    write_ui(data_dir, max_prompt_chars=40)
    session_id = new_session(cli, env)
    code, _, err = cli("ask", session_id, "y" * 41, **env, HARNESS_COPILOT_MAX_PROMPT_CHARS="5000")
    assert code != 0 and "40" in err and launches == []


def test_prompt_at_the_limit_arrives_whole(cli, env, app):
    session_id = new_session(cli, env)
    prompt = ("limite " * 1000)[:3000]
    code, out, err = cli("ask", session_id, prompt, **env, HARNESS_COPILOT_MAX_PROMPT_CHARS="3000")
    assert code == 0, err
    assert [p.prompt for p in app.prompts] == [prompt]



def test_suggestion_buttons_after_the_reply_are_not_part_of_it(cli, env, app):
    """Seen on the real page on 2026-11-26: three follow-up suggestions, rendered as buttons in
    a toolbar inside the answer's turn, came out as three lines of the answer. Controls are
    never the provider's words: buttons and toolbars are left out by structure, whatever
    their text or language."""
    session_id = new_session(cli, env)
    url = app.url("/app", chips="1")
    code, out, err = cli("ask", session_id, "sugerencias ZQX-END-5", **env | {"HARNESS_COPILOT_URL": url})
    assert code == 0, err
    assert "ZZ-CHIP" not in out and "Copy" not in out
    assert out.rstrip().endswith("ZQX-END-5"), out[-80:]

# -- 5.1: one remote conversation per session ---------------------------------------------------


def test_three_sessions_three_conversations(cli, env, data_dir, app):
    sessions = [new_session(cli, env, f"S{n}") for n in range(3)]
    for n, session_id in enumerate(sessions):
        code, out, err = cli("ask", session_id, f"pregunta sintetica {n} ZQX-END-{n}", **env)
        assert code == 0, err
        assert f"ZQX-END-{n}" in out
        # The visually hidden label before the reply is not part of the answer.
        assert out.startswith(CANARY_REPLY) and "ZZ-SR-LABEL" not in out
    refs = [session_row(data_dir, s)[1] for s in sessions]
    assert len(set(refs)) == 3 and None not in refs
    for n, ref in enumerate(refs):
        assert prompts_in(app, ref) == [f"pregunta sintetica {n} ZQX-END-{n}"]
    assert app.prompt_count == 3


def test_second_question_goes_to_the_same_conversation(cli, env, data_dir, app):
    session_id = new_session(cli, env)
    cli("ask", session_id, "primera ZQX-END-1", **env)
    ref = session_row(data_dir, session_id)[1]
    code, out, err = cli("ask", session_id, "segunda ZQX-END-2", **env)
    assert code == 0, err
    assert "ZQX-END-2" in out and "ZQX-END-1" not in out
    assert session_row(data_dir, session_id) == ("active", ref)
    assert prompts_in(app, ref) == ["primera ZQX-END-1", "segunda ZQX-END-2"]


def test_query_after_the_identifier_is_never_kept(cli, env, data_dir, app):
    """The page keeps a query string after the identifier; only the identifier is stored."""
    marker = "ZQ-QUERY-5531"
    url = app.url("/app", trail=marker)
    session_id = new_session(cli, env)
    code, out, err = cli("ask", session_id, "pregunta", **env | {"HARNESS_COPILOT_URL": url})
    assert code == 0, err
    ref = session_row(data_dir, session_id)[1]
    assert re.fullmatch(r"[0-9a-f]{16}", ref)
    assert marker not in out + err
    code, out, _ = cli("history", session_id, **env)
    assert ref in out and marker not in out
    assert not files_containing(data_dir, marker)


def test_identifier_assigned_after_the_reply_is_bound(cli, env, data_dir, app):
    """As measured on the real page: the identifier reaches the address after the answer."""
    session_id = new_session(cli, env)
    url = app.url("/app", id_delay_ms="1500")
    code, out, err = cli("ask", session_id, "pregunta", **env | {"HARNESS_COPILOT_URL": url})
    assert code == 0, err
    assert "identifier did not reach" not in err
    ref = session_row(data_dir, session_id)[1]
    assert ref in app.conversations


def test_completed_without_identifier_warns_and_binds_nothing(cli, env, data_dir, app):
    """Window 3 of D6: Copilot answered, the identifier never came."""
    session_id = new_session(cli, env)
    url = app.url("/app", id_never="1")
    code, out, err = cli("ask", session_id, "pregunta", **env | {"HARNESS_COPILOT_URL": url})
    assert code == 0, err
    assert CANARY_REPLY in out
    assert "identifier did not reach the address" in err
    assert session_row(data_dir, session_id) == ("active", None)
    # The next question cannot continue it: it says so and starts a new conversation.
    code, out, err = cli("ask", session_id, "otra", **env)
    assert code == 0 and "without the earlier context" in err
    assert len(app.conversations) == 2


def test_failure_before_the_identifier_is_uncertain_and_the_next_opens_a_new_one(
    cli, env, data_dir, app
):
    """Window 2 of D6: the prompt left, the reply never ends, the identifier never came."""
    session_id = new_session(cli, env)
    url = app.url("/app", never_finish="1", id_never="1")
    code, _, err = cli(
        "ask", session_id, "pregunta",
        **env | {"HARNESS_COPILOT_URL": url, "HARNESS_REQUEST_TIMEOUT_S": "20"},
    )
    assert code == 1 and "uncertain" in err
    assert session_row(data_dir, session_id) == ("uncertain", None)
    assert app.prompt_count == 1
    code, out, err = cli("ask", session_id, "siguiente", **env)
    assert code == 0, err
    assert "orphaned" in err
    assert request_states(data_dir, session_id) == ["uncertain", "completed"]
    assert len(app.conversations) == 2 and app.prompt_count == 2


# -- 5.2: a new process continues the conversation; a lost one closes the session -------------


def test_conversation_recovered_in_a_new_process(env, data_dir, app):
    created = run_main(data_dir, "session", "create", "S", **env)
    session_id = created.stdout.strip()
    first = run_main(data_dir, "ask", session_id, "primera ZQX-END-1", **env)
    assert first.returncode == 0, first.stderr
    second = run_main(data_dir, "ask", session_id, "segunda ZQX-END-2", **env)
    assert second.returncode == 0, second.stderr
    ref = session_row(data_dir, session_id)[1]
    assert prompts_in(app, ref) == ["primera ZQX-END-1", "segunda ZQX-END-2"]
    assert len(app.conversations) == 1


def test_lost_remote_conversation_closes_the_session_without_sending(env, data_dir, app):
    created = run_main(data_dir, "session", "create", "S", **env)
    session_id = created.stdout.strip()
    assert run_main(data_dir, "ask", session_id, "primera", **env).returncode == 0
    ref = session_row(data_dir, session_id)[1]
    lost = run_main(
        data_dir, "ask", session_id, "segunda", **env | {"HARNESS_COPILOT_URL": app.url("/app", forget="1")}
    )
    assert lost.returncode == 1
    assert "Create a new session" in lost.stderr and "Traceback" not in lost.stderr
    assert app.prompt_count == 1 and prompts_in(app, ref) == ["primera"]
    assert request_states(data_dir, session_id) == ["completed", "failed"]
    assert session_row(data_dir, session_id) == ("closed", ref)
    refused = run_main(data_dir, "ask", session_id, "tercera", **env)
    assert refused.returncode == 1 and "closed" in refused.stderr
    assert query(data_dir, "SELECT count(*) FROM requests") == [(2,)]
    assert app.prompt_count == 1


# -- 4.3: page states -------------------------------------------------------------------------


def test_expired_login_asks_for_a_person_and_touches_nothing(cli, env, data_dir, app):
    session_id = new_session(cli, env)
    app.require_login = True
    app.login_with_editor = True  # the sign-in page even has controls with the chat's locators
    code, out, err = cli("ask", session_id, "pregunta", **env)
    assert code == 1 and out == ""
    assert "copilot login" in err
    assert request_states(data_dir, session_id) == ["authentication_required"]
    assert session_row(data_dir, session_id) == ("authentication_required", None)
    assert app.login_events == []
    assert app.prompt_count == 0


def test_back_to_active_after_signing_in_by_hand(cli, env, data_dir, app):
    session_id = new_session(cli, env)
    app.require_login = True
    cli("ask", session_id, "pregunta", **env)
    app.login_auto_ms = 300  # the "person" signs in on the sign-in page
    code, _, err = cli("copilot", "login", **env)
    assert code == 0, err
    code, out, err = cli("ask", session_id, "otra vez", **env)
    assert code == 0, err
    assert session_row(data_dir, session_id)[0] == "active"
    assert request_states(data_dir, session_id) == ["authentication_required", "completed"]


def test_page_that_does_not_load_keeps_the_session(cli, env, data_dir, app):
    session_id = new_session(cli, env)
    cli("ask", session_id, "primera", **env)
    before = session_row(data_dir, session_id)
    url = app.url("/app", ready_ms="600000")
    code, _, err = cli(
        "ask", session_id, "segunda",
        **env | {"HARNESS_COPILOT_URL": url, "HARNESS_COPILOT_READY_TIMEOUT_S": "4"},
    )
    assert code == 1 and "not ready in time" in err
    assert request_states(data_dir, session_id) == ["completed", "timeout"]
    assert session_row(data_dir, session_id) == before
    assert app.prompt_count == 1


# -- 4.4: the new reply and its end -------------------------------------------------------------


def test_reply_written_in_parts_is_returned_whole(cli, env, data_dir, app):
    """The page shows its done control halfway and pauses; the stability guard waits. The
    pause (0.3 s) is far below the window (2 s), so a slow machine cannot stretch one into
    the other."""
    write_ui(data_dir, end_signal={"name": "done_control"}, stability_window_ms=2000)
    session_id = new_session(cli, env)
    url = app.url("/app", early="done_control", pause_ms="300")
    code, out, err = cli("ask", session_id, "partes ZQX-END-7", **env | {"HARNESS_COPILOT_URL": url})
    assert code == 0, err
    # The second half of the reply arrived, and it is the end of the answer.
    assert out.rstrip().endswith("word12 ZQX-END-7") and CANARY_REPLY in out


def test_an_earlier_reply_does_not_count(cli, env, data_dir, app):
    session_id = new_session(cli, env)
    cli("ask", session_id, "primera ZQX-END-1", **env)
    url = app.url("/app", start_ms="2500")
    code, out, err = cli("ask", session_id, "segunda ZQX-END-2", **env | {"HARNESS_COPILOT_URL": url})
    assert code == 0, err
    assert "ZQX-END-2" in out and "ZQX-END-1" not in out


def test_hostile_reply_is_printed_without_control_or_invisible_characters(cli, env, app):
    session_id = new_session(cli, env)
    code, out, err = cli("ask", session_id, "dame ZQX-HOSTILE", **env)
    assert code == 0, err
    assert "HOSTILE" in out and "END" in out
    for bad in ("\x1b", "\x07", "\x08", "\x00", "‮", "‬", "​"):
        assert bad not in out, repr(bad)
    # Whole escape sequences go, not only their ESC: no leftover `[2J` or window title.
    assert "[2J" not in out and "ZZ-TITLE" not in out


def test_huge_reply_is_read_up_to_the_cap(cli, env, app):
    session_id = new_session(cli, env)
    code, out, err = cli("ask", session_id, "dame ZQX-HUGE", **env)
    assert code == 0, err
    assert HUGE_REPLY_CHARS > REPLY_MAX_CHARS
    assert REPLY_MAX_CHARS - 10 <= len(out.strip()) <= REPLY_MAX_CHARS
    assert f"longer than {REPLY_MAX_CHARS}" in err


def test_feed_shape_with_a_lost_key_press_sends_once(cli, env, data_dir, app):
    """Enter sends, zero-width anchors in the editor, an optimistic copy of the message, and
    the first key press after loading is ignored: the prompt still arrives exactly once."""
    write_ui(data_dir, **FEED_UI)
    session_id = new_session(cli, env)
    url = app.url("/feed", lose_first="1")
    code, out, err = cli("ask", session_id, "feed ZQX-END-4", **env | {"HARNESS_COPILOT_URL": url})
    assert code == 0, err
    assert "ZQX-END-4" in out
    assert [p.prompt for p in app.prompts] == ["feed ZQX-END-4"]
    ref = session_row(data_dir, session_id)[1]
    code, out, err = cli("ask", session_id, "feed dos ZQX-END-5", **env | {"HARNESS_COPILOT_URL": app.url("/feed")})
    assert code == 0, err
    assert prompts_in(app, ref) == ["feed ZQX-END-4", "feed dos ZQX-END-5"]


# -- 4.5 and 5.3: browser lost, deadlines, no resend --------------------------------------------


async def close_the_window(h: Harness) -> None:
    """Close the harness's Edge from outside, as a person closing the window would. The
    provider then closes its context too; whichever close comes second finds it gone."""
    with contextlib.suppress(PlaywrightError):
        await h.launcher.contexts[0].close()


async def test_browser_closed_before_sending_fails(harness, app):
    h = harness(HARNESS_COPILOT_URL=app.url("/app", ready_ms="600000"))
    session = h.service.create_session("S")
    task = asyncio.create_task(h.service.ask(str(session.session_id), "pregunta"))
    await wait_until(lambda: app.page_hits > 0 and h.launcher.contexts, what="the page to load")
    await close_the_window(h)
    response = await asyncio.wait_for(task, 60)
    assert response.status == "failed" and "closed before the prompt was sent" in response.detail
    assert app.prompt_count == 0


async def test_browser_closed_during_the_reply_is_uncertain(harness, app):
    h = harness(HARNESS_COPILOT_URL=app.url("/app", never_finish="1"))
    session = h.service.create_session("S")
    task = asyncio.create_task(h.service.ask(str(session.session_id), "pregunta"))
    await wait_until(lambda: app.prompt_count == 1, timeout_s=30, what="the prompt")
    await close_the_window(h)
    response = await asyncio.wait_for(task, 60)
    assert response.status == "uncertain" and "not resent" in response.detail
    assert app.prompt_count == 1


async def test_nothing_is_left_open_after_a_deadline(harness, app):
    h = harness(HARNESS_COPILOT_URL=app.url("/app", never_finish="1"), HARNESS_REQUEST_TIMEOUT_S="20")
    session = h.service.create_session("S")
    response = await h.service.ask(str(session.session_id), "pregunta")
    assert response.status == "uncertain"
    assert h.launcher.contexts == [] and h.launcher.peak_open == 1
    other = harness()
    second = other.service.create_session("T")
    assert (await other.service.ask(str(second.session_id), "otra")).status == "completed"
    assert app.prompt_count == 2



async def test_an_error_before_sending_survives_a_driver_slow_to_stop(harness, app, monkeypatch):
    """Seen in two full runs on 2026-11-25: the lost conversation ended as `timeout`. Edge,
    with background networking on (D3), takes about 10 s to close; past the close bound,
    Playwright's driver waited for it with no bound of its own, and the request deadline
    expired while the browser was being put away. Here the driver never stops: the launcher
    gives up on it after its own bound, and the error found before sending is kept."""
    real_stop = PlaywrightClient.stop

    async def stuck(self):
        try:
            await asyncio.sleep(3600)
        finally:
            await real_stop(self)  # stopped for real when the test's loop ends

    h = harness()
    session = str(h.service.create_session("S").session_id)
    assert (await h.service.ask(session, "primera")).status == "completed"
    monkeypatch.setattr(PlaywrightClient, "stop", stuck)
    lost = harness(HARNESS_COPILOT_URL=app.url("/app", forget="1"))
    started = time.monotonic()
    response = await asyncio.wait_for(lost.service.ask(session, "segunda"), 60)
    assert response.status == "failed", response.detail
    assert "Create a new session" in response.detail
    assert time.monotonic() - started < lost.settings.request_timeout_s
    assert app.prompt_count == 1

def test_reply_that_never_ends_is_uncertain_and_never_resent(cli, env, data_dir, app):
    session_id = new_session(cli, env)
    assert cli("ask", session_id, "primera", **env)[0] == 0
    url = app.url("/app", never_finish="1")
    code, _, err = cli(
        "ask", session_id, "segunda",
        **env | {"HARNESS_COPILOT_URL": url, "HARNESS_REQUEST_TIMEOUT_S": "20"},
    )
    assert code == 1 and "uncertain" in err
    assert app.prompt_count == 2
    cli("session", "list", **env)  # any other command: recovery never resends
    assert app.prompt_count == 2
    code, out, err = cli("ask", session_id, "tercera", **env)
    assert code == 0, err
    assert "1 more turn(s) than the harness completed" in err
    assert app.prompt_count == 3 and [p.prompt for p in app.prompts][-1] == "tercera"
    assert request_states(data_dir, session_id) == ["completed", "uncertain", "completed"]


# -- 6.1 and 6.2: no content kept ---------------------------------------------------------------


def files_containing(root: Path, needle: str) -> list[Path]:
    found = []
    data = needle.encode()
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath, name)
            if data in path.read_bytes():
                found.append(path)
    return found


def text_columns_containing(data_dir: Path, needle: str) -> int:
    conn = sqlite3.connect(data_dir / DATABASE_NAME)
    try:
        hits = 0
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            for column in conn.execute(f"PRAGMA table_info({table})"):
                hits += conn.execute(
                    f"SELECT count(*) FROM {table} WHERE CAST({column[1]} AS TEXT) LIKE ?",
                    (f"%{needle}%",),
                ).fetchone()[0]
        return hits
    finally:
        conn.close()


def test_canaries_never_reach_storage(cli, env, data_dir, app):
    session_id = new_session(cli, env)
    code, out, err = cli("ask", session_id, f"pregunta {PROMPT_CANARY}", **env)
    assert code == 0, err
    assert CANARY_REPLY in out  # printed
    for canary in (PROMPT_CANARY, CANARY_REPLY):
        assert text_columns_containing(data_dir, canary) == 0
        assert files_containing(data_dir, canary) == []


def test_canary_negative_control_with_the_mock(cli, data_dir):
    """The same check finds the prompt when the provider is synthetic and stores content."""
    session_id = cli("session", "create", "S")[1].strip()
    assert cli("ask", session_id, f"pregunta {PROMPT_CANARY}")[0] == 0
    assert text_columns_containing(data_dir, PROMPT_CANARY) >= 1


def test_history_shows_the_reference_and_no_text(cli, env, data_dir, app):
    session_id = new_session(cli, env)
    cli("ask", session_id, f"uno {PROMPT_CANARY}", **env)
    cli("ask", session_id, f"dos {PROMPT_CANARY}", **env)
    ref = session_row(data_dir, session_id)[1]
    code, out, err = cli("history", session_id, **env)
    assert code == 0, err
    assert f"remote conversation: {ref}" in out
    assert len(re.findall(r"^\[completed\] ", out, flags=re.M)) == 2
    assert PROMPT_CANARY not in out and CANARY_REPLY not in out
    assert provider_factory(Settings.from_env(env))("copilot_web").synthetic_content is False
