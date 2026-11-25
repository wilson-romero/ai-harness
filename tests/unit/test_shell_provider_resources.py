"""Provider resources that live as long as a conversation (interactive-shell D5, task 4.3;
spec llm-provider «Recursos del proveedor con vida de conversación»)."""

import asyncio

from harness.providers.base import close_resources, open_resources
from harness.providers.mock import MockProvider
from harness.shell.conversation import INTERRUPTED_EXIT
from tests.conftest import RecordingProvider
from tests.shell_support import CountingProvider, ScriptedTerminal, make_conversation, statuses


async def test_one_open_for_several_questions(conn, data_dir):
    """Scenario «Una apertura para varias preguntas»."""
    provider = CountingProvider()
    seen: list[tuple[int, int]] = []

    def watch(term):
        seen.append((provider.opens, provider.closes))

    from tests.shell_support import Action
    terminal = ScriptedTerminal(["uno", Action(watch), "dos", "tres", Action(watch), "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider)
    await conversation.run()
    assert provider.calls == 3
    assert seen == [(1, 0), (1, 0)]  # open during the questions, closed only at the end
    assert (provider.opens, provider.closes) == (1, 1)


async def test_closed_even_after_a_failed_question(conn, data_dir):
    """Scenario «Cierre aunque una pregunta falle» (failed)."""
    provider = CountingProvider(fail=True)
    terminal = ScriptedTerminal(["uno", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider)
    await conversation.run()
    assert statuses(conn) == ["failed"]
    assert (provider.opens, provider.closes) == (1, 1)


async def test_closed_even_after_an_uncertain_question(conn, data_dir):
    """Scenario «Cierre aunque una pregunta falle» (uncertain), leaving by end of input."""
    provider = CountingProvider()
    terminal = ScriptedTerminal(["uno", None])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider)
    provider.after_send = conversation.interrupt
    await conversation.run()
    assert statuses(conn) == ["uncertain"]
    assert (provider.opens, provider.closes) == (1, 1)


async def test_closed_when_the_loop_ends_with_an_error(conn, data_dir):
    provider = CountingProvider()

    class Broken(ScriptedTerminal):
        async def read_line(self, prompt):
            raise RuntimeError("the terminal broke")

    conversation, _, _ = make_conversation(conn, data_dir, Broken(), provider)
    try:
        await conversation.run()
    except RuntimeError:
        pass
    assert (provider.opens, provider.closes) == (1, 1)


class _Hanging(CountingProvider):
    """A provider whose opening or closing never ends; Ctrl+C arrives while it hangs."""

    def __init__(self, where: str) -> None:
        super().__init__()
        self.where = where
        self.conversation = None

    async def _hang(self) -> None:
        self.conversation.interrupt()  # what the SIGINT handler calls
        await asyncio.sleep(3600)

    async def open_resources(self) -> None:
        self.opens += 1
        if self.where == "open":
            await self._hang()

    async def close_resources(self) -> None:
        self.closes += 1
        if self.where == "close":
            await self._hang()


async def test_ctrl_c_stops_an_opening_that_never_ends(conn, data_dir):
    """Review 2026-11-25: Ctrl+C while the provider opens ends the conversation cleanly:
    nothing asked, the provider closed, the session free."""
    provider = _Hanging("open")
    terminal = ScriptedTerminal(["no debería leerse", "/exit"])
    conversation, service, _ = make_conversation(conn, data_dir, terminal, provider)
    provider.conversation = conversation
    assert await asyncio.wait_for(conversation.run(), 10) == INTERRUPTED_EXIT
    assert (provider.opens, provider.closes) == (1, 1)
    assert terminal.reads == 0 and provider.calls == 0 and statuses(conn) == []
    assert any(line.startswith("interrupted: the provider was still opening")
               for line in terminal.shown)
    (session_id,) = [row[0] for row in conn.execute("SELECT session_id FROM sessions")]
    _, lock = service.take_session(session_id)  # free again
    lock.release()


async def test_ctrl_c_stops_a_closing_that_never_ends(conn, data_dir):
    provider = _Hanging("close")
    terminal = ScriptedTerminal(["uno", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider)
    provider.conversation = conversation
    assert await asyncio.wait_for(conversation.run(), 10) == 0
    assert statuses(conn) == ["completed"]
    assert any(line.startswith("interrupted: closing the provider was stopped")
               for line in terminal.shown)


async def test_a_provider_without_resources_works_the_same():
    """A provider with nothing to keep: opening and closing are no-ops."""
    mock = MockProvider()
    await open_resources(mock)
    await close_resources(mock)


def test_a_single_question_never_opens(cli, monkeypatch):
    """Scenario «Pregunta suelta sin cambios»: same answer and same rows as a provider without
    the operations, and neither operation is called."""
    def rows(code_out_err):
        code, out, err = code_out_err
        return code, out

    plain = RecordingProvider()
    monkeypatch.setattr("harness.cli.provider_factory", lambda settings: lambda name: plain)
    session = cli("session", "create", "S")[1].strip()
    before = rows(cli("ask", session, "la misma pregunta"))

    counting = CountingProvider()
    monkeypatch.setattr("harness.cli.provider_factory", lambda settings: lambda name: counting)
    after = rows(cli("ask", session, "la misma pregunta"))
    assert (counting.opens, counting.closes) == (0, 0)
    assert counting.calls == 1
    assert before == (0, "respuesta sintética\n") and after == before
    history = cli("history", session)[1].splitlines()
    assert history == ["[completed] user: la misma pregunta",
                       "[completed] assistant: respuesta sintética"] * 2
