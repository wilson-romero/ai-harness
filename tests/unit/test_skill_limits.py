"""Execution limits (skill-engine D14; SEC-15). Each stop leaves one `skill.limit` event."""

import asyncio

from tests.skill_support import GOOD_ECHO, FakeTerminal, ScriptedProvider, build, copy_skills


def _limits(conn):
    return [tuple(r) for r in conn.execute(
        "SELECT outcome, detail FROM audit_events WHERE event_type = 'skill.limit'")]


def _run(engine, session, text="hola"):
    return asyncio.run(engine.run("demo-echo", str(session.session_id), {"text": text}))


def _setup(conn, data_dir, answer=GOOD_ECHO, **kwargs):
    provider = ScriptedProvider({"tarea: demo-echo/draft": answer})
    engine, sessions, _ = build(conn, data_dir, provider=provider, **kwargs)
    return engine, sessions.create_session("Demo"), provider


def _check_failed_draft(conn, code):
    steps = {r["step_key"]: r for r in conn.execute("SELECT * FROM skill_steps")}
    draft = steps["draft"]
    assert (draft["status"], draft["error_code"]) == ("failed", code)
    assert draft["output_text"] is None and draft["output_sha256"] is None
    assert steps["check"]["status"] == "pending"  # nothing after the stop ran
    assert conn.execute("SELECT status, error_code FROM skill_runs").fetchone()[:] == (
        "failed", code)


def test_response_too_large(conn, data_dir):
    engine, session, _ = _setup(conn, data_dir, answer="x" * 131_073)
    assert _run(engine, session).status == "failed"
    _check_failed_draft(conn, "limit:response_bytes")
    assert _limits(conn) == [("response_bytes", "step=draft;limit=response_bytes")]
    # The step keeps no output; the session history keeps the answer like any answer of a
    # synthetic provider (as `ask` does, which has no size limit) (review, 2026-11-24).
    assert [tuple(r) for r in conn.execute(
        "SELECT role, length(content) FROM messages ORDER BY rowid")] == [
        ("user", len("[skill demo-echo/draft intento 1]")), ("assistant", 131_073)]


def test_response_too_large_from_a_real_provider_is_stored_nowhere(conn, data_dir):
    provider = ScriptedProvider({"tarea: demo-echo/draft": "y" * 131_073}, synthetic=False)
    engine, sessions, _ = build(conn, data_dir, provider=provider,
                                terminal=FakeTerminal(interactive=True))
    assert _run(engine, sessions.create_session("Demo")).status == "failed"
    _check_failed_draft(conn, "limit:response_bytes")
    assert [tuple(r) for r in conn.execute("SELECT role, content FROM messages ORDER BY rowid")
            ] == [("user", None), ("assistant", None)]


def test_response_too_large_in_utf8_bytes_only(conn, data_dir):
    answer = "€" * 43_691  # 43 691 characters, 131 073 bytes
    engine, session, _ = _setup(conn, data_dir, answer=answer)
    assert _run(engine, session).status == "failed"
    _check_failed_draft(conn, "limit:response_bytes")


def test_response_at_the_limit_passes_the_llm_step(conn, data_dir):
    engine, session, _ = _setup(conn, data_dir, answer="x" * 131_072)
    _run(engine, session)
    assert conn.execute("SELECT status FROM skill_steps WHERE step_key = 'draft'"
                        ).fetchone()[0] == "completed"


def test_prompt_too_large(conn, data_dir):
    engine, session, provider = _setup(conn, data_dir)
    assert _run(engine, session, text="x" * 65_536).status == "failed"
    assert provider.calls == 0
    _check_failed_draft(conn, "limit:prompt_bytes")
    assert _limits(conn) == [("prompt_bytes", "step=draft;limit=prompt_bytes")]


def test_proposal_too_large(conn, data_dir, tmp_path):
    root = copy_skills(tmp_path)
    workflow = root / "demo-echo" / "workflow.json"
    workflow.write_text(workflow.read_text(encoding="utf-8").replace(
        '"max_bytes": 32768', '"max_bytes": 65536'), encoding="utf-8")
    answer = GOOD_ECHO + "\n" + "y" * 32_768
    engine, session, _ = _setup(conn, data_dir, answer=answer, root=root)
    assert _run(engine, session).status == "failed"
    confirm = conn.execute("SELECT status, error_code FROM skill_steps WHERE step_key = 'confirm'"
                           ).fetchone()
    assert tuple(confirm) == ("failed", "limit:proposal_bytes")
    assert conn.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0
    assert _limits(conn) == [("proposal_bytes", "step=confirm;limit=proposal_bytes")]


def test_run_time_limit(conn, data_dir):
    ticks = iter([0.0, 0.0, 1801.0, 1801.0, 1801.0])
    engine, session, provider = _setup(conn, data_dir, monotonic=lambda: next(ticks))
    outcome = _run(engine, session)
    assert outcome.status == "failed" and provider.calls == 1
    check = conn.execute("SELECT status, error_code FROM skill_steps WHERE step_key = 'check'"
                         ).fetchone()
    assert tuple(check) == ("failed", "limit:run_time")
    assert _limits(conn) == [("run_time", "step=check;limit=run_time")]


def test_step_deadline_is_bounded_by_the_run_time_left(conn, data_dir, tmp_path):
    root = copy_skills(tmp_path)
    provider = ScriptedProvider(hang_after_send=True)
    times = iter([0.0, 0.0, 1799.5, 1799.5] + [1800.0] * 20)
    engine, sessions, _ = build(conn, data_dir, provider=provider, root=root,
                                monotonic=lambda: next(times))
    session = sessions.create_session("Demo")
    outcome = _run(engine, session)  # the step declares 30 s; only 0.5 s were left
    assert outcome.status == "uncertain"


class _CutProvider(ScriptedProvider):
    """Reports, as the Copilot provider does, that only part of the answer was read."""

    def __init__(self, cut: bool) -> None:
        super().__init__()
        self.cut = cut

    async def ask(self, request, on_sent, *, events) -> str:
        text = await super().ask(request, on_sent)
        if self.cut:
            events.truncated()
        return text


def test_a_truncated_answer_is_never_a_steps_output(conn, data_dir):
    """Review 2026-11-26: a reply read only in part (the character cap, or the walk bound
    of the page reader) is refused like one that is too large, never checked as complete."""
    engine, sessions, _ = build(conn, data_dir, provider=_CutProvider(cut=True))
    assert _run(engine, sessions.create_session("Demo")).status == "failed"
    _check_failed_draft(conn, "limit:response_truncated")
    assert _limits(conn) == [("response_truncated", "step=draft;limit=response_truncated")]


def test_control_the_same_answer_read_whole_passes_the_llm_step(conn, data_dir):
    engine, sessions, _ = build(conn, data_dir, provider=_CutProvider(cut=False))
    _run(engine, sessions.create_session("Demo"))
    assert conn.execute("SELECT status FROM skill_steps WHERE step_key = 'draft'"
                        ).fetchone()[0] == "completed"
