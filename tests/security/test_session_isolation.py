"""SEC-02: one session never sees or stores data of another."""

import sqlite3

import pytest

from harness.storage import repositories as repo
from harness.storage.database import transaction

CANARY = "ZZ-CANARY-7731"


async def test_cross_session_message_is_rejected_by_storage(conn, make_service):
    service = make_service()
    a = service.create_session("A")
    b = service.create_session("B")
    response = await service.ask(str(a.session_id), "question for A")
    before = conn.execute("SELECT count(*) FROM messages").fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError), transaction(conn):
        repo.insert_message(
            conn,
            session_id=b.session_id,
            request_id=response.request_id,
            role="assistant",
            content="smuggled",
        )
    assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == before


async def test_history_does_not_mix_sessions(make_service):
    service = make_service()
    a = service.create_session("A")
    b = service.create_session("B")
    await service.ask(str(a.session_id), "only in A")
    await service.ask(str(b.session_id), "only in B")

    contents_a = [e.content for e in service.history(str(a.session_id))]
    assert "only in A" in contents_a
    assert not any("only in B" in (c or "") for c in contents_a)


async def test_audit_never_stores_the_prompt(conn, make_service):
    service = make_service()
    session = service.create_session("Audited")
    response = await service.ask(str(session.session_id), f"please review {CANARY}")

    events = conn.execute("SELECT * FROM audit_events").fetchall()
    for_request = [e for e in events if e["request_id"] == str(response.request_id)]
    assert len(for_request) >= 1
    assert any(e["event_type"] == "session.created" for e in events)
    dumped = "\n".join(str(tuple(e)) for e in events)
    assert CANARY not in dumped
    # The canary is stored where it should be, so the check above can tell the difference.
    assert conn.execute(
        "SELECT count(*) FROM messages WHERE content LIKE ?", (f"%{CANARY}%",)
    ).fetchone()[0] == 1
