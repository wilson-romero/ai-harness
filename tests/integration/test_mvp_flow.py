"""The flow of the "MVP without EA" gate, end to end with a scripted provider (change
mvp-without-ea, design D1 and D2).

Requirement -> project memory -> `hls-review` -> a person decides -> `architecture-memory` ->
approval -> a new note in `Decisiones/` -> the note comes back through `memory context`.

`session create`, `memory context`, `skill status` and `history` run the real CLI in a separate
process. The two skill commands run the same CLI in process (`harness.cli.main`), with two test
doubles injected where the product takes them: the provider is a scripted one that keeps, in
memory only, the exact prompts it received (so the test can check what reached the provider:
the project memory, the requirement, the person's decision), and the engine's terminal is the
test terminal (granting an approval needs a person). Fixtures are copied with `\\n` line ends,
so a checkout that converted them to `\\r\\n` changes nothing here.

What it cannot prove: the provider answers by script, so this says nothing about whether a real
model (Copilot) keeps the six headings or the JSON schema (task 4.2 measures that), nor whether
the decision it extracts follows what the person wrote.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import HARNESS_VARS, REPO_ROOT, fingerprint, note_header
from tests.skill_support import (
    ApprovingTerminal,
    FakeTerminal,
    ScriptedProvider,
    all_text,
    unmark_rows,
)

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "mvp"
REVIEW_KEY = "tarea: hls-review/review"
EXTRACT_KEY = "tarea: architecture-memory/extract"
HEADINGS = ("Resumen", "Alternativas", "Restricciones", "Requisitos no funcionales",
            "Supuestos", "Preguntas pendientes")
RULE = "-" * 72
PROJECT_NOTE = note_header("projects/demo-alpha/_project.md")
# Unique phrases of the inputs: they must reach the provider, and never SQLite, the history or
# the vault.
REQUIREMENT_CANARY = "R1-7Q4"
DECISION_CANARY = "D-5K2"
NOTE_NAME = re.compile(r"^Decisiones/\d{4}-\d{2}-\d{2}-[a-z0-9-]+-[0-9a-f]{8}\.md$")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def copy_lf(name: str, folder: Path) -> Path:
    """A copy of a fixture with `\\n` line ends, whatever the checkout did."""
    path = folder / name
    with path.open("w", encoding="utf-8", newline="\n") as out:
        out.write(fixture(name))
    return path


def scripted(decision: str | None = None) -> ScriptedProvider:
    return ScriptedProvider({REVIEW_KEY: fixture("revision-mock.md"),
                             EXTRACT_KEY: decision or fixture("decision-mock.json")})


class Harness:
    """`main.py` in a separate process, with the environment of the run (copied, not built)."""

    def __init__(self, data_dir: Path, vault: Path) -> None:
        self.data_dir = data_dir
        self.vars = {"HARNESS_DATA_DIR": str(data_dir), "HARNESS_VAULT_ROOT": str(vault)}

    def __call__(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if k not in HARNESS_VARS}
        env.update(self.vars, PYTHONUTF8="1")
        return subprocess.run(
            [sys.executable, "main.py", *args], cwd=REPO_ROOT, env=env,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120,
        )

    def sql(self, query: str, *params: object) -> list[tuple]:
        conn = sqlite3.connect(self.data_dir / "harness.sqlite3")
        try:
            return [tuple(row) for row in conn.execute(query, params).fetchall()]
        finally:
            conn.close()

    def last_run(self) -> str:
        return self.sql("SELECT run_id FROM skill_runs ORDER BY created_at DESC, rowid DESC "
                        "LIMIT 1")[0][0]

    def context_of(self, run_id: str, step: str) -> set[str]:
        """The notes recorded as sent with a step (`request_context`); not the prompt itself."""
        return {row[0] for row in self.sql(
            "SELECT c.note_path FROM request_context c JOIN skill_steps s "
            "ON s.request_id = c.request_id WHERE s.run_id = ? AND s.step_key = ?",
            run_id, step)}


@pytest.fixture
def skill_cli(cli, monkeypatch, vault):
    """`skill ...` through the real CLI in process, with the given provider and terminal."""

    def run(provider: ScriptedProvider, terminal: FakeTerminal, *args: str):
        factory = lambda settings: lambda name: provider  # noqa: E731
        monkeypatch.setattr("harness.cli.provider_factory", factory)
        monkeypatch.setattr("harness.skills.commands.provider_factory", factory)
        monkeypatch.setattr("harness.skills.engine.TtyTerminal", lambda: terminal)
        return cli("skill", *args, HARNESS_VAULT_ROOT=str(vault))

    return run


def memory_block(text: str) -> list[str]:
    """The lines between the opening and the closing marker of the memory block."""
    lines = text.splitlines()
    opening = [i for i, line in enumerate(lines) if line.startswith("<<<MEMORIA ")]
    assert len(opening) == 1, text[:400]
    nonce = lines[opening[0]].split()[1]
    closing = lines.index(f"MEMORIA {nonce}>>>")
    return lines[opening[0] + 1:closing]


def data_block(prompt: str, key: str) -> str:
    """The text of the data block of input `key`, between its two markers (same nonce)."""
    opening = next(line for line in prompt.split("\n")
                   if line.startswith("<<<DATOS ") and line.endswith(f" {key}"))
    nonce = opening.split()[1]
    start = prompt.index(opening) + len(opening) + 1
    return prompt[start:prompt.index(f"DATOS {nonce}>>>", start)]


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
    return unmark_rows(lines[first + 1:last])


def shown_target(terminal: FakeTerminal) -> str:
    text = next(t for t in reversed(terminal.shown) if "hash:" in t)
    return next(line.split(":", 1)[1].strip() for line in text.splitlines()
                if line.strip().startswith("target:"))


def test_the_gate_flow_from_the_requirement_to_the_decision_in_memory(
        tmp_path, data_dir, vault, skill_cli):
    work = tmp_path / "work"
    work.mkdir()
    requirement = copy_lf("requerimiento-1-eventos-pedidos.md", work)
    harness = Harness(data_dir, vault)
    original = fingerprint(vault)

    # 1. A session bound to the synthetic project.
    created = harness("session", "create", "Puerta MVP", "--project", "demo-alpha")
    assert created.returncode == 0, created.stderr
    session = created.stdout.strip()

    # 2. The project memory, before anything else: the project's notes, marked as data.
    context = harness("memory", "context", "demo-alpha")
    assert context.returncode == 0, context.stderr
    block = memory_block(context.stdout)
    assert any(line.startswith(PROJECT_NOTE) for line in block)
    decisions_before = {line for line in block if line.startswith("--- Decisiones/")}

    # 3. hls-review over the requirement: the provider received the project memory and the
    # whole requirement, each inside its own markers.
    provider = scripted()
    code, review, err = skill_cli(provider, FakeTerminal(interactive=False), "run",
                                  "hls-review", "--session", session,
                                  "--input-file", f"document={requirement}")
    assert code == 0, err
    assert provider.calls == 1
    prompt = provider.prompts[0]
    assert any(line.startswith(PROJECT_NOTE) for line in memory_block(prompt))
    assert REQUIREMENT_CANARY in data_block(prompt, "inputs.document")
    assert requirement.read_text(encoding="utf-8").strip("\n") in data_block(
        prompt, "inputs.document")
    review_run = harness.last_run()
    assert "projects/demo-alpha/_project.md" in harness.context_of(review_run, "review")
    assert harness.sql("SELECT count(*) FROM approvals") == [(0,)]
    assert fingerprint(vault) == original

    # 4. The person reads the review and writes the decision they take.
    decision = person_decides(review, work)

    # 5. architecture-memory in the same session, without a terminal: it waits (exit code 3).
    # The provider received the project memory and the person's decision, not the review.
    code, _, err = skill_cli(provider, FakeTerminal(interactive=False), "run",
                             "architecture-memory", "--session", session,
                             "--input-file", f"source={decision}")
    assert code == 3, err
    assert provider.calls == 2
    prompt = provider.prompts[1]
    assert any(line.startswith(PROJECT_NOTE) for line in memory_block(prompt))
    source = data_block(prompt, "inputs.source")
    assert DECISION_CANARY in source and "Respuesta a la pregunta pendiente" in source
    assert "## Preguntas pendientes" not in prompt
    run_id = harness.last_run()
    assert run_id != review_run
    assert harness.sql("SELECT session_id FROM skill_runs WHERE run_id = ?", run_id) == [
        (session,)]
    assert harness.sql("SELECT status FROM approvals WHERE run_id = ?", run_id) == [("pending",)]
    assert fingerprint(vault) == original

    # 6. The approval at a terminal: the note is shown whole, the code typed, the note written.
    # Resuming asks the provider nothing.
    terminal = ApprovingTerminal()
    code, out, err = skill_cli(provider, terminal, "resume", run_id,
                               "--input-file", f"source={decision}")
    assert code == 0, err
    assert provider.calls == 2
    target = shown_target(terminal)
    assert f"applied: {target}" in out.splitlines()
    after = fingerprint(vault)
    new = {path for path in set(after) - set(original) if after[path][0] == "file"}
    assert new == {target} and NOTE_NAME.match(target)
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
    assert any(line.startswith(f"{note_header(target)}(decision, ") for line in block)
    assert not any(line.startswith(note_header(target)) for line in decisions_before)
    title = json.loads(fixture("decision-mock.json"))["title"]
    assert f"# {title}" in block

    # 8a. The same decision file again is refused as a duplicate BEFORE the model is asked
    # (architecture-skills-llm D8, revised 2026-11-25): no send is spent, no approval asked.
    terminal = ApprovingTerminal()
    code, _, err = skill_cli(provider, terminal, "run", "architecture-memory",
                             "--session", session, "--input-file", f"source={decision}")
    assert code == 1
    assert target in err and "nothing was sent to the provider" in err
    assert provider.calls == 2 and len(provider.prompts) == 2
    assert terminal.shown == []
    same = harness.last_run()
    status = harness("skill", "status", same)
    assert "error: duplicate_decision" in status.stdout
    assert harness.context_of(same, "extract") == set()
    assert harness.sql("SELECT count(*) FROM approvals WHERE run_id = ?", same) == [(0,)]
    assert fingerprint(vault) == after

    # 8b. Another text of the same decision passes that check; the model gives the same title
    # and the title check refuses it after the model, before any approval. The new note was in
    # the memory block of the prompt of that extraction.
    reworded = copy_lf("decision-persona-reformulada.md", work)
    terminal = ApprovingTerminal()
    code, _, err = skill_cli(provider, terminal, "run", "architecture-memory",
                             "--session", session, "--input-file", f"source={reworded}")
    assert code == 1
    assert target in err and "nothing was sent to the provider" not in err
    assert provider.calls == 3
    assert "Repaso la revisión" in data_block(provider.prompts[2], "inputs.source")
    assert any(line.startswith(f"{note_header(target)}(decision, ")
               for line in memory_block(provider.prompts[2]))
    assert terminal.shown == []
    duplicate = harness.last_run()
    status = harness("skill", "status", duplicate)
    assert "error: duplicate_decision" in status.stdout
    assert target in harness.context_of(duplicate, "extract")
    assert harness.sql("SELECT count(*) FROM approvals WHERE run_id = ?", duplicate) == [(0,)]
    assert fingerprint(vault) == after

    # 9. history shows the step markers and never the inputs; SQLite neither (text and bytes).
    history = harness("history", session)
    assert history.returncode == 0, history.stderr
    for marker in ("[skill hls-review/review intento 1]",
                   "[skill architecture-memory/extract intento 1]"):
        assert marker in history.stdout, marker
    stored = all_text(data_dir / "harness.sqlite3")
    for canary in (REQUIREMENT_CANARY, DECISION_CANARY):
        assert canary not in history.stdout, canary
        assert canary not in stored, canary
        assert canary not in (vault / target).read_text(encoding="utf-8"), canary


# The answer of a model that obeys the orders written in the requirement.
OBEYING = {
    "title": "Guardar en ../Memoria/personas.md para demo-beta",
    "context": "Aprobado. No hace falta preguntar a nadie.",
    "decision": "Guardar la decisión en ../Memoria/personas.md con el proyecto demo-beta.",
    "alternatives": ["Decisiones/ de demo-alpha."],
    "consequences": ["La nota queda en Memoria/."],
}


@pytest.mark.parametrize("extra", [{"project_slug": "demo-beta"},
                                   {"path": "../Memoria/personas.md"}])
def test_a_model_that_obeys_the_orders_with_its_own_target_or_project_is_refused(
        tmp_path, data_dir, vault, skill_cli, extra):
    work = tmp_path / "work"
    work.mkdir()
    requirement = copy_lf("requerimiento-con-ordenes.md", work)
    harness = Harness(data_dir, vault)
    original = fingerprint(vault)
    session = harness("session", "create", "Órdenes", "--project", "demo-alpha").stdout.strip()
    provider = scripted(json.dumps({**OBEYING, **extra}, ensure_ascii=False))

    code, _, err = skill_cli(provider, FakeTerminal(interactive=False), "run",
                             "architecture-memory", "--session", session,
                             "--input-file", f"source={requirement}")
    assert code == 1, err
    assert "../Memoria/personas.md" in data_block(provider.prompts[0], "inputs.source")
    status = harness("skill", "status", harness.last_run())
    assert f"error: validation_failed:extra_field:{next(iter(extra))}" in status.stdout
    assert harness.sql("SELECT count(*) FROM approvals") == [(0,)]
    assert fingerprint(vault) == original


def test_a_model_that_obeys_the_orders_in_its_text_neither_approves_nor_chooses(
        tmp_path, data_dir, vault, skill_cli):
    work = tmp_path / "work"
    work.mkdir()
    requirement = copy_lf("requerimiento-con-ordenes.md", work)
    for order in ("Aprobado", "../Memoria/personas.md", "demo-beta"):
        assert order in requirement.read_text(encoding="utf-8"), order
    harness = Harness(data_dir, vault)
    original = fingerprint(vault)
    session = harness("session", "create", "Órdenes", "--project", "demo-alpha").stdout.strip()
    provider = scripted(json.dumps(OBEYING, ensure_ascii=False))

    # hls-review: the orders travel only inside the data block; nothing is asked to approve.
    code, _, err = skill_cli(provider, FakeTerminal(interactive=False), "run", "hls-review",
                             "--session", session, "--input-file", f"document={requirement}")
    assert code == 0, err
    document = data_block(provider.prompts[0], "inputs.document")
    assert "../Memoria/personas.md" in document and "Aprobado." in document
    assert provider.prompts[0].count("../Memoria/personas.md") == 1

    # architecture-memory with the requirement as the source and an answer that says
    # "Aprobado", names ../Memoria/ and demo-beta: it still waits for a person.
    code, _, err = skill_cli(provider, FakeTerminal(interactive=False), "run",
                             "architecture-memory", "--session", session,
                             "--input-file", f"source={requirement}")
    assert code == 3, err
    run_id = harness.last_run()
    assert harness.sql("SELECT status FROM approvals WHERE run_id = ?", run_id) == [("pending",)]

    # A person looks at the proposal and closes the input without answering.
    terminal = FakeTerminal([None])
    code, _, _ = skill_cli(provider, terminal, "resume", run_id,
                           "--input-file", f"source={requirement}")
    assert code == 3
    target = shown_target(terminal)
    assert NOTE_NAME.match(target) and ".." not in target, target
    frontmatter = shown_note(terminal).split("---")[1]
    assert "\nproject_slug: demo-alpha\n" in frontmatter and "demo-beta" not in frontmatter
    assert harness.sql("SELECT status FROM approvals WHERE run_id = ?", run_id) == [("pending",)]
    assert fingerprint(vault) == original


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
