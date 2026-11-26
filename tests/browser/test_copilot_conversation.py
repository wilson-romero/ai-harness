"""Copilot Web in a conversation: Edge is launched once and kept (design D3, revised
2026-11-26; interactive-shell D5; spec llm-provider «Recursos del proveedor con vida de
conversación»). Synthetic chat only, headless, temporary profile."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from harness.browser.edge import BROWSER_LOCK, EdgeLauncher
from harness.config import Settings
from harness.core.service import SessionService
from harness.providers import copilot_web
from harness.providers.copilot_web import CopilotWebProvider
from harness.shell.conversation import INTERRUPTED_EXIT, Conversation, ConversationDeps
from harness.skills.config import SkillSettings
from harness.storage.database import open_database
from harness.storage.locks import NamedLock
from tests.browser.test_copilot_provider import write_ui
from tests.conftest import run_main
from tests.copilot_app import SyntheticCopilot, wait_until
from tests.shell_support import Action, ScriptedTerminal
from tests.skill_support import FIXTURES

pytestmark = pytest.mark.edge


class Chat:
    """A conversation with a real Copilot provider against the synthetic chat, in this process."""

    def __init__(self, data_dir: Path, profile: Path, url: str, terminal: ScriptedTerminal,
                 timeout_s: float = 40.0) -> None:
        self.env = {
            "HARNESS_DATA_DIR": str(data_dir),
            "HARNESS_PROVIDER": "copilot_web",
            "HARNESS_COPILOT_URL": url,
            "HARNESS_EDGE_PROFILE": str(profile),
            "HARNESS_REQUEST_TIMEOUT_S": str(timeout_s),
            "HARNESS_TEST_HEADLESS": "1",
        }
        self.settings = Settings.from_env(self.env)
        self.launcher = EdgeLauncher.from_settings(self.settings)
        self.provider = CopilotWebProvider(self.settings, self.launcher)
        self.conn = open_database(data_dir)
        self.data_dir = data_dir
        self.terminal = terminal
        service = SessionService(self.conn, data_dir, lambda name: self.provider, "copilot_web", timeout_s)
        self.conversation = Conversation(terminal, ConversationDeps(
            conn=self.conn, data_dir=data_dir, service=service, provider=self.provider,
            provider_name="copilot_web", timeout_s=timeout_s,
            memory=lambda: (_ for _ in ()).throw(AssertionError("no memory in these tests")),
            skills=lambda: SkillSettings(skills_dir=FIXTURES, approval_ttl_s=900),
            columns=lambda: 10_000,
        ))

    def statuses(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT status FROM requests ORDER BY rowid")]

    def error_codes(self) -> list[str | None]:
        return [r[0] for r in self.conn.execute("SELECT error_code FROM requests ORDER BY rowid")]

    def sessions(self) -> list[tuple[str, str | None]]:
        return list(self.conn.execute("SELECT session_id, remote_ref FROM sessions ORDER BY rowid"))

    def browser_free(self) -> bool:
        lock = NamedLock(self.data_dir, BROWSER_LOCK)
        free = lock.acquire()
        lock.release()
        return free

    def closed(self) -> bool:
        """Nothing of the browser is left: no context, no launch in progress, lock free."""
        return not self.launcher.contexts and self.launcher._starting_or_open == 0 and self.browser_free()

    def close(self) -> None:
        self.conn.close()


@pytest.fixture
def app(copilot_app: SyntheticCopilot, data_dir: Path) -> SyntheticCopilot:
    write_ui(data_dir)
    return copilot_app


@pytest.fixture
def chat(app, data_dir, tmp_path):
    made: list[Chat] = []

    def build(lines: list, url: str | None = None, **kwargs) -> Chat:
        c = Chat(data_dir, tmp_path / "edge-profile", url or app.url(), ScriptedTerminal(lines), **kwargs)
        made.append(c)
        return c

    yield build
    for c in made:
        c.close()


@pytest.fixture
def launches(monkeypatch) -> list:
    calls: list = []
    original = EdgeLauncher._launch

    async def spy(self, playwright, profile):
        calls.append(profile)
        return await original(self, playwright, profile)

    monkeypatch.setattr(EdgeLauncher, "_launch", spy)
    return calls


@pytest.fixture
def pages(monkeypatch) -> list:
    """The page each question ran on, in order."""
    seen: list = []
    original = copilot_web._Turn.run

    async def spy(self, page):
        seen.append(page)
        return await original(self, page)

    monkeypatch.setattr(copilot_web._Turn, "run", spy)
    return seen


# -- one launch, kept for the whole conversation ----------------------------------------------


async def test_one_launch_for_several_questions(chat, app, launches):
    open_during: list[bool] = []
    c = chat(["uno ZQX-END-1", "dos ZQX-END-2",
              Action(lambda t: open_during.append(bool(c.launcher.contexts))),
              "tres ZQX-END-3", "/exit"])
    assert await c.conversation.run() == 0
    assert c.statuses() == ["completed"] * 3 and app.prompt_count == 3
    assert len(launches) == 1 and open_during == [True]
    assert c.closed()
    for n in (1, 2, 3):
        assert f"ZQX-END-{n}" in c.terminal.text


def test_one_shot_ask_still_launches_and_closes_per_question(cli, app, data_dir, tmp_path, launches):
    """Negative control of the test above, and scenario «Pregunta suelta sin cambios»: outside a
    conversation every `ask` launches Edge and closes it."""
    env = {"HARNESS_DATA_DIR": str(data_dir), "HARNESS_PROVIDER": "copilot_web",
           "HARNESS_COPILOT_URL": app.url(), "HARNESS_EDGE_PROFILE": str(tmp_path / "edge-profile"),
           "HARNESS_REQUEST_TIMEOUT_S": "40", "HARNESS_TEST_HEADLESS": "1"}
    code, out, err = cli("session", "create", "S", **env)
    session_id = out.strip()
    for n in (1, 2):
        code, out, err = cli("ask", session_id, f"suelta ZQX-END-{n}", **env)
        assert code == 0, err
    lock = NamedLock(data_dir, BROWSER_LOCK)
    assert lock.acquire()
    lock.release()
    assert app.prompt_count == 2


# -- closed on every way out ------------------------------------------------------------------


@pytest.mark.parametrize("ending", ["/exit", None])
async def test_closed_when_leaving(chat, ending):
    c = chat(["uno ZQX-END-1", ending])
    assert await c.conversation.run() == 0
    assert c.statuses() == ["completed"] and c.closed()


async def test_closed_when_the_loop_breaks(chat, app):
    c = chat([])

    async def broken(prompt):
        assert c.launcher.contexts  # open while the conversation runs
        raise RuntimeError("the terminal broke")

    c.terminal.read_line = broken
    with pytest.raises(RuntimeError):
        await c.conversation.run()
    assert c.closed()


async def test_ctrl_c_while_edge_starts_exits_130_and_leaves_nothing(chat, monkeypatch, launches):
    """The shell cancels the opening at the first Ctrl+C; the launch is undone, the lock freed."""
    c = chat(["nunca"])
    original = EdgeLauncher._launch

    async def interrupted(self, playwright, profile):
        task = asyncio.ensure_future(original(self, playwright, profile))
        c.conversation.interrupt()  # what the SIGINT handler calls
        return await task

    monkeypatch.setattr(EdgeLauncher, "_launch", interrupted)
    assert await c.conversation.run() == INTERRUPTED_EXIT
    assert c.statuses() == [] and c.closed()
    assert "nunca" not in c.terminal.text.split("\n")[-1]


# -- the browser lock -------------------------------------------------------------------------


async def test_the_browser_lock_is_held_for_the_conversation(chat, data_dir):
    seen: dict = {}

    async def second_process(term):
        seen["free_inside"] = c.browser_free()
        # Another process that needs the browser: a one-shot `ask` in a new session, with a
        # short deadline so its bounded wait for the lock ends quickly.
        env = c.env | {"HARNESS_REQUEST_TIMEOUT_S": "4"}
        created = await asyncio.to_thread(run_main, data_dir, "session", "create", "otra", **env)
        asked = await asyncio.to_thread(run_main, data_dir, "ask", created.stdout.strip(),
                                        "desde otro proceso ZQX-END-9", **env)
        seen["second"] = (asked.returncode, asked.stderr)

    c = chat(["uno ZQX-END-1", Action(second_process), "/exit"])
    assert await c.conversation.run() == 0
    assert seen["free_inside"] is False
    code, err = seen["second"]
    assert code != 0 and "in use by another command" in err
    assert c.browser_free()  # control: released once the conversation ends


# -- sessions inside one conversation ---------------------------------------------------------


def _resume_first(c: Chat) -> Action:
    def run(term):
        first = c.sessions()[0][0]
        line = next(l for l in reversed(term.shown) if str(first) in l and l[1:4].strip())
        term.lines.insert(0, f"/resume {line[1:4].strip()}")
    return Action(run)


async def test_new_and_resume_navigate_in_the_same_browser(chat, app, launches):
    c = chat(["en A ZQX-END-1", "/new B", "en B ZQX-END-2", "/sessions"])
    c.terminal.lines += [_resume_first(c), "otra vez en A ZQX-END-3", "/exit"]
    assert await c.conversation.run() == 0
    assert c.statuses() == ["completed"] * 3 and len(launches) == 1
    (a, ref_a), (b, ref_b) = c.sessions()
    assert ref_a and ref_b and ref_a != ref_b
    assert [t["text"] for t in app.conversations[ref_a] if t["role"] == "user"] == [
        "en A ZQX-END-1", "otra vez en A ZQX-END-3"]
    assert [t["text"] for t in app.conversations[ref_b] if t["role"] == "user"] == ["en B ZQX-END-2"]


# -- Ctrl+C during a question -----------------------------------------------------------------


async def test_ctrl_c_after_sending_is_uncertain_and_the_next_question_gets_a_new_tab(
        chat, app, launches, pages):
    """Defined state: a question that does not end with an answer leaves its tab untrusted
    (it may still be sending or rendering); the next question opens a new tab in the same
    browser, closes the old one without its unload handlers and loads its conversation."""
    c = chat([], url=app.url("/app", chunk_ms="300"))

    async def watcher():
        await wait_until(lambda: app.prompt_count == 1, 60, "the first prompt to arrive")
        await asyncio.sleep(0.5)
        c.conversation.interrupt()

    c.terminal.lines = ["primera ZQX-END-1", "segunda ZQX-END-2", "tercera ZQX-END-3", "/exit"]
    task = asyncio.ensure_future(watcher())
    assert await c.conversation.run() == 0
    await task
    assert c.statuses() == ["uncertain", "completed", "completed"]
    assert c.error_codes()[0] == "interrupted"
    assert app.prompt_count == 3  # never resent
    assert len(launches) == 1 and c.closed()
    # The interrupted tab was replaced; a tab after an answer is kept (control).
    assert pages[1] is not pages[0] and pages[2] is pages[1]
    assert pages[0].is_closed()


async def test_a_window_closed_by_hand_is_launched_again(chat, app, launches):
    c = chat([])

    async def close_window(term):
        await c.launcher.contexts[0].close()

    c.terminal.lines = ["uno ZQX-END-1", Action(close_window), "dos ZQX-END-2", "/exit"]
    assert await c.conversation.run() == 0
    assert c.statuses() == ["completed", "completed"] and len(launches) == 2 and c.closed()


# -- signed out -------------------------------------------------------------------------------


async def test_signed_out_the_conversation_opens_and_the_question_asks_to_sign_in(
        chat, app, launches):
    app.require_login = True
    c = chat(["hola ZQX-END-1", "/exit"])
    assert await c.conversation.run() == 0
    assert c.statuses() == ["authentication_required"]
    assert "main.py copilot login" in c.terminal.text
    assert app.prompt_count == 0 and app.login_events == []  # nothing typed anywhere
    assert len(launches) == 1 and c.closed()
    # Control: signed in, the same conversation sends.
    app.require_login = False
    c2 = chat(["hola ZQX-END-2", "/exit"])
    assert await c2.conversation.run() == 0
    assert c2.statuses()[-1] == "completed" and app.prompt_count == 1
