"""`ask --project`: the memory travels apart from the question and is never stored (D7)."""

import hashlib

import pytest

from harness.core.errors import ProjectMismatch
from harness.memory.context import build_context
from tests.conftest import SECRET_SAMPLES, note_header, query, write_note

CANARY = "CANARIO-SQLITE-4242"


@pytest.fixture
def env(vault):
    return {"HARNESS_VAULT_ROOT": str(vault)}


def _session(cli, project="demo-alpha"):
    args = ["session", "create", "S"] + (["--project", project] if project else [])
    return cli(*args)[1].strip()


def _denied(data_dir):
    """The memory audit events, and that no request or message was recorded."""
    assert query(data_dir, "SELECT count(*) FROM requests") == [(0,)]
    assert query(data_dir, "SELECT count(*) FROM messages") == [(0,)]
    return query(data_dir, "SELECT outcome FROM audit_events WHERE event_type = 'memory.context'")


def _text_values(data_dir):
    """Every text value of every column of every table."""
    values = []
    for (table,) in query(data_dir, "SELECT name FROM sqlite_master WHERE type = 'table'"):
        for row in query(data_dir, f"SELECT * FROM {table}"):
            values += [value for value in row if isinstance(value, str)]
    return values


def test_session_project(cli, env, data_dir, recorder):
    session_id = _session(cli)
    code, out, err = cli("ask", session_id, "pregunta", "--project", "demo-alpha", **env)
    assert code == 0, err
    assert out.strip() == "respuesta sintética"
    (sent,) = recorder.prompts
    assert note_header("projects/demo-alpha/_project.md") in sent and sent.endswith("pregunta")
    assert "context: demo-alpha, 7 note(s) included" in err
    paths = [row[0] for row in query(data_dir, "SELECT note_path FROM request_context")]
    assert sorted(paths) == sorted([
        "projects/demo-alpha/_project.md",
        "Decisiones/alpha-mensajeria.md",
        "Lecciones/2026-11-10-reintentos-idempotentes.md",
        "Memoria-CC/project_alpha-integraciones.md",
        "projects/demo-alpha/sessions/2026-11-21-121500.md",
        "projects/demo-alpha/sessions/2026-11-20-111500.md",
        "projects/demo-alpha/sessions/2026-11-19-101500.md",
    ])
    assert query(data_dir, "SELECT event_type, outcome FROM audit_events"
                           " WHERE event_type = 'memory.context'") == [("memory.context", "ok")]


def test_project_other_than_the_sessions(cli, env, data_dir, recorder):
    session_id = _session(cli)
    code, out, err = cli("ask", session_id, "pregunta", "--project", "demo-beta", **env)
    assert code == 1 and out == ""
    assert "belongs to another project" in err
    assert query(data_dir, "SELECT count(*) FROM requests") == [(0,)]
    assert recorder.prompts == []
    assert query(data_dir, "SELECT outcome FROM audit_events"
                           " WHERE event_type = 'memory.context'") == [("denied",)]


def test_session_without_project(cli, env, data_dir, recorder):
    session_id = _session(cli, project=None)
    code, out, err = cli("ask", session_id, "pregunta", "--project", "demo-alpha", **env)
    assert code == 1 and out == ""
    assert "has no project" in err
    assert _denied(data_dir) == [("denied",)]
    assert recorder.prompts == []


def test_vault_not_configured_registers_nothing(cli, data_dir):
    session_id = _session(cli)
    code, _, err = cli("ask", session_id, "pregunta", "--project", "demo-alpha")
    assert code == 1 and "HARNESS_VAULT_ROOT is not set" in err
    assert _denied(data_dir) == [("denied",)]  # no request, no content: only the event


def test_invalid_project_registers_nothing(cli, env, data_dir):
    session_id = _session(cli)
    code, _, err = cli("ask", session_id, "pregunta", "--project", "../../etc", **env)
    assert code == 1 and "invalid project identifier" in err
    assert _denied(data_dir) == [("denied",)]


def test_missing_project_is_denied(cli, data_dir, vault):
    (vault / "projects" / "demo-gamma").mkdir()
    session_id = _session(cli, project="demo-gamma")
    (vault / "projects" / "demo-gamma").rmdir()
    code, _, err = cli("ask", session_id, "pregunta", "--project", "demo-gamma",
                       HARNESS_VAULT_ROOT=str(vault))
    assert code == 1 and "does not exist" in err
    assert _denied(data_dir) == [("denied",)]


def test_refusals_before_the_project_record_nothing(cli, env, data_dir):
    # A missing session or an empty prompt is refused as for any question: no memory event.
    session_id = _session(cli)
    assert cli("ask", session_id, "  ", "--project", "demo-alpha", **env)[0] == 1
    assert _denied(data_dir) == []


def test_canary_of_a_note_stays_out_of_sqlite(cli, env, vault, data_dir):
    # The real Mock: its content is synthetic, so the question is stored, and still the
    # memory block is not.
    note = write_note(vault, "Decisiones/alpha-canario.md", f"Dato sintético {CANARY}.",
                      project_slug="demo-alpha")
    session_id = _session(cli)
    code, out, err = cli("ask", session_id, "pregunta", "--project", "demo-alpha", **env)
    assert code == 0, err
    sent_chars = int(out.split("Received ")[1].split(" ")[0])
    assert sent_chars > len("pregunta") + 1000  # the block did go to the provider

    assert not [value for value in _text_values(data_dir) if CANARY in value]
    raw = note.read_bytes()
    assert query(
        data_dir,
        "SELECT sha256, bytes, truncated FROM request_context WHERE note_path = ?",
        ("Decisiones/alpha-canario.md",),
    ) == [(hashlib.sha256(raw).hexdigest(), len(raw), 0)]
    # The control: the same search does find text that was stored.
    assert [value for value in _text_values(data_dir) if value == "pregunta"]


def test_history_with_the_original_question(cli, env):
    session_id = _session(cli)
    cli("ask", session_id, "Resume el contexto", "--project", "demo-alpha", **env)
    code, out, _ = cli("history", session_id)
    assert code == 0
    lines = out.strip().splitlines()
    assert lines[0] == "[completed] user: Resume el contexto"
    assert "MEMORIA" not in out and note_header("projects/demo-alpha/_project.md") not in out


def test_token_in_a_note_sent_to_the_provider(cli, env, vault, recorder):
    token = SECRET_SAMPLES["github"]
    write_note(vault, "Decisiones/alpha-despliegue.md", f"despliegue con {token}",
               project_slug="demo-alpha")
    session_id = _session(cli)
    code, _, err = cli("ask", session_id, "pregunta", "--project", "demo-alpha", **env)
    assert code == 0
    (sent,) = recorder.prompts
    assert "[REDACTED:github]" in sent and token not in sent
    assert token not in err and "1 credential(s) redacted" in err


def test_truncated_note_is_recorded_as_truncated(cli, env, vault, data_dir):
    write_note(vault, "Decisiones/alpha-larga.md", "palabra " * 600, project_slug="demo-alpha")
    session_id = _session(cli)
    assert cli("ask", session_id, "pregunta", "--project", "demo-alpha", **env)[0] == 0
    assert query(
        data_dir, "SELECT truncated FROM request_context WHERE note_path = ?",
        ("Decisiones/alpha-larga.md",),
    ) == [(1,)]


async def test_service_refuses_a_context_of_another_project(conn, make_service, vault):
    service = make_service()
    session = service.create_session("S", "demo-alpha")
    context = build_context(vault.resolve(), "demo-beta", 8192)
    with pytest.raises(ProjectMismatch):
        await service.ask(str(session.session_id), "pregunta", context)
    assert conn.execute("SELECT count(*) FROM requests").fetchone()[0] == 0
