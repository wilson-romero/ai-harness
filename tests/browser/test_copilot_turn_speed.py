"""Speed of a question to Copilot Web (change copilot-turn-speed) against the synthetic chat:
the phases timed (D1), the held tab asked again without reloading only when it is trusted
(D2), the reply ended on a measured positive signal (D3), and the old path without the
measurement or with the switches off (D4).

The synthetic server is the oracle: it counts every prompt and every page load, and holds the
full text of every reply. Headless Edge, temporary profile, nothing real.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.browser.edge import EdgeLauncher
from harness.config import Settings
from harness.core.contracts import RequestStatus
from harness.core.service import SessionService
from harness.providers import copilot_web
from harness.providers.copilot_timings import PHASES, read_for, timings_path
from harness.providers.copilot_web import CopilotWebProvider
from harness.storage.database import open_database
from tests.browser.test_copilot_provider import write_ui
from tests.conftest import REPO_ROOT
from tests.copilot_app import CANARY_REPLY, SyntheticCopilot, late_block, make_reply, wait_until

pytestmark = pytest.mark.edge

FAST_END = {"signal": "stop_hidden", "confirm_ms": 500, "sends": 12, "modes": ["auto"],
            "measured_at": "2026-11-27T00:00:00Z"}
TAB_REUSE = {"questions": 4, "measured_at": "2026-11-27T00:00:00Z"}
# As on the real page (4 s, measured 2026-11-24): the fallback must be told apart from the
# fast end by its time.
REAL_WINDOW_MS = 4000
PROMPT_CANARY = "ZZ-CANARY-PROMPT-7710"
MENU = REPO_ROOT / "tests" / "fixtures" / "copilot_ui" / "response-mode-menu.json"


class Talk:
    """One provider held for a conversation, behind the real service, in this process."""

    def __init__(self, data_dir: Path, profile: Path, url: str, **env: str) -> None:
        self.env = {
            "HARNESS_DATA_DIR": str(data_dir),
            "HARNESS_PROVIDER": "copilot_web",
            "HARNESS_COPILOT_URL": url,
            "HARNESS_EDGE_PROFILE": str(profile),
            "HARNESS_REQUEST_TIMEOUT_S": "40",
            "HARNESS_TEST_HEADLESS": "1",
            # Off by default (review 2026-11-28, finding 5); these tests turn it on.
            "HARNESS_COPILOT_REUSE_TAB": "on",
        } | env
        self.settings = Settings.from_env(self.env)
        self.launcher = EdgeLauncher.from_settings(self.settings)
        self.provider = CopilotWebProvider(self.settings, self.launcher)
        self.conn = open_database(data_dir)
        self.data_dir = data_dir
        self.service = SessionService(self.conn, data_dir, lambda name: self.provider,
                                      "copilot_web", self.settings.request_timeout_s)
        self.timings = []

    async def __aenter__(self) -> Talk:
        await self.provider.open_resources()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.provider.close_resources()

    def session(self, name: str = "S") -> str:
        return str(self.service.create_session(name).session_id)

    async def ask(self, session_id: str, prompt: str, **kwargs):
        response = await self.service.ask(session_id, prompt, **kwargs)
        self.timings.append(self.provider.last_timings)
        return response

    def page(self):
        held = self.provider._held
        assert held is not None and held.page is not None
        return held.page

    def remote(self, session_id: str) -> str | None:
        return self.conn.execute("SELECT remote_ref FROM sessions WHERE session_id = ?",
                                 (session_id,)).fetchone()[0]

    def paths(self) -> list[str]:
        return [t.path for t in self.timings]


@pytest.fixture
def talk(copilot_app: SyntheticCopilot, data_dir: Path, tmp_path: Path):
    made: list[Talk] = []

    def build(url: str | None = None, **env: str) -> Talk:
        made.append(Talk(data_dir, tmp_path / "edge-profile", url or copilot_app.url(), **env))
        return made[-1]

    build.app = copilot_app

    yield build
    for t in made:
        t.conn.close()


def measured(data_dir: Path, *, reuse: bool = True, fast: bool = True, **changes) -> None:
    extra = {"stability_window_ms": REAL_WINDOW_MS}
    if reuse:
        extra["tab_reuse"] = TAB_REUSE
    if fast:
        extra["fast_end"] = FAST_END
    write_ui(data_dir, **(extra | changes))


def user_prompts(app: SyntheticCopilot, conversation: str) -> list[str]:
    return [t["text"] for t in app.conversations[conversation] if t["role"] == "user"]


# -- D1: every question timed, durations only ---------------------------------------------------


async def test_every_question_records_its_phases_and_no_text(talk, copilot_app, data_dir):
    write_ui(data_dir)  # the synthetic measurement as it was: nothing of this change measured
    async with talk() as t:
        s = t.session()
        for n in (1, 2):
            r = await t.ask(s, f"{PROMPT_CANARY} pregunta {n} ZQX-END-{n}")
            assert r.status is RequestStatus.COMPLETED
    raw = timings_path(data_dir).read_text(encoding="utf-8")
    assert PROMPT_CANARY not in raw and CANARY_REPLY not in raw and "127.0.0.1" not in raw
    lines = [json.loads(line) for line in raw.splitlines()]
    assert len(lines) == 2
    for line in lines:
        assert line["outcome"] == "answered" and line["path"] == "reload"
        assert line["end"] == "window" and line["attempts"] == 1
        for phase in ("navigate", "ready", "settle", "guard", "type", "send", "reply_start",
                      "reply_end", "read", "post"):
            assert phase in line["phases_ms"], phase
        assert set(line["phases_ms"]) <= set(PHASES)
        assert line["phases_ms"]["settle"] >= 2000  # the old path's 2 s without changes
        assert line["total_ms"] >= sum(v for k, v in line["phases_ms"].items() if k != "read")
    assert t.provider.last_timings.request_id == lines[-1]["request_id"]


def test_history_shows_the_timings_of_each_question(cli, copilot_app, data_dir, tmp_path):
    write_ui(data_dir)
    env = {"HARNESS_DATA_DIR": str(data_dir), "HARNESS_PROVIDER": "copilot_web",
           "HARNESS_COPILOT_URL": copilot_app.url(),
           "HARNESS_EDGE_PROFILE": str(tmp_path / "edge-profile"),
           "HARNESS_REQUEST_TIMEOUT_S": "40", "HARNESS_TEST_HEADLESS": "1"}
    code, out, err = cli("session", "create", "S", **env)
    session_id = out.strip()
    code, out, err = cli("ask", session_id, "una ZQX-END-1", **env)
    assert code == 0, err
    assert "timings (s)" not in err  # the debug line only when asked for
    code, out, err = cli("ask", session_id, "dos ZQX-END-2", **env, HARNESS_COPILOT_TIMINGS="on")
    assert code == 0, err
    assert "warning: timings (s): answered, path reload, end window" in err
    code, out, err = cli("history", session_id, "--timings", **env)
    assert code == 0, err
    assert out.count("timings (s): answered, path reload, end window, total") == 2
    assert "navigate" in out and "reply end" in out
    code, plain, err = cli("history", session_id, **env)
    assert "timings" not in plain  # control: only with --timings


def test_timings_of_another_provider_or_a_tampered_file_are_not_shown(data_dir):
    path = timings_path(data_dir)
    path.parent.mkdir(parents=True)
    good = {"request_id": "r1", "session_id": "s", "path": "reload", "declined": None,
            "end": "window", "attempts": 1, "outcome": "answered",
            "phases_ms": {"navigate": 400}, "total_ms": 400, "at": ""}
    bad = [good | {"request_id": "r2", "path": "\x1b[2J"}, good | {"request_id": "r3",
           "phases_ms": {"secret": 1}}, good | {"request_id": "r4", "declined": "page text"}]
    path.write_text("\n".join([json.dumps(good), *map(json.dumps, bad), "not json"]) + "\n")
    found = read_for(data_dir, ["r1", "r2", "r3", "r4"])
    assert list(found) == ["r1"]


# -- D4: without the measurement, or switched off, the old path ------------------------------


async def test_without_the_measurement_every_question_reloads_and_waits_the_window(
        talk, copilot_app, data_dir):
    write_ui(data_dir, stability_window_ms=REAL_WINDOW_MS)  # switches on (default), nothing measured
    async with talk() as t:
        s = t.session()
        for n in (1, 2, 3):
            r = await t.ask(s, f"q{n} ZQX-END-{n}")
            assert r.status is RequestStatus.COMPLETED and r.text == make_reply(f"q{n} ZQX-END-{n}")
    assert t.paths() == ["reload"] * 3 and [x.end for x in t.timings] == ["window"] * 3
    assert all(x.declined is None for x in t.timings)
    assert copilot_app.page_hits == 3 and copilot_app.prompt_count == 3


@pytest.mark.parametrize("switch", ["HARNESS_COPILOT_REUSE_TAB", "HARNESS_COPILOT_FAST_END"])
async def test_each_switch_turns_its_optimisation_off(talk, copilot_app, data_dir, switch):
    measured(data_dir)
    async with talk(**{switch: "off"}) as t:
        s = t.session()
        for n in (1, 2):
            assert (await t.ask(s, f"q{n} ZQX-END-{n}")).status is RequestStatus.COMPLETED
    if switch == "HARNESS_COPILOT_REUSE_TAB":
        assert t.paths() == ["reload", "reload"] and t.timings[1].end == "signal"
        assert copilot_app.page_hits == 2
    else:
        assert t.paths() == ["reload", "reuse"] and [x.end for x in t.timings] == ["window"] * 2
        assert copilot_app.page_hits == 1


def test_a_switch_takes_only_on_or_off():
    from harness.core.errors import InvalidInput

    with pytest.raises(InvalidInput, match="HARNESS_COPILOT_REUSE_TAB"):
        Settings.from_env({"HARNESS_COPILOT_REUSE_TAB": "maybe"})
    assert Settings.from_env({}).copilot_reuse_tab is False  # off by default (D8)
    assert Settings.from_env({"HARNESS_COPILOT_FAST_END": "OFF"}).copilot_fast_end is False


# -- D2: the trusted tab, asked again without reloading ------------------------------------------


async def test_a_trusted_tab_is_asked_again_without_reloading(talk, copilot_app, data_dir):
    measured(data_dir, fast=False)
    prompts = [f"seguida {n} ZQX-END-{n}" for n in (1, 2, 3)]
    async with talk() as t:
        s = t.session()
        for prompt in prompts:
            r = await t.ask(s, prompt)
            assert r.status is RequestStatus.COMPLETED and r.text == make_reply(prompt)
    assert t.paths() == ["reload", "reuse", "reuse"]
    assert t.timings[0].declined == "new tab"
    assert copilot_app.page_hits == 1  # one load for three questions
    assert copilot_app.prompt_count == 3  # one send per question, nothing resent
    assert user_prompts(copilot_app, t.remote(s)) == prompts
    for x in t.timings[1:]:
        assert {"navigate", "ready", "settle", "history"}.isdisjoint(x.phases_ms)
        assert "reuse_check" in x.phases_ms and "guard" in x.phases_ms


async def test_reuse_refuses_a_tab_moved_to_another_address(talk, copilot_app, data_dir):
    """The person opened a new chat in the tab: the question reloads its own conversation
    (as before) instead of typing there, and the session goes on."""
    measured(data_dir, fast=False)
    async with talk() as t:
        s = t.session()
        await t.ask(s, "uno ZQX-END-1")
        await t.page().goto(copilot_app.url())
        r = await t.ask(s, "dos ZQX-END-2")
    assert r.status is RequestStatus.COMPLETED, r.detail
    assert t.paths() == ["reload", "reload"] and t.timings[1].declined == "address"
    assert user_prompts(copilot_app, t.remote(s)) == ["uno ZQX-END-1", "dos ZQX-END-2"]


async def test_reuse_refuses_a_tab_another_session_used(talk, copilot_app, data_dir):
    measured(data_dir, fast=False)
    async with talk() as t:
        a, b = t.session("A"), t.session("B")
        await t.ask(a, "en A ZQX-END-1")
        await t.ask(b, "en B ZQX-END-2")
        r = await t.ask(a, "otra en A ZQX-END-3")
    assert r.status is RequestStatus.COMPLETED
    assert t.paths() == ["reload", "reload", "reload"]
    assert [x.declined for x in t.timings] == ["new tab", "no conversation", "other session"]
    assert user_prompts(copilot_app, t.remote(a)) == ["en A ZQX-END-1", "otra en A ZQX-END-3"]
    assert user_prompts(copilot_app, t.remote(b)) == ["en B ZQX-END-2"]


async def test_reuse_refuses_a_page_that_signed_out(talk, copilot_app, data_dir):
    measured(data_dir, fast=False)
    async with talk(copilot_app.url(live="1")) as t:
        s = t.session()
        await t.ask(s, "uno ZQX-END-1")
        copilot_app.require_login = True
        await t.page().locator("#synthetic-unauth-banner").wait_for(timeout=10_000)
        r = await t.ask(s, "dos ZQX-END-2")
    assert r.status is RequestStatus.AUTHENTICATION_REQUIRED, r.detail
    assert t.timings[1].declined == "page state"
    assert copilot_app.prompt_count == 1 and copilot_app.login_events == []


async def test_reuse_refuses_a_conversation_deleted_elsewhere(talk, copilot_app, data_dir):
    measured(data_dir, fast=False)
    async with talk(copilot_app.url(live="1")) as t:
        s = t.session()
        await t.ask(s, "uno ZQX-END-1")
        copilot_app.forget(t.remote(s))
        await wait_until(lambda: "/c/" not in t.page().url, 10, "the tab to leave the deleted chat")
        r = await t.ask(s, "dos ZQX-END-2")
    assert r.status is RequestStatus.FAILED and "Create a new session" in (r.detail or "")
    assert t.timings[1].declined == "address"
    assert copilot_app.prompt_count == 1  # nothing typed in the new chat


async def test_reuse_refuses_a_tab_with_a_turn_added_elsewhere(talk, copilot_app, data_dir):
    measured(data_dir, fast=False)
    async with talk(copilot_app.url(live="1")) as t:
        s = t.session()
        await t.ask(s, "uno ZQX-END-1")
        copilot_app.add_elsewhere(t.remote(s), "ZZ-OTRO-DISPOSITIVO")
        users = t.page().locator("#synthetic-thread .turn.user")
        await wait_until(lambda: len(copilot_app.conversations[t.remote(s)]) == 4, 5, "the turn")
        for _ in range(100):
            if await users.count() == 2:
                break
            await t.page().wait_for_timeout(100)
        r = await t.ask(s, "dos ZQX-END-2")
    assert r.status is RequestStatus.COMPLETED and r.text == make_reply("dos ZQX-END-2")
    assert t.timings[1].path == "reload" and t.timings[1].declined == "turns"
    assert any("1 more turn(s)" in w for w in r.warnings)
    assert user_prompts(copilot_app, t.remote(s)) == ["uno ZQX-END-1", "ZZ-OTRO-DISPOSITIVO",
                                                      "dos ZQX-END-2"]


async def test_reuse_refuses_a_tab_idle_too_long(talk, copilot_app, data_dir, monkeypatch):
    measured(data_dir, fast=False)
    monkeypatch.setattr(copilot_web, "REUSE_MAX_IDLE_S", 0.0)
    async with talk() as t:
        s = t.session()
        await t.ask(s, "uno ZQX-END-1")
        r = await t.ask(s, "dos ZQX-END-2")
    assert r.status is RequestStatus.COMPLETED
    assert t.timings[1].declined == "idle" and copilot_app.page_hits == 2


async def test_on_the_reused_tab_the_mode_is_set_and_confirmed_before_typing(
        talk, copilot_app, data_dir):
    measured(data_dir, fast=False, response_mode=json.loads(MENU.read_text(encoding="utf-8")))
    async with talk(copilot_app.url(modes="menu")) as t:
        s = t.session()
        await t.ask(s, "uno ZQX-END-1")
        r = await t.ask(s, "dos ZQX-END-2", mode="quick")
    assert r.status is RequestStatus.COMPLETED, r.detail
    assert t.paths() == ["reload", "reuse"] and "mode" in t.timings[1].phases_ms
    assert [(p.mode, p.list_open) for p in copilot_app.prompts] == [("auto", False),
                                                                    ("quick", False)]


# -- D3: the end of a reply by a positive signal ------------------------------------------------


async def ask_once(talk, data_dir, url: str, *, fast: bool = True, prompt="fin ZQX-END-1",
                   **changes):
    measured(data_dir, reuse=False, fast=fast, **changes)
    app = talk.app
    before = app.prompt_count
    async with talk(url) as t:
        r = await t.ask(t.session(), prompt)
    assert r.status is RequestStatus.COMPLETED, r.detail
    assert app.prompt_count == before + 1  # one send, nothing resent
    return r, t.timings[0]


async def test_a_reply_ends_on_its_signal_before_the_window(talk, copilot_app, data_dir):
    r, timing = await ask_once(talk, data_dir, copilot_app.url())
    assert r.text == make_reply("fin ZQX-END-1") and timing.end == "signal"
    # Control: the same page without the measurement waits the 4 s window.
    r2, slow = await ask_once(talk, data_dir, copilot_app.url(), fast=False)
    assert r2.text == r.text and slow.end == "window"
    assert slow.phases_ms["reply_end"] - timing.phases_ms["reply_end"] >= 2500


async def test_a_pause_while_the_reply_is_still_busy_does_not_end_it(talk, copilot_app, data_dir):
    r, timing = await ask_once(talk, data_dir, copilot_app.url(pause_ms="1500"))
    assert r.text == make_reply("fin ZQX-END-1") and timing.end == "signal"


async def test_a_signal_that_flickers_does_not_end_the_reply(talk, copilot_app, data_dir):
    r, timing = await ask_once(talk, data_dir, copilot_app.url(pause_ms="2000", flicker_ms="300"))
    assert r.text == make_reply("fin ZQX-END-1") and timing.end == "signal"


async def test_a_signal_that_never_shows_leaves_the_window_to_decide(talk, copilot_app, data_dir):
    r, timing = await ask_once(talk, data_dir, copilot_app.url(nostop="1", pause_ms="1500"))
    assert r.text == make_reply("fin ZQX-END-1") and timing.end == "window"


async def test_a_reply_that_streams_slowly_is_returned_whole(talk, copilot_app, data_dir):
    r, timing = await ask_once(talk, data_dir, copilot_app.url(steps="6", chunk_ms="800"))
    assert r.text == make_reply("fin ZQX-END-1") and timing.end == "signal"


async def test_a_block_appended_after_the_signal_is_waited_for(talk, copilot_app, data_dir):
    url = copilot_app.url(late_block_ms="100", late_chunks="6")
    r, timing = await ask_once(talk, data_dir, url)
    assert r.text == make_reply("fin ZQX-END-1") + "\n\n" + late_block(6)


async def test_without_the_fast_end_a_late_block_is_kept_by_the_window(talk, copilot_app, data_dir):
    """What the probe falls back to when a page appends after the confirmation window
    (`test_speed_refuses_a_fast_end_that_would_cut_a_late_block`): the old window."""
    url = copilot_app.url(late_block_ms="1500")
    r, timing = await ask_once(talk, data_dir, url, fast=False)
    assert r.text == make_reply("fin ZQX-END-1") + "\n\n" + late_block(1)
    assert timing.end == "window"


async def test_both_optimisations_together_keep_every_answer_whole(talk, copilot_app, data_dir):
    measured(data_dir)
    prompts = [f"juntas {n} ZQX-END-{n}" for n in (1, 2, 3)]
    async with talk(copilot_app.url(pause_ms="1200")) as t:
        s = t.session()
        texts = [(await t.ask(s, p)).text for p in prompts]
    assert texts == [make_reply(p) for p in prompts]
    assert t.paths() == ["reload", "reuse", "reuse"] and [x.end for x in t.timings] == ["signal"] * 3
    assert copilot_app.prompt_count == 3 and copilot_app.page_hits == 1


# -- D5: with a window by default, without one only when asked ----------------------------------


async def test_questions_use_a_window_unless_headless_is_switched_on(talk, copilot_app, data_dir):
    """The server tells the two apart by the User-Agent (`HeadlessChrome` without a window)."""
    write_ui(data_dir)
    async with talk(HARNESS_TEST_HEADLESS="") as t:
        r = await t.ask(t.session(), "con ventana ZQX-END-1")
    assert r.status is RequestStatus.COMPLETED and copilot_app.headless_hits == [False]
    async with talk(HARNESS_TEST_HEADLESS="", HARNESS_COPILOT_HEADLESS="on") as t:
        r = await t.ask(t.session(), "sin ventana ZQX-END-2")
    assert r.status is RequestStatus.COMPLETED and r.text == make_reply("sin ventana ZQX-END-2")
    assert copilot_app.headless_hits == [False, True]


@pytest.mark.parametrize("page, status", [("login", RequestStatus.AUTHENTICATION_REQUIRED),
                                          ("other", RequestStatus.TIMEOUT)])
async def test_a_page_that_differs_without_a_window_is_refused(talk, copilot_app, data_dir,
                                                                page, status):
    """Without a window the page asks to sign in, or has another structure than ui.json: the
    existing guards refuse it and nothing is typed. With a window the same page works."""
    write_ui(data_dir)
    copilot_app.headless_page = page
    async with talk(HARNESS_TEST_HEADLESS="", HARNESS_COPILOT_HEADLESS="on",
                    HARNESS_COPILOT_READY_TIMEOUT_S="5") as t:
        r = await t.ask(t.session(), "sin ventana ZQX-END-1")
    assert r.status is status, r.detail
    assert "nothing was sent" in (r.detail or "")
    assert copilot_app.prompt_count == 0 and all(copilot_app.headless_hits)
    async with talk(HARNESS_TEST_HEADLESS="") as t:  # control: with a window
        r = await t.ask(t.session(), "con ventana ZQX-END-2")
    assert r.status is RequestStatus.COMPLETED and copilot_app.prompt_count == 1


def test_signing_in_always_uses_a_window(monkeypatch, tmp_path):
    import asyncio
    import dataclasses

    from harness.browser import login
    from harness.browser.edge import EdgeLauncher

    settings = Settings.from_env({"HARNESS_DATA_DIR": str(tmp_path),
                                  "HARNESS_COPILOT_HEADLESS": "on",
                                  "HARNESS_COPILOT_URL": "http://127.0.0.1:9/app"})
    assert EdgeLauncher.from_settings(settings).headless is True
    assert EdgeLauncher.from_settings(settings, window=True).headless is False
    assert EdgeLauncher.from_settings(dataclasses.replace(settings, copilot_headless=False)).headless is False
    seen = []

    def spy(settings, **kwargs):
        seen.append(kwargs)
        raise RuntimeError("stop here")

    monkeypatch.setattr(login.EdgeLauncher, "from_settings", spy)
    monkeypatch.setattr(login, "load_measurement", lambda data_dir: None)
    with pytest.raises(RuntimeError, match="stop here"):
        asyncio.run(login.manual_login(settings))
    assert seen == [{"window": True}]


# -- review 2026-11-28 ----------------------------------------------------------------------
# Finding 1: an idle gap between two phases of a reply, longer than the short window, ended it
# with half its text. Each case asserts the FULL text and one send.

WHOLE = make_reply("fin ZQX-END-1")


@pytest.mark.parametrize("gap_ms", ["700", "800"])
async def test_an_idle_gap_between_two_phases_does_not_cut_the_reply(talk, copilot_app,
                                                                     data_dir, gap_ms):
    r, timing = await ask_once(talk, data_dir, copilot_app.url(pause_ms="2600", flicker_ms=gap_ms))
    assert r.text == WHOLE
    assert timing.early_endings == 1  # the fast end fired, the signal came back: counted


async def test_a_late_block_after_an_idle_moment_is_kept(talk, copilot_app, data_dir):
    """Citations or cards that arrive 0.8 s after the reply looked finished."""
    r, timing = await ask_once(talk, data_dir, copilot_app.url(late_block_ms="800", late_chunks="3"))
    assert r.text == WHOLE + "\n\n" + late_block(3)
    assert timing.early_endings == 1


async def test_a_signal_element_removed_and_created_again_does_not_cut_the_reply(
        talk, copilot_app, data_dir):
    url = copilot_app.url(pause_ms="2600", flicker_ms="800", recreate="1")
    r, timing = await ask_once(talk, data_dir, url)
    assert r.text == WHOLE


async def test_an_instant_reply_whose_signal_never_turns_busy_ends_by_the_window(
        talk, copilot_app, data_dir):
    r, timing = await ask_once(talk, data_dir, copilot_app.url(steps="1", nostop="1"))
    assert r.text == WHOLE and timing.end == "window"


async def test_a_signal_already_busy_before_sending_does_not_count(talk, copilot_app, data_dir):
    """The stop control shows before the prompt goes out (left over), hides when the reply
    appears and never shows again while it streams with a pause."""
    url = copilot_app.url(stale_stop="1", nostop="1", start_ms="600", pause_ms="1500")
    r, timing = await ask_once(talk, data_dir, url)
    assert r.text == WHOLE and timing.end == "window"


async def test_the_fast_end_acts_only_in_the_modes_it_was_measured_in(talk, copilot_app,
                                                                     data_dir):
    menu = json.loads(MENU.read_text(encoding="utf-8"))
    r, timing = await ask_once(talk, data_dir, copilot_app.url(modes="menu"), response_mode=menu)
    assert timing.end == "signal"  # control: measured in auto
    measured(data_dir, reuse=False, response_mode=menu)
    async with talk(copilot_app.url(modes="menu")) as t:
        r = await t.ask(t.session(), "fin ZQX-END-2", mode="deep")
    assert r.status is RequestStatus.COMPLETED and r.text == make_reply("fin ZQX-END-2")
    assert t.timings[0].end == "window"
    measured(data_dir, reuse=False, response_mode=menu, fast_end=FAST_END | {"modes": ["auto", "deep"]})
    async with talk(copilot_app.url(modes="menu")) as t:
        r = await t.ask(t.session(), "fin ZQX-END-3", mode="deep")
    assert t.timings[0].end == "signal"


# Finding 2: the timings never change a question's outcome.


async def test_a_corrupt_timings_file_does_not_change_the_answer(talk, copilot_app, data_dir,
                                                                monkeypatch):
    from harness.providers import copilot_timings

    measured(data_dir, reuse=False, fast=False)
    monkeypatch.setattr(copilot_timings, "TRIM_AT_BYTES", 1_000)
    path = timings_path(data_dir)
    path.write_bytes(b"\xff\xfe not utf-8 \x80" * 200 + b"\n")
    async with talk() as t:
        r = await t.ask(t.session(), "fin ZQX-END-1")
    assert r.status is RequestStatus.COMPLETED, r.detail
    assert r.text == WHOLE and copilot_app.prompt_count == 1


async def test_a_directory_in_place_of_the_timings_file_does_not_change_the_answer(
        talk, copilot_app, data_dir):
    measured(data_dir, reuse=False, fast=False)
    timings_path(data_dir).mkdir()
    async with talk() as t:
        r = await t.ask(t.session(), "fin ZQX-END-1")
    assert r.status is RequestStatus.COMPLETED and r.text == WHOLE


async def test_a_recording_that_raises_does_not_change_the_answer(talk, copilot_app, data_dir,
                                                                 monkeypatch):
    """Whatever the recording raises, the question that was sent keeps its answer; a
    cancellation is not an Exception and is never caught there."""
    from harness.providers import copilot_web

    def boom(*args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(copilot_web, "record_timings", boom)
    measured(data_dir, reuse=False, fast=False)
    async with talk() as t:
        r = await t.ask(t.session(), "fin ZQX-END-1")
    assert r.status is RequestStatus.COMPLETED, r.detail
    assert r.text == WHOLE and copilot_app.prompt_count == 1


# Finding 5: reuse stays off until the owner turns it on.


async def test_reuse_is_off_unless_switched_on(talk, copilot_app, data_dir):
    measured(data_dir, fast=False)
    async with talk(HARNESS_COPILOT_REUSE_TAB="") as t:
        s = t.session()
        for n in (1, 2):
            assert (await t.ask(s, f"q{n} ZQX-END-{n}")).status is RequestStatus.COMPLETED
    assert t.paths() == ["reload", "reload"] and copilot_app.page_hits == 2


# Finding 6: a question that did not end with an answer makes the next one reload; the idle
# bound at its edge.


async def test_after_an_uncertain_question_the_next_one_reloads(talk, copilot_app, data_dir):
    """The first question answers (the tab is remembered), the second runs out of time after
    sending: the third reloads in a new tab, not the remembered one."""
    measured(data_dir, fast=False)
    async with talk(copilot_app.url(pause_ms="5000")) as t:
        s = t.session()
        assert (await t.ask(s, "uno ZQX-END-1")).status is RequestStatus.COMPLETED
        t.service._timeout_s = 4.0  # this question only: it ends before the reply does
        second = await t.ask(s, "dos ZQX-END-2")
        assert second.status is RequestStatus.UNCERTAIN, second.detail
        t.service._timeout_s = 40.0
        await t.ask(s, "tres ZQX-END-3")
    assert t.timings[1].outcome == "uncertain"
    assert t.timings[2].path == "reload" and t.timings[2].declined == "new tab"


async def test_after_a_failed_question_the_next_one_reloads(talk, copilot_app, data_dir):
    measured(data_dir, fast=False, response_mode=json.loads(MENU.read_text(encoding="utf-8")))
    async with talk(copilot_app.url(modes="menu", mode_stuck="1")) as t:
        s = t.session()
        assert (await t.ask(s, "uno ZQX-END-1")).status is RequestStatus.COMPLETED
        failed = await t.ask(s, "dos ZQX-END-2", mode="deep")
        assert failed.status is RequestStatus.FAILED, failed.detail
        third = await t.ask(s, "tres ZQX-END-3", mode="auto")  # `deep` stays chosen
    assert third.status is RequestStatus.COMPLETED
    assert t.timings[1].path == "reuse"  # the failed one still used the trusted tab
    assert t.timings[2].path == "reload" and t.timings[2].declined == "new tab"


async def test_after_a_cancelled_question_the_next_one_reloads(talk, copilot_app, data_dir):
    import asyncio

    measured(data_dir, fast=False)
    async with talk(copilot_app.url(pause_ms="3000")) as t:
        s = t.session()
        await t.ask(s, "uno ZQX-END-1")
        task = asyncio.ensure_future(t.service.ask(s, "dos ZQX-END-2"))
        await wait_until(lambda: copilot_app.prompt_count == 2, 20, "the second prompt")
        task.cancel()
        with pytest.raises(BaseException):
            await task
        t.timings.append(t.provider.last_timings)
        assert t.timings[-1].outcome == "cancelled"
        await t.ask(s, "tres ZQX-END-3")
    assert t.timings[-1].path == "reload" and t.timings[-1].declined == "new tab"


@pytest.mark.parametrize("idle_s, path", [(119.0, "reuse"), (121.0, "reload")])
async def test_the_idle_bound_at_its_edge(talk, copilot_app, data_dir, idle_s, path):
    measured(data_dir, fast=False)
    async with talk() as t:
        s = t.session()
        await t.ask(s, "uno ZQX-END-1")
        t.provider._held.memory.at -= idle_s  # the answer came idle_s seconds ago
        r = await t.ask(s, "dos ZQX-END-2")
    assert r.status is RequestStatus.COMPLETED and t.timings[1].path == path
    assert t.timings[1].declined == (None if path == "reuse" else "idle")


# Windows parity 3, on the reuse path (task 8.6): a held tab that is not reused falls back to
# the reload, and a page that is then not ready reports the same structural detail.


async def test_a_declined_tab_that_reloads_into_a_page_never_ready_says_what_it_showed(
        talk, copilot_app, data_dir):
    measured(data_dir, fast=False)
    async with talk(HARNESS_COPILOT_READY_TIMEOUT_S="3") as t:
        s = t.session()
        assert (await t.ask(s, "uno ZQX-END-1")).status is RequestStatus.COMPLETED
        t.provider._held.memory.at -= 121.0  # declined as idle: the question reloads
        copilot_app.headless_page = "other"  # the reload gets a page without the chat
        r = await t.ask(s, "dos ZQX-END-2")
    assert r.status is RequestStatus.TIMEOUT, r.detail
    assert t.timings[1].path == "reload" and t.timings[1].declined == "idle"
    detail = r.detail or ""
    assert "not ready in time" in detail and "nothing was sent" in detail
    assert "ended by HARNESS_COPILOT_READY_TIMEOUT_S" in detail and "user turns" in detail
    assert copilot_app.prompt_count == 1  # only the first question was sent
