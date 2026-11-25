"""Holding a session for several questions (interactive-shell D4, task 3.1)."""

import pytest

from harness.core.contracts import RequestStatus
from harness.core.errors import InvalidInput, SessionBusy
from harness.providers.mock import MockProvider
from tests.conftest import RecordingProvider


async def test_a_taken_session_refuses_a_single_question(make_service, conn):
    service = make_service()
    session = service.create_session("S")
    taken, lock = service.take_session(str(session.session_id))
    try:
        with pytest.raises(SessionBusy):
            await service.ask(str(session.session_id), "x")
        with pytest.raises(SessionBusy):
            service.take_session(str(session.session_id))
        assert conn.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
    finally:
        lock.release()
    assert taken.session_id == session.session_id
    response = await service.ask(str(session.session_id), "x")
    assert response.status is RequestStatus.COMPLETED


async def test_questions_with_the_session_taken_follow_the_rules_of_ask(make_service, conn):
    provider = MockProvider()
    service = make_service({"mock": provider})
    session = service.create_session("S")
    _, lock = service.take_session(str(session.session_id))
    try:
        first = await service.ask_taken(session.session_id, provider, "uno")
        second = await service.ask_taken(session.session_id, provider, "dos")
    finally:
        lock.release()
    assert first.status is second.status is RequestStatus.COMPLETED
    rows = conn.execute("SELECT status FROM requests ORDER BY started_at").fetchall()
    assert [row[0] for row in rows] == ["completed", "completed"]
    assert [e.content for e in service.history(str(session.session_id)) if e.role == "user"] \
        == ["uno", "dos"]


async def test_an_empty_question_is_refused_before_anything_is_recorded(make_service, conn):
    provider = MockProvider()
    service = make_service({"mock": provider})
    session = service.create_session("S")
    _, lock = service.take_session(str(session.session_id))
    try:
        with pytest.raises(InvalidInput):
            await service.ask_taken(session.session_id, provider, "   ")
    finally:
        lock.release()
    assert conn.execute("SELECT count(*) FROM requests").fetchone()[0] == 0


async def test_the_attachment_is_sent_but_never_stored(make_service, conn):
    provider = RecordingProvider()
    service = make_service({"mock": provider})
    session = service.create_session("S")
    _, lock = service.take_session(str(session.session_id))
    try:
        await service.ask_taken(session.session_id, provider, "la pregunta",
                                attachment="CONTENIDO-ADJUNTO-SINTETICO")
    finally:
        lock.release()
    assert provider.prompts == ["CONTENIDO-ADJUNTO-SINTETICO\n\nla pregunta"]
    stored = "\n".join(str(v) for row in conn.execute("SELECT * FROM messages") for v in row)
    assert "la pregunta" in stored
    assert "CONTENIDO-ADJUNTO-SINTETICO" not in stored
