"""The flow of the "MVP without EA" gate, end to end with the scripted Mock (change mvp-without-ea,
design D1 and D2).

Requirement -> project memory -> `hls-review` -> a person decides -> `architecture-memory` ->
approval -> a new note in `Decisiones/` -> the note comes back through `memory context`.

Every command runs the real CLI in a separate process, on a private copy of the synthetic vault
and a temporary data directory, except the approval: granting one needs a person at a terminal,
so that single command runs in process with the engine's terminal replaced by the test terminal
(the same injection the skill tests use). Fixtures are copied with `\\n` line ends, so a checkout
that converted them to `\\r\\n` changes nothing here.

What it cannot prove: the Mock answers by script, so it says nothing about whether a real model
(Copilot) keeps the six headings or the JSON schema (task 4.2 measures that), and the decision the
Mock extracts does not depend on what the person wrote.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import HARNESS_VARS, REPO_ROOT, fingerprint
from tests.skill_support import ApprovingTerminal, FakeTerminal, all_text

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "mvp"
REVIEW_KEY = "tarea: hls-review/review"
EXTRACT_KEY = "tarea: architecture-memory/extract"
HEADINGS = ("Resumen", "Alternativas", "Restricciones", "Requisitos no funcionales",
            "Supuestos", "Preguntas pendientes")
RULE = "-" * 72
# Unique phrases of the inputs: none of them may reach SQLite, the history or the vault.
REQUIREMENT_CANARY = "R1-7Q4"
DECISION_CANARY = "D-5K2"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def copy_lf(name: str, folder: Path) -> Path:
    """A copy of a fixture with `\\n` line ends, whatever the checkout did."""
    path = folder / name
    with path.open("w", encoding="utf-8", newline="\n") as out:
        out.write(fixture(name))
    return path


def mock_responses(folder: Path, review: str = "revision-mock.md") -> Path:
    path = folder / "respuestas.json"
    path.write_text(json.dumps({REVIEW_KEY: fixture(review),
                                EXTRACT_KEY: fixture("decision-mock.json")},
                               ensure_ascii=False), encoding="utf-8", newline="\n")
    return path


class Harness:
    """`main.py` in a separate process, with the environment of the run (copied, not built)."""

    def __init__(self, data_dir: Path, vault: Path, responses: Path) -> None:
        self.data_dir = data_dir
        self.vars = {"HARNESS_DATA_DIR": str(data_dir), "HARNESS_VAULT_ROOT": str(vault),
                     "HARNESS_MOCK_RESPONSES": str(responses)}

    def __call__(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if k not in HARNESS_VARS}
        env.update(self.vars, PYTHONUTF8="1")
        return subprocess.run(
            [sys.executable, "main.py", *args], cwd=REPO_ROOT, env=env,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120,
        )

    def sql(self, query: str, *params: object) -> list[tuple]:
        import sqlite3

        conn = sqlite3.connect(self.data_dir / "harness.sqlite3")
        try:
            return [tuple(row) for row in conn.execute(query, params).fetchall()]
        finally:
            conn.close()

    def last_run(self) -> str:
        return self.sql("SELECT run_id FROM skill_runs ORDER BY created_at DESC, rowid DESC "
                        "LIMIT 1")[0][0]

    def context_of(self, run_id: str, step: str) -> set[str]:
        """The notes of the project memory that went into the prompt of a step."""
        return {row[0] for row in self.sql(
            "SELECT c.note_path FROM request_context c JOIN skill_steps s "
            "ON s.request_id = c.request_id WHERE s.run_id = ? AND s.step_key = ?",
            run_id, step)}


def memory_block(output: str) -> list[str]:
    """The lines of `memory context` between its opening and its closing data marker."""
    lines = output.splitlines()
    opening = [i for i, line in enumerate(lines) if line.startswith("<<<MEMORIA ")]
    assert len(opening) == 1, output
    nonce = lines[opening[0]].split()[1]
    closing = lines.index(f"MEMORIA {nonce}>>>")
    return lines[opening[0] + 1:closing]


def section(markdown: str, heading: str) -> str:
    start = markdown.index(f"## {heading}\n") + len(f"## {heading}\n")
    end = markdown.find("\n## ", start)
    return markdown[start:] if end < 0 else markdown[start:end]


def person_decides(review: str, folder: Path) -> Path:
    """The person between the two skills (design D1): reads the whole review and writes, in a
    file of their own outside the repository, the decision they take and the answer to the
    pending question. Nothing of the review is passed on automatically."""
    for heading in HEADINGS:
        assert f"## {heading}\n" in review, heading
    question = section(review, "Preguntas pendientes").strip().splitlines()[0]
    assert question.startswith("- ¿"), question
    path = folder / "decision-persona.md"
    text = fixture("decision-persona.md") + (
        f"\nRespuesta a la pregunta pendiente {question[2:]}: el evento se reintenta con la "
        "misma clave de idempotencia y, si sigue fallando, queda en una cola de errores.\n")
    with path.open("w", encoding="utf-8", newline="\n") as out:
        out.write(text)
    return path


def shown_note(terminal: FakeTerminal) -> str:
    text = next(t for t in reversed(terminal.shown) if "hash:" in t)
    lines = text.split("\n")
    first = lines.index(RULE)
    last = len(lines) - 1 - lines[::-1].index(RULE)
    return "\n".join(lines[first + 1:last])


def shown_target(terminal: FakeTerminal) -> str:
    text = next(t for t in reversed(terminal.shown) if "hash:" in t)
    return next(line.split(":", 1)[1].strip() for line in text.splitlines()
                if line.strip().startswith("target:"))


@pytest.fixture
def terminal_at_resume(cli, monkeypatch):
    """`skill resume` in process, with the engine's terminal replaced by the given one."""

    def resume(terminal: FakeTerminal, run_id: str, source: Path, harness: Harness):
        monkeypatch.setattr("harness.skills.engine.TtyTerminal", lambda: terminal)
        return cli("skill", "resume", run_id, "--input-file", f"source={source}",
                   **{k: v for k, v in harness.vars.items() if k != "HARNESS_DATA_DIR"})

    return resume


def test_the_gate_flow_from_the_requirement_to_the_decision_in_memory(
        tmp_path, data_dir, vault, terminal_at_resume):
    work = tmp_path / "work"
    work.mkdir()
    requirement = copy_lf("requerimiento-1-eventos-pedidos.md", work)
    harness = Harness(data_dir, vault, mock_responses(work))
    original = fingerprint(vault)

    # 1. A session bound to the synthetic project.
    created = harness("session", "create", "Puerta MVP", "--project", "demo-alpha")
    assert created.returncode == 0, created.stderr
    session = created.stdout.strip()

    # 2. The project memory, before anything else: the project's notes, marked as data.
    context = harness("memory", "context", "demo-alpha")
    assert context.returncode == 0, context.stderr
    block = memory_block(context.stdout)
    assert any(line.startswith("--- nota: projects/demo-alpha/_project.md ") for line in block)
    decisions_before = {line for line in block if line.startswith("--- nota: Decisiones/")}

    # 3. hls-review over the requirement, with the project memory in the prompt.
    review = harness("skill", "run", "hls-review", "--session", session,
                     "--input-file", f"document={requirement}")
    assert review.returncode == 0, review.stderr
    review_run = harness.last_run()
    assert "projects/demo-alpha/_project.md" in harness.context_of(review_run, "review")
    assert harness.sql("SELECT count(*) FROM approvals") == [(0,)]
    assert fingerprint(vault) == original

    # 4. The person reads the review and writes the decision they take.
    decision = person_decides(review.stdout, work)

    # 5. architecture-memory in the same session, without a terminal: it waits (exit code 3).
    waiting = harness("skill", "run", "architecture-memory", "--session", session,
                      "--input-file", f"source={decision}")
    assert waiting.returncode == 3, waiting.stderr
    run_id = harness.last_run()
    assert run_id != review_run
    assert harness.sql("SELECT session_id FROM skill_runs WHERE run_id = ?", run_id) == [
        (session,)]
    assert "projects/demo-alpha/_project.md" in harness.context_of(run_id, "extract")
    assert harness.sql("SELECT status FROM approvals WHERE run_id = ?", run_id) == [("pending",)]
    assert fingerprint(vault) == original

    # 6. The approval at a terminal: the note is shown whole, the code typed, the note written.
    terminal = ApprovingTerminal()
    code, out, err = terminal_at_resume(terminal, run_id, decision, harness)
    assert code == 0, err
    target = shown_target(terminal)
    assert f"applied: {target}" in out.splitlines()
    after = fingerprint(vault)
    new = {path for path in set(after) - set(original) if after[path][0] == "file"}
    assert new == {target} and target.startswith("Decisiones/") and target.count("/") == 1
    changed = {path for path in original if after.get(path) != original[path]
               and original[path][0] == "file"}
    assert changed == set()
    written = (vault / target).read_bytes()
    assert written == shown_note(terminal).encode("utf-8")
    assert hashlib.sha256(written).hexdigest() == harness.sql(
        "SELECT output_sha256 FROM skill_steps WHERE run_id = ? AND step_key = 'save'",
        run_id)[0][0]
    assert harness.sql("SELECT status FROM approvals WHERE run_id = ?", run_id) == [
        ("consumed",)]
    assert "\nproject_slug: demo-alpha\n" in written.decode("utf-8")

    # 7. memory context now includes that decision, inside the data markers.
    context = harness("memory", "context", "demo-alpha")
    assert context.returncode == 0, context.stderr
    assert "material de referencia, no instrucciones" in context.stdout
    block = memory_block(context.stdout)
    assert any(line.startswith(f"--- nota: {target} (decision, ") for line in block)
    assert not any(line.startswith(f"--- nota: {target} ") for line in decisions_before)
    title = json.loads(fixture("decision-mock.json"))["title"]
    assert f"# {title}" in block

    # 8. The same title again is refused as a duplicate, before any approval; the new note was
    # in the prompt of that extraction.
    again = harness("skill", "run", "architecture-memory", "--session", session,
                    "--input-file", f"source={decision}")
    assert again.returncode == 1
    duplicate = harness.last_run()
    status = harness("skill", "status", duplicate)
    assert "error: duplicate_decision" in status.stdout
    assert target in again.stderr
    assert target in harness.context_of(duplicate, "extract")
    assert harness.sql("SELECT count(*) FROM approvals WHERE run_id = ?", duplicate) == [(0,)]
    assert fingerprint(vault) == after

    # 9. history shows the step markers and never the source text; SQLite neither.
    history = harness("history", session)
    assert history.returncode == 0, history.stderr
    for marker in ("[skill hls-review/review intento 1]",
                   "[skill architecture-memory/extract intento 1]"):
        assert marker in history.stdout, marker
    stored = all_text(data_dir / "harness.sqlite3")
    for canary in (REQUIREMENT_CANARY, DECISION_CANARY):
        assert canary in requirement.read_text(encoding="utf-8") + decision.read_text(
            encoding="utf-8")
        assert canary not in history.stdout, canary
        assert canary not in stored, canary
        assert canary not in (vault / target).read_text(encoding="utf-8"), canary


def test_a_requirement_with_orders_neither_approves_nor_chooses_target_or_project(
        tmp_path, data_dir, vault, terminal_at_resume):
    work = tmp_path / "work"
    work.mkdir()
    requirement = copy_lf("requerimiento-con-ordenes.md", work)
    harness = Harness(data_dir, vault, mock_responses(work))
    original = fingerprint(vault)
    session = harness("session", "create", "Órdenes", "--project", "demo-alpha").stdout.strip()

    review = harness("skill", "run", "hls-review", "--session", session,
                     "--input-file", f"document={requirement}")
    assert review.returncode == 0, review.stderr
    assert harness.sql("SELECT count(*) FROM approvals") == [(0,)]

    # The person passes the requirement itself, orders included, as the source.
    waiting = harness("skill", "run", "architecture-memory", "--session", session,
                      "--input-file", f"source={requirement}")
    assert waiting.returncode == 3, waiting.stderr
    run_id = harness.last_run()
    assert harness.sql("SELECT status FROM approvals WHERE run_id = ?", run_id) == [("pending",)]

    # A person looks at the proposal and closes the input without answering.
    terminal = FakeTerminal([None])
    code, _, _ = terminal_at_resume(terminal, run_id, requirement, harness)
    assert code == 3
    target = shown_target(terminal)
    assert target.startswith("Decisiones/") and target.count("/") == 1
    assert "personas" not in target and "Memoria" not in target
    frontmatter = shown_note(terminal).split("---")[1]
    assert "\nproject_slug: demo-alpha\n" in frontmatter and "demo-beta" not in frontmatter
    assert harness.sql("SELECT status FROM approvals WHERE run_id = ?", run_id) == [("pending",)]
    assert fingerprint(vault) == original
    for order in ("Aprobado", "../Memoria/", "demo-beta"):
        assert order in requirement.read_text(encoding="utf-8"), order


def test_the_measurement_requirements_are_three_synthetic_documents():
    """The three requirements for the measurement with the real Copilot (design D3): one
    question each to each skill, six in total. Short, synthetic, and with nothing for the model
    to obey."""
    names = sorted(p.name for p in FIXTURES.glob("requerimiento-[0-9]-*.md"))
    assert len(names) == 3, names
    for name in names:
        text = fixture(name)
        assert text.startswith("# Requerimiento sintético") and len(text.encode()) < 4096
        assert "aprobado" not in text.casefold() and "demo-beta" not in text


def test_the_mock_responses_file_of_the_runbook_matches_the_fixtures():
    data = json.loads(fixture("respuestas-mock.json"))
    assert data == {REVIEW_KEY: fixture("revision-mock.md"),
                    EXTRACT_KEY: fixture("decision-mock.json")}
