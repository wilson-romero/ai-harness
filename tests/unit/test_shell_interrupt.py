"""Ctrl+C in the conversation (interactive-shell D6, D7, task 4.1).

`Conversation.interrupt()` is what the SIGINT handler calls. Here the test provider calls it at
a fixed point of the question (before or after `on_sent`), so the order of events is fixed by
the double, not by a clock. The real delivery of the signal is task 4.2.
"""

import asyncio
import builtins
import threading
import time

from harness.shell.terminal import ConsoleTerminal, WaitInterrupted
from tests.shell_support import (
    INTERRUPT,
    Action,
    CountingProvider,
    ScriptedTerminal,
    make_conversation,
    statuses,
)


def _interrupting(when: str) -> tuple[CountingProvider, list]:
    provider = CountingProvider()
    holder: list = []

    def hook() -> None:
        holder[0].interrupt()

    setattr(provider, "after_send" if when == "after" else "before_send", hook)
    return provider, holder


async def test_interrupt_after_send_leaves_the_request_uncertain(conn, data_dir):
    """Scenario «Interrupción después del envío»; never resent."""
    provider, holder = _interrupting("after")
    terminal = ScriptedTerminal(["pregunta interrumpida", "otra pregunta", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider)
    holder.append(conversation)
    assert await conversation.run() == 0
    assert statuses(conn) == ["uncertain", "completed"]
    assert any("is uncertain" in line and "not resent" in line for line in terminal.shown)
    assert provider.prompts.count("pregunta interrumpida") == 1
    assert provider.calls == 2


async def test_interrupt_before_send_is_not_uncertain(conn, data_dir):
    """Scenario «Interrupción antes del envío»."""
    provider, holder = _interrupting("before")
    terminal = ScriptedTerminal(["pregunta", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider)
    holder.append(conversation)
    assert await conversation.run() == 0
    assert statuses(conn) == ["failed"]
    assert conn.execute("SELECT error_code FROM requests").fetchone()[0] == \
        "interrupted_before_send"
    assert any("failed before the prompt was sent" in line for line in terminal.shown)
    assert terminal.reads == 2  # back to waiting for a line


async def test_interrupt_while_waiting_keeps_the_conversation(conn, data_dir):
    """Scenario «Interrupción en la espera»."""
    terminal = ScriptedTerminal([INTERRUPT, INTERRUPT, "/status", "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal)
    assert await conversation.run() == 0
    assert sum(line.startswith("interrupted: the conversation is still open")
               for line in terminal.shown) == 2
    assert any(line.startswith("last request: -") for line in terminal.shown)
    assert statuses(conn) == []
    assert provider.calls == 0


async def test_the_next_question_after_an_uncertain_one(conn, data_dir):
    """Scenario «Pregunta siguiente tras una incierta»."""
    provider, holder = _interrupting("after")
    terminal = ScriptedTerminal(["primera", "segunda", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider)
    holder.append(conversation)
    await conversation.run()
    requests = conn.execute("SELECT request_id, status FROM requests ORDER BY rowid").fetchall()
    assert [row[1] for row in requests] == ["uncertain", "completed"]
    assert requests[0][0] != requests[1][0]
    second = terminal.shown.index("> segunda")
    assert any(line.startswith("warning: this session has an earlier uncertain request")
               for line in terminal.shown[second:])


async def test_ctrl_c_before_the_question_starts_names_no_earlier_request(conn, data_dir):
    """Review 2026-11-25: Ctrl+C right after Enter, before the question's task started. The
    notice is about this line (nothing recorded, nothing sent), never about the request before."""
    provider, holder = _interrupting("after")
    terminal = ScriptedTerminal([
        "primera",
        Action(lambda _t: holder[0].interrupt()),  # lands before the next task starts
        "segunda",
        "/exit",
    ])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, provider)
    holder.append(conversation)
    assert await conversation.run() == 0
    assert statuses(conn) == ["uncertain"]
    assert provider.calls == 1
    second = terminal.shown.index("> segunda")
    after = terminal.shown[second + 1:]
    assert "interrupted: no request was recorded; nothing was sent" in after
    assert not any(line.startswith("interrupted: request") for line in after)


async def test_the_conversation_ignores_an_interrupt_when_no_loop_runs(conn, data_dir):
    conversation, _, _ = make_conversation(conn, data_dir, ScriptedTerminal())
    conversation.interrupt()  # before `run`: nothing to cancel, nothing raised


# -- the real terminal's line wait, with `input` replaced (no terminal needed) ---------------------


class FakeInput:
    """Stands in for `input()` in the helper thread: blocks until the test gives a line."""

    def __init__(self) -> None:
        self.given: list[object] = []
        self.ready = threading.Condition()
        self.calls = 0

    def __call__(self, prompt: str = "") -> str:
        with self.ready:
            self.calls += 1
            while not self.given:
                self.ready.wait()
            item = self.given.pop(0)
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item
        return item  # type: ignore[return-value]

    def give(self, item: object) -> None:
        with self.ready:
            self.given.append(item)
            self.ready.notify_all()


async def _until(condition, timeout_s: float = 10.0) -> None:
    """Yield to the loop until `condition` holds; a test that waits for what never comes fails
    instead of spinning (review 2026-11-25). The deadline is a guard, not the synchronisation."""
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("the condition never held")
        await asyncio.sleep(0)


async def test_console_wait_interrupted_keeps_one_read_and_its_line(monkeypatch, capsys):
    fake = FakeInput()
    monkeypatch.setattr(builtins, "input", fake)
    terminal = ConsoleTerminal()
    waiting = asyncio.ensure_future(terminal.read_line("> "))
    await _until(lambda: fake.calls == 1)
    assert terminal.interrupt_wait() is True
    try:
        await waiting
        raise AssertionError("the wait was not interrupted")
    except WaitInterrupted:
        pass
    assert terminal.interrupt_wait() is False  # nobody is waiting now
    second = asyncio.ensure_future(terminal.read_line("> "))
    await asyncio.sleep(0)
    fake.give("después")
    assert await second == "después"
    assert fake.calls == 1  # the interrupted read was the only one


async def test_console_end_of_input_after_an_interrupt_is_not_the_end(monkeypatch, capsys):
    fake = FakeInput()
    monkeypatch.setattr(builtins, "input", fake)
    terminal = ConsoleTerminal()
    waiting = asyncio.ensure_future(terminal.read_line("> "))
    await _until(lambda: fake.calls == 1)
    terminal.interrupt_wait()
    try:
        await waiting
    except WaitInterrupted:
        pass
    again = asyncio.ensure_future(terminal.read_line("> "))
    fake.give(EOFError)  # what the console may return to the interrupted read (D6, Windows)
    await _until(lambda: fake.calls == 2)
    fake.give("sigue")
    assert await again == "sigue"
    fake_end = asyncio.ensure_future(terminal.read_line("> "))
    await _until(lambda: fake.calls == 3)
    fake.give(EOFError)
    assert await fake_end is None  # a real end of input still ends


async def test_console_keyboard_interrupt_in_the_reader_thread_reads_again(monkeypatch, capsys):
    """Review 2026-11-25: a KeyboardInterrupt raised in the helper thread (plausible on
    Windows) once left `_reading` true forever, so no read started again and the wait hung."""
    fake = FakeInput()
    monkeypatch.setattr(builtins, "input", fake)
    terminal = ConsoleTerminal()
    waiting = asyncio.ensure_future(terminal.read_line("> "))
    await _until(lambda: fake.calls == 1)
    fake.give(KeyboardInterrupt)
    await _until(lambda: fake.calls == 2)
    fake.give("sigue")
    assert await asyncio.wait_for(waiting, 10) == "sigue"


async def test_console_end_of_input_then_ctrl_c_is_an_interruption(monkeypatch, capsys):
    """Review 2026-11-25: a console may end the read (end of input) before the SIGINT handler
    runs. An interruption that arrives after that end, within the grace, is an interruption:
    the conversation does not end."""
    monkeypatch.setattr("harness.shell.terminal.EOF_GRACE_S", 30.0)
    fake = FakeInput()
    monkeypatch.setattr(builtins, "input", fake)
    terminal = ConsoleTerminal()
    waiting = asyncio.ensure_future(terminal.read_line("> "))
    await _until(lambda: fake.calls == 1)
    fake.give(EOFError)
    await _until(lambda: not terminal._reading or waiting.done())  # the end has been taken
    assert terminal.interrupt_wait() is True  # the handler, late
    try:
        await asyncio.wait_for(waiting, 10)
        raise AssertionError("the late interruption was taken as the end of input")
    except WaitInterrupted:
        pass
    again = asyncio.ensure_future(terminal.read_line("> "))
    await _until(lambda: fake.calls == 2)
    fake.give("sigue")
    assert await asyncio.wait_for(again, 10) == "sigue"


async def test_console_end_of_input_alone_still_ends_after_the_grace(monkeypatch, capsys):
    monkeypatch.setattr("harness.shell.terminal.EOF_GRACE_S", 0.01)
    fake = FakeInput()
    monkeypatch.setattr(builtins, "input", fake)
    terminal = ConsoleTerminal()
    waiting = asyncio.ensure_future(terminal.read_line("> "))
    await _until(lambda: fake.calls == 1)
    fake.give(EOFError)
    assert await asyncio.wait_for(waiting, 10) is None


async def test_console_approval_prompt_interrupted_is_undecided(monkeypatch, capsys):
    fake = FakeInput()
    monkeypatch.setattr(builtins, "input", fake)
    terminal = ConsoleTerminal()
    loop = asyncio.get_running_loop()
    # Ctrl+C while a thread is blocked in the prompt (the loop thread, in the conversation).
    answer = await loop.run_in_executor(None, lambda: _ask_with_interrupt(terminal, fake))
    assert answer is None
    # The read the prompt left behind gives its line to the next waiter, the conversation.
    nxt = asyncio.ensure_future(terminal.read_line("> "))
    await asyncio.sleep(0)
    fake.give("abcd1234")
    assert await nxt == "abcd1234"
    assert fake.calls == 1


def _ask_with_interrupt(terminal: ConsoleTerminal, fake: FakeInput) -> str | None:
    def interrupt_when_reading() -> None:
        while fake.calls == 0:
            time.sleep(0.001)
        while not terminal.interrupt_wait():
            time.sleep(0.001)

    threading.Thread(target=interrupt_when_reading, daemon=True).start()
    return terminal.ask("code: ")


async def test_console_reads_nothing_ahead(monkeypatch, capsys):
    """No read starts until someone waits: a line typed meanwhile is read by the next waiter."""
    fake = FakeInput()
    monkeypatch.setattr(builtins, "input", fake)
    terminal = ConsoleTerminal()
    first = asyncio.ensure_future(terminal.read_line("> "))
    await _until(lambda: fake.calls == 1)
    fake.give("uno")
    assert await first == "uno"
    await asyncio.sleep(0)
    assert fake.calls == 1  # no second read started after the line
