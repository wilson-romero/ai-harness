"""The `hls-review` skill (spec hls-review, design D1), with the repository's own skill folder."""

from __future__ import annotations

import asyncio
import json
import shutil

import pytest

from harness.core.errors import InvalidInput
from harness.memory.context import build_context
from harness.skills.config import DEFAULT_SKILLS_DIR
from tests.conftest import REPO_ROOT, fingerprint, run_main
from tests.skill_support import ScriptedProvider, build

INPUTS = REPO_ROOT / "tests" / "fixtures" / "skill-inputs"
KEY = "tarea: hls-review/review"


def _fixture(name: str) -> str:
    return (INPUTS / name).read_text(encoding="utf-8")


def _engine(conn, data_dir, vault, answer=None, **kwargs):
    provider = ScriptedProvider({KEY: answer or _fixture("hls-review-ok.md")})
    return build(
        conn, data_dir, provider=provider, root=DEFAULT_SKILLS_DIR,
        project_context=lambda project: build_context(vault, project, 16_000), **kwargs,
    )


def _run(engine, session, **inputs):
    return asyncio.run(engine.run("hls-review", str(session.session_id), inputs))


def _context_rows(conn):
    return conn.execute(
        "SELECT note_path, sha256 FROM request_context ORDER BY note_path").fetchall()


def test_complete_review_with_the_mock(conn, data_dir, vault):
    engine, sessions, provider = _engine(conn, data_dir, vault)
    session = sessions.create_session("Revisión", "demo-alpha")
    outcome = _run(engine, session, document=_fixture("hls-corto.md"))
    assert outcome.status == "completed"
    assert "## Preguntas pendientes" in outcome.output
    assert provider.calls == 1
    prompt = provider.prompts[0]
    assert "<<<MEMORIA" in prompt and "projects/demo-alpha/_project.md" in prompt
    # The document is inside the data markers of the reference, after the instructions.
    start = prompt.index("inputs.document")
    assert "Servicio sintético de pedidos" in prompt[start:]
    assert prompt.index(KEY) < start


def test_session_without_project_is_refused_before_the_vault_and_the_provider(conn, data_dir,
                                                                               vault):
    read = []
    engine, sessions, provider = build(
        conn, data_dir, provider=ScriptedProvider({KEY: "x"}), root=DEFAULT_SKILLS_DIR,
        project_context=lambda project: read.append(project),
    )
    session = sessions.create_session("Sin proyecto")
    with pytest.raises(InvalidInput, match="has no project"):
        _run(engine, session, document="doc")
    assert read == [] and provider.calls == 0
    assert conn.execute("SELECT count(*) FROM skill_runs").fetchone()[0] == 0


def test_missing_document_is_refused_before_the_run(conn, data_dir, vault):
    engine, sessions, provider = _engine(conn, data_dir, vault)
    session = sessions.create_session("Revisión", "demo-alpha")
    with pytest.raises(InvalidInput, match="'document' is required"):
        _run(engine, session)
    assert conn.execute("SELECT count(*) FROM skill_runs").fetchone()[0] == 0
    assert provider.calls == 0


def test_answer_without_pending_questions_fails_naming_the_heading(conn, data_dir, vault):
    engine, sessions, _ = _engine(conn, data_dir, vault, _fixture("hls-review-incompleta.md"))
    session = sessions.create_session("Revisión", "demo-alpha")
    outcome = _run(engine, session, document=_fixture("hls-corto.md"))
    assert outcome.status == "failed"
    assert outcome.output is None
    code = conn.execute("SELECT error_code FROM skill_runs").fetchone()[0]
    assert code == "validation_failed:required_headings:Preguntas pendientes"


def test_the_template_asks_to_separate_evidence_assumption_and_proposal(conn, data_dir, vault):
    engine, sessions, provider = _engine(conn, data_dir, vault)
    session = sessions.create_session("Revisión", "demo-alpha")
    _run(engine, session, document=_fixture("hls-corto.md"))
    prompt = provider.prompts[0]
    instructions = prompt[prompt.index(KEY):prompt.index("inputs.document")]
    for word in ("evidencia", "supuesto", "propuesta", "no inventes"):
        assert word in instructions.casefold(), word


def test_the_review_writes_nothing_in_the_vault(conn, data_dir, vault, tmp_path):
    engine, sessions, _ = _engine(conn, data_dir, vault)
    session = sessions.create_session("Revisión", "demo-alpha")
    before = fingerprint(vault)
    outside = {p for p in fingerprint(tmp_path) if not p.startswith("data")}
    outcome = _run(engine, session, document=_fixture("hls-corto.md"))
    assert outcome.status == "completed"
    assert fingerprint(vault) == before
    assert {p for p in fingerprint(tmp_path) if not p.startswith("data")} == outside


def test_orders_inside_the_document_change_nothing(conn, data_dir, vault):
    engine, sessions, _ = _engine(conn, data_dir, vault)
    plain = sessions.create_session("Sin órdenes", "demo-alpha")
    _run(engine, plain, document=_fixture("hls-corto.md"))
    rows_plain = _context_rows(conn)
    conn.execute("DELETE FROM request_context")
    before = fingerprint(vault)
    orders = sessions.create_session("Con órdenes", "demo-alpha")
    outcome = _run(engine, orders, document=_fixture("hls-con-ordenes.md"))
    assert outcome.status == "completed"
    assert _context_rows(conn) == rows_plain
    assert conn.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0
    steps = conn.execute(
        "SELECT DISTINCT step_key FROM skill_steps ORDER BY step_key").fetchall()
    assert [s[0] for s in steps] == ["check", "review"]
    assert fingerprint(vault) == before


def test_the_skill_has_no_approval_and_no_effect():
    workflow = json.loads((DEFAULT_SKILLS_DIR / "hls-review" / "workflow.json").read_text(
        encoding="utf-8"))
    assert [step["kind"] for step in workflow["steps"]] == ["llm", "validate"]


def test_cli_review_by_stdout_and_vault_untouched(data_dir, vault, tmp_path):
    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps({KEY: _fixture("hls-review-ok.md")}), encoding="utf-8")
    env = {"HARNESS_VAULT_ROOT": str(vault), "HARNESS_MOCK_RESPONSES": str(responses)}
    session = run_main(data_dir, "session", "create", "Demo", "--project", "demo-alpha", **env)
    assert session.returncode == 0, session.stderr
    document = tmp_path / "hls.md"
    shutil.copyfile(INPUTS / "hls-corto.md", document)
    before = fingerprint(vault)
    result = run_main(data_dir, "skill", "run", "hls-review", "--session",
                      session.stdout.strip(), "--input-file", f"document={document}", **env)
    assert result.returncode == 0, result.stderr
    assert "## Preguntas pendientes" in result.stdout
    assert fingerprint(vault) == before


def test_listed_valid_with_its_two_steps(data_dir):
    listing = run_main(data_dir, "skill", "list")
    assert listing.returncode == 0, listing.stderr
    assert any(line.split("\t")[:3] == ["hls-review", "1.0.0", "valid"]
               for line in listing.stdout.splitlines())
    shown = run_main(data_dir, "skill", "show", "hls-review")
    assert "step 1: review llm template=templates/review.md memory=project" in shown.stdout
    assert "step 2: check validate of=review format=markdown" in shown.stdout
