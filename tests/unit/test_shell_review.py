"""Checks the independent review of 2026-11-25 found missing: for each, a mutation of the code
left every test green. Each test here fails on that mutation (receipts in tasks.md)."""

from __future__ import annotations

import os
import signal

import pytest

from harness.core.errors import ProjectMismatch, SessionBusy, UsageError
from harness.core.service import SessionService
from harness.memory.context import build_context
from harness.shell.app import interrupts_to
from harness.shell.conversation import read_text_file
from harness.storage.locks import SessionLock
from tests.conftest import write_note
from tests.shell_support import (
    Action,
    CountingProvider,
    ScriptedTerminal,
    make_conversation,
    statuses,
)
from tests.skill_support import build


def _resume(session_id) -> Action:
    """Type `/resume N` with the number /sessions gave to `session_id`."""

    def run(term):
        line = next(l for l in reversed(term.shown) if str(session_id) in l and l[1:4].strip())
        term.lines.insert(0, f"/resume {line[1:4].strip()}")

    return Action(run)


async def test_a_held_session_lets_the_engine_skip_only_that_session_lock(conn, data_dir):
    """`held_session` is the conversation's own session: for any other, the engine takes the
    lock, and a session held elsewhere is refused (mutation: any session is «held»)."""
    _, sessions, _ = build(conn, data_dir)
    held = sessions.create_session("de la conversación")
    other = sessions.create_session("de otro proceso")
    engine, _, provider = build(conn, data_dir, held_session=held.session_id)
    outside = SessionLock(data_dir, other.session_id)
    assert outside.acquire()
    try:
        with pytest.raises(SessionBusy):
            await engine.run("demo-echo", str(other.session_id), {"text": "x"})
        assert provider.calls == 0
    finally:
        outside.release()
    mine = SessionLock(data_dir, held.session_id)  # the conversation holds its own session
    assert mine.acquire()
    try:
        outcome = await engine.run("demo-echo", str(held.session_id), {"text": "x"})
        assert outcome.status == "awaiting_approval"  # it ran without a second lock
    finally:
        mine.release()


async def test_a_refused_resume_keeps_the_current_session_held(conn, data_dir):
    """Receipt 3.3 said this was checked; it was not (mutation: release, then take)."""
    _, service, _ = make_conversation(conn, data_dir, ScriptedTerminal())
    busy = service.create_session("ocupada")
    _, lock = service.take_session(str(busy.session_id))
    still_held: list[bool] = []
    holder: list = []

    def check(_term):
        probe = SessionLock(data_dir, holder[0]._session_id)
        taken = probe.acquire()
        if taken:
            probe.release()
        still_held.append(not taken)

    terminal = ScriptedTerminal(["/sessions", _resume(busy.session_id), Action(check), "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal)
    holder.append(conversation)
    try:
        await conversation.run()
    finally:
        lock.release()
    assert "is in use by another process" in terminal.text
    assert still_held == [True]


async def test_resume_refuses_a_session_of_another_provider(conn, data_dir):
    other = SessionService(conn, data_dir, lambda name: CountingProvider(), "otro", 5.0)
    foreign = other.create_session("de otro proveedor")
    terminal = ScriptedTerminal(["/sessions", _resume(foreign.session_id), "pregunta", "/exit"])
    conversation, service, provider = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    assert "uses provider 'otro'" in terminal.text
    assert [e.content for e in service.history(str(foreign.session_id))] == []
    assert provider.prompts == ["pregunta"]  # asked in the conversation's own session


async def test_memory_in_a_session_with_a_project_searches_only_that_project(conn, data_dir,
                                                                             vault):
    write_note(vault, "projects/demo-beta/solo-beta.md", "termino-solo-de-beta",
               type="nota", project="demo-beta")
    terminal = ScriptedTerminal(["/memory termino-solo-de-beta", "/new sin proyecto",
                                 "/memory termino-solo-de-beta", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal, vault=vault)
    await conversation.run(None, "demo-alpha")
    first, second = [i for i, line in enumerate(terminal.shown) if line.startswith("search:")]
    assert "No results." in terminal.shown[:first]
    assert terminal.shown[first].startswith("search: 0 result(s)")
    assert terminal.shown[second].startswith("search: 1 result(s)")


def test_harness_lines_that_start_with_a_bar_are_moved(conn, data_dir):
    terminal = ScriptedTerminal()
    conversation, _, _ = make_conversation(conn, data_dir, terminal)
    conversation._say("| no soy del proveedor\nnormal")
    assert terminal.shown == [" | no soy del proveedor", "normal"]


def test_the_ctrl_c_handler_is_put_back_on_exit(conn, data_dir):
    conversation, _, _ = make_conversation(conn, data_dir, ScriptedTerminal())
    before = signal.getsignal(signal.SIGINT)
    with interrupts_to(conversation):
        assert signal.getsignal(signal.SIGINT) is not before
    assert signal.getsignal(signal.SIGINT) is before
    with pytest.raises(RuntimeError), interrupts_to(conversation):
        raise RuntimeError("the conversation broke")
    assert signal.getsignal(signal.SIGINT) is before


def test_a_file_swapped_after_its_check_is_refused(tmp_path, monkeypatch):
    """The entry checked and the file opened must be the same (mutation: no identity check)."""
    checked = tmp_path / "comprobado.md"
    checked.write_text("texto", encoding="utf-8")
    opened = tmp_path / "abierto.md"
    opened.write_text("otro texto", encoding="utf-8")
    real_lstat = os.lstat

    def swapped(path, *args, **kwargs):  # the entry changes between lstat and open
        return real_lstat(checked if str(path) == str(opened) else path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", swapped)
    with pytest.raises(UsageError, match="changed while it was opened"):
        read_text_file(str(opened))


async def test_an_interrupt_left_from_before_does_not_answer_the_approval_prompt(monkeypatch,
                                                                                capsys):
    """A Ctrl+C mark that reached the queue after the wait it was meant for had ended is not
    an answer to the next approval prompt (mutation: the prompt keeps stale marks)."""
    import asyncio
    import builtins

    from harness.shell import terminal as module

    monkeypatch.setattr(builtins, "input", lambda prompt="": "abcd1234")
    console = module.ConsoleTerminal()
    console._queue.put(module._INTERRUPT)  # left over from an earlier wait
    answer = await asyncio.get_running_loop().run_in_executor(None, console.ask, "code: ")
    assert answer == "abcd1234"


async def test_ask_taken_refuses_the_memory_of_another_project(conn, data_dir, vault):
    terminal = ScriptedTerminal()
    _, service, provider = make_conversation(conn, data_dir, terminal, vault=vault)
    session = service.create_session("alfa", "demo-alpha")
    _, lock = service.take_session(str(session.session_id))
    try:
        context = build_context(vault.resolve(), "demo-beta", 16 * 1024)
        with pytest.raises(ProjectMismatch):
            await service.ask_taken(session.session_id, provider, "pregunta", context)
    finally:
        lock.release()
    assert provider.calls == 0 and statuses(conn) == []


async def test_a_session_project_that_is_not_valid_is_refused_and_audited(conn, data_dir, vault):
    """The question's checks are those of `ask --project` (mutation: no check before the vault
    is read): a stored project that is not a valid name is refused and audited."""
    terminal = ScriptedTerminal(["pregunta", "/exit"])
    conversation, service, provider = make_conversation(conn, data_dir, terminal, vault=vault)
    session = service.create_session("S", "demo-alpha")
    conn.execute("UPDATE sessions SET project_id = '../fuera' WHERE session_id = ?",
                 (str(session.session_id),))
    await conversation.run(str(session.session_id))
    assert provider.calls == 0 and statuses(conn) == []
    outcomes = [row[0] for row in conn.execute(
        "SELECT outcome FROM audit_events WHERE event_type = 'memory.context'")]
    assert outcomes == ["denied"]
