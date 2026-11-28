"""A hostile value reaches the database as data, never as SQL (local-persistence spec)."""

HOSTILE = "x'); DROP TABLE sessions; --"
TABLES = {
    "schema_migrations", "sessions", "requests", "messages", "audit_events", "request_context",
    "skill_runs", "skill_steps", "approvals", "tool_calls", "effect_sources",
    "plan_runs",  # code-mode slice 2
    "workspace_events",  # workspace-tools slice B1 (migration 011)
}


async def test_a_hostile_session_name_is_stored_literally(conn, make_service):
    service = make_service()
    session = service.create_session(HOSTILE)
    await service.ask(str(session.session_id), HOSTILE)

    assert [s.name for s in service.list_sessions()] == [HOSTILE]
    assert [e.content for e in service.history(str(session.session_id))][0] == HOSTILE
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == TABLES
