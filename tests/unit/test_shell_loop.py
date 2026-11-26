"""The conversation loop: questions, commands and sessions (interactive-shell, tasks 3.2-3.3)."""

from harness.core.contracts import RequestStatus
from harness.shell.conversation import FOREIGN_PREFIX
from harness.storage.locks import SessionLock
from tests.shell_support import CountingProvider, ScriptedTerminal, make_conversation, statuses


def _session_ids(conn) -> list[str]:
    return [row[0] for row in conn.execute("SELECT session_id FROM sessions ORDER BY rowid")]


def _questions(service, session_id) -> list[str]:
    return [e.content for e in service.history(str(session_id)) if e.role == "user"]


# -- 3.2 the minimal loop -------------------------------------------------------------------------


async def test_a_question_is_answered_and_the_loop_waits_again(conn, data_dir):
    """Scenario «Pregunta respondida»."""
    terminal = ScriptedTerminal(["¿Qué es una ADR?", "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal)
    assert await conversation.run() == 0
    assert provider.prompts == ["¿Qué es una ADR?"]
    assert f"{FOREIGN_PREFIX}respuesta sintética" in terminal.shown
    assert statuses(conn) == ["completed"]
    assert terminal.reads == 2  # it waited for another line after the answer


async def test_two_questions_in_a_row_belong_to_one_session(conn, data_dir):
    """Scenario «Dos preguntas seguidas en la misma sesión»."""
    terminal = ScriptedTerminal(["uno", "dos", "/exit"])
    conversation, service, _ = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    [session_id] = _session_ids(conn)
    sessions = {row[0] for row in conn.execute("SELECT session_id FROM requests")}
    assert sessions == {session_id}
    assert _questions(service, session_id) == ["uno", "dos"]


async def test_an_empty_line_records_nothing(conn, data_dir):
    """Scenario «Línea vacía»."""
    terminal = ScriptedTerminal(["", "   ", "\t", "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    assert provider.calls == 0
    assert statuses(conn) == []
    assert terminal.reads == 4


async def test_a_failed_question_keeps_the_conversation_open(conn, data_dir):
    """Scenario «Pregunta fallida»."""
    terminal = ScriptedTerminal(["x", "y", "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal,
                                                  CountingProvider(fail=True))
    assert await conversation.run() == 0
    assert statuses(conn) == ["failed", "failed"]
    assert sum("ended as failed" in line for line in terminal.shown) == 2
    assert provider.calls == 2


async def test_exit_frees_the_session_and_leaves_nothing_in_flight(conn, data_dir):
    """Scenario «Salida ordenada»."""
    terminal = ScriptedTerminal(["uno", "/exit", "never read"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal)
    assert await conversation.run() == 0
    assert terminal.lines == ["never read"]
    [session_id] = _session_ids(conn)
    lock = SessionLock(data_dir, __import__("uuid").UUID(session_id))
    assert lock.acquire()
    lock.release()
    assert conn.execute("SELECT count(*) FROM requests WHERE status IN ('pending', 'running')"
                        ).fetchone()[0] == 0


async def test_end_of_input_leaves_like_exit(conn, data_dir):
    """Scenario «Fin de entrada»."""
    terminal = ScriptedTerminal(["uno", None])
    conversation, _, _ = make_conversation(conn, data_dir, terminal)
    assert await conversation.run() == 0
    [session_id] = _session_ids(conn)
    lock = SessionLock(data_dir, __import__("uuid").UUID(session_id))
    assert lock.acquire()
    lock.release()
    assert statuses(conn) == ["completed"]


async def test_help_is_never_sent(conn, data_dir):
    """Scenario «Comando conocido»."""
    terminal = ScriptedTerminal(["/help", "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    assert provider.calls == 0
    assert any(line.strip().startswith("/resume N") for line in terminal.shown)


async def test_an_unknown_command_is_never_sent(conn, data_dir):
    """Scenario «Comando desconocido»."""
    terminal = ScriptedTerminal(["/nada", "/exti", "  /exti", "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    assert provider.calls == 0
    assert statuses(conn) == []
    assert sum("unknown command" in line for line in terminal.shown) == 3


async def test_a_question_that_starts_with_a_slash(conn, data_dir):
    """Scenario «Pregunta que empieza por barra»."""
    terminal = ScriptedTerminal(["//ruta/de/ejemplo es correcta?", "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    assert provider.prompts == ["/ruta/de/ejemplo es correcta?"]


# -- 3.3 the session of the conversation ----------------------------------------------------------


async def test_a_new_session_by_default(conn, data_dir):
    """Scenario «Sesión nueva por defecto»."""
    terminal = ScriptedTerminal(["uno", "/exit"])
    conversation, service, _ = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    [session_id] = _session_ids(conn)
    assert _questions(service, session_id) == ["uno"]
    assert f"session:  {session_id}" in terminal.text


async def test_resuming_a_session_shows_its_history_and_no_other(conn, data_dir):
    """Scenario «Reanudar una sesión existente» and SEC-02."""
    seed, service, _ = make_conversation(conn, data_dir, ScriptedTerminal())
    mine = service.create_session("mía")
    other = service.create_session("otra")
    await service.ask(str(mine.session_id), "pregunta-de-la-mia")
    await service.ask(str(other.session_id), "pregunta-de-la-otra")
    terminal = ScriptedTerminal(["/history", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal)
    await conversation.run(str(mine.session_id))
    assert f"{FOREIGN_PREFIX}pregunta-de-la-mia" in terminal.shown
    assert "pregunta-de-la-otra" not in terminal.text
    assert str(other.session_id) not in terminal.text


async def test_new_switches_session_and_the_old_one_does_not_change(conn, data_dir):
    """Scenario «Cambiar de sesión dentro de la conversación»."""
    terminal = ScriptedTerminal(["uno", "/new", "dos", "/exit"])
    conversation, service, _ = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    first, second = _session_ids(conn)
    assert _questions(service, first) == ["uno"]
    assert _questions(service, second) == ["dos"]
    for session_id in (first, second):  # both are free again
        lock = SessionLock(data_dir, __import__("uuid").UUID(session_id))
        assert lock.acquire()
        lock.release()


async def test_the_old_session_is_free_while_the_new_one_is_held(conn, data_dir):
    def check(term):
        first, second = _session_ids(conn)
        free = SessionLock(data_dir, __import__("uuid").UUID(first))
        held = SessionLock(data_dir, __import__("uuid").UUID(second))
        term.checked = (free.acquire(), held.acquire())
        free.release()
        held.release()

    from tests.shell_support import Action
    terminal = ScriptedTerminal(["/new otra", Action(check), "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    assert terminal.checked == (True, False)


def _resume(session_id):
    """An Action: type `/resume N` with the number /sessions gave to `session_id`."""
    from tests.shell_support import Action

    def run(term):
        line = next(l for l in reversed(term.shown) if str(session_id) in l and l[1:4].strip())
        term.lines.insert(0, f"/resume {line[1:4].strip()}")

    return Action(run)


async def test_sessions_and_resume_by_number(conn, data_dir):
    _, service, _ = make_conversation(conn, data_dir, ScriptedTerminal())
    earlier = service.create_session("anterior")
    await service.ask(str(earlier.session_id), "pregunta-anterior")
    terminal = ScriptedTerminal(["/resume 1", "/sessions", "/resume 9", "/resume x",
                                 _resume(earlier.session_id), "/history", "/status", "/exit"])
    conversation, _, provider = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    assert "run /sessions first" in terminal.text
    assert "a number from 1 to 2" in terminal.text
    assert f"resumed session {earlier.session_id}" in terminal.text
    assert f"{FOREIGN_PREFIX}pregunta-anterior" in terminal.shown
    assert any(line.startswith(f"session:  {earlier.session_id}") for line in terminal.shown)
    assert provider.calls == 0


async def test_resume_of_a_session_in_use_keeps_the_current_one(conn, data_dir):
    _, service, _ = make_conversation(conn, data_dir, ScriptedTerminal())
    busy = service.create_session("ocupada")
    _, lock = service.take_session(str(busy.session_id))
    try:
        terminal = ScriptedTerminal(["/sessions", _resume(busy.session_id), "pregunta", "/exit"])
        conversation, service2, _ = make_conversation(conn, data_dir, terminal)
        await conversation.run()
    finally:
        lock.release()
    assert "is in use by another process" in terminal.text
    current = [s for s in _session_ids(conn) if s != str(busy.session_id)]
    assert _questions(service2, current[0]) == ["pregunta"]
    assert _questions(service2, busy.session_id) == []


async def test_status_names_the_last_request(conn, data_dir):
    terminal = ScriptedTerminal(["uno", "/status", "/exit"])
    conversation, _, _ = make_conversation(conn, data_dir, terminal)
    await conversation.run()
    [request_id] = [row[0] for row in conn.execute("SELECT request_id FROM requests")]
    assert f"last request: {request_id} {RequestStatus.COMPLETED}" in terminal.shown
