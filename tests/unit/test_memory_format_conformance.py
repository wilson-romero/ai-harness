"""The reader against the real format of `claude-memory-system` (memory-format-conformance).

The facts come from the public repository at commit 92b19ea (docs/convenciones.md,
scripts/memoria-capture.sh, scripts/memoria-dream.sh), described here in our own words; no
text of that repository is copied into this one.
"""

import re

import pytest

from harness.memory.context import build_context
from harness.memory.notes import frontmatter_problem, load_note, parse_frontmatter
from harness.memory.paths import walk_vault
from tests.conftest import VAULT_FIXTURE, header_paths, write_note
from tests.unit.test_memory_maintenance import _counts, _entries

# The `type` values of the convention, plus `decision`, which is the harness's own (study of
# 2026-11-28, mismatch 9; its format is an open decision of the owner).
REAL_TYPES = {"feedback", "project", "reference", "lesson", "session", "daily", "curated", "user"}
HARNESS_TYPES = {"decision"}
DATE_HEADING = re.compile(r"^## \d{4}-\d{2}-\d{2}$", re.MULTILINE)


def _fixture_notes():
    return {f.relative: load_note(f) for f in walk_vault(VAULT_FIXTURE.resolve()).files}


@pytest.fixture
def maintain(cli, vault):
    def run():
        return cli("memory", "maintain", "--dry-run", HARNESS_VAULT_ROOT=str(vault))

    return run


# -- the fixture has the real layout (task 1.x) -------------------------------------------------


def test_fixture_uses_only_real_note_types():
    notes = _fixture_notes()
    types = {
        relative: note.frontmatter.fields.get("type")
        for relative, note in notes.items()
        if note.frontmatter.present
    }
    assert set(types.values()) <= REAL_TYPES | HARNESS_TYPES, types
    assert {r for r, t in types.items() if t == "decision"} <= {
        r for r in types if r.startswith("Decisiones/")
    }
    assert types["_index.md"] == "reference"
    assert all(t == "lesson" for r, t in types.items()
               if r.startswith("Lecciones/") and not r.endswith("_INDEX.md"))
    assert all(types[r] == "curated" for r in types
               if r.startswith("Memoria/") and r.count("/") == 1)


def test_fixture_has_the_real_layout():
    notes = _fixture_notes()
    for relative in [
        "Memoria/contexto-reciente.md", "Memoria/proyectos-activos.md", "Memoria/personas.md",
        "Memoria/preferencias.md", "Memoria/perfil.md", "Memoria/Suenos/2026-11-21.md",
        "Memoria-CC/MEMORY.md", "Memoria-CC/MEMORY-tecnico.md", "Lecciones/_INDEX.md",
        "Decisiones/_INDEX.md", "agents/_skills-index.md", "agents/skills/revisor.md",
        "_index.md", "daily/2026-11-21.md",
    ]:
        assert relative in notes, relative
    assert not any(r.startswith("agents/") and r.count("/") == 1 and r != "agents/_skills-index.md"
                   for r in notes)
    agent = notes["agents/skills/revisor.md"].frontmatter.fields
    assert agent["type"] == "reference" and agent["agent_type"] == "revisor"
    assert len(DATE_HEADING.findall(notes["Memoria/contexto-reciente.md"].body)) == 2
    for index in ("Memoria-CC/MEMORY.md", "Memoria-CC/MEMORY-tecnico.md"):
        assert not notes[index].frontmatter.present  # the real indexes have none


def test_fixture_capture_notes_have_the_real_fields_and_sections():
    notes = _fixture_notes()
    for slug in ("demo-alpha", "demo-beta"):
        project = notes[f"projects/{slug}/_project.md"]
        fields = project.frontmatter.fields
        assert "created" not in fields  # the capture rewrites it without one
        assert fields["project"] == f"Code/{slug}" and fields["project_slug"] == slug
        assert fields["tags"] == ("claude-code", "proyecto")
        for section in ("## Memoria de Claude Code", "## Historial de sesiones"):
            assert section in project.body
    sessions = [n for r, n in notes.items() if "/sessions/" in r]
    assert len(sessions) == 5
    for session in sessions:
        fields = session.frontmatter.fields
        assert fields["tags"] == ("claude-code", fields["project_slug"])
        assert re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", fields["session_id"])
        for section in ("## Objetivo de la sesión", "## Archivos tocados", "## Estado git",
                        "## Metadatos"):
            assert section in session.body


# -- D1: notes the capture rewrites without `created` --------------------------------------------


@pytest.mark.parametrize("relative", [
    "projects/demo-alpha/_project.md", "_index.md", "agents/_skills-index.md",
])
def test_capture_notes_may_leave_created_out(relative):
    fm, _ = parse_frontmatter("---\ntype: project\nupdated: 2026-11-21\n---\n")
    assert frontmatter_problem(fm, relative) is None


@pytest.mark.parametrize("relative", [
    "Lecciones/2026-11-10-x.md", "projects/demo-alpha/sessions/2026-11-21-121500.md",
    "projects/demo-alpha/otra/_project.md", "Memoria-CC/_index.md", None,
])
def test_every_other_note_still_needs_created(relative):
    # Negative control: the exemption is by exact path, not by file name.
    fm, _ = parse_frontmatter("---\ntype: lesson\nupdated: 2026-11-21\n---\n")
    assert frontmatter_problem(fm, relative) == "created is not YYYY-MM-DD"


def test_a_created_that_is_there_is_still_checked():
    fm, _ = parse_frontmatter("---\ntype: project\ncreated: ayer\nupdated: 2026-11-21\n---\n")
    assert frontmatter_problem(fm, "projects/demo-alpha/_project.md") == (
        "created is not YYYY-MM-DD")
    fm, _ = parse_frontmatter("---\ntype: project\n---\n")
    assert frontmatter_problem(fm, "projects/demo-alpha/_project.md") == (
        "updated is not YYYY-MM-DD")


def test_real_capture_notes_are_not_reported(maintain):
    # The fixture's `_project.md`, `_index.md` and `_skills-index.md` have no `created`.
    code, out, err = maintain()
    assert code == 0, err
    assert _entries(out, "invalid_frontmatter") == []


# -- D2: a plain scalar with `: ` is not valid YAML ----------------------------------------------


@pytest.mark.parametrize("line", [
    "description: Estilo: breve", "description: termina en dos puntos:",
    "title: a: b: c",
])
def test_unquoted_colon_space_breaks_the_frontmatter(line):
    fm, _ = parse_frontmatter(f"---\ntype: feedback\n{line}\n---\ncuerpo\n")
    assert fm.present and not fm.syntax_ok


@pytest.mark.parametrize(("line", "value"), [
    ('description: "Estilo: breve"', "Estilo: breve"),
    ("description: 'Estilo: breve'", "Estilo: breve"),
    ("source: https://example.com/a", "https://example.com/a"),
    ("hora: 12:15:00", "12:15:00"),
])
def test_quoted_or_without_space_it_is_fine(line, value):
    fm, _ = parse_frontmatter(f"---\ntype: feedback\n{line}\n---\n")
    assert fm.syntax_ok and value in fm.fields.values()


def test_maintain_reports_the_broken_description(maintain, vault):
    note = vault / "Memoria-CC/feedback_rota.md"
    note.write_text("---\ntype: feedback\ncreated: 2026-11-01\nupdated: 2026-11-01\n"
                    "description: Estilo: breve\n---\nCuerpo.\n", encoding="utf-8")
    code, out, _ = maintain()
    assert code == 0
    assert _entries(out, "invalid_frontmatter") == ["Memoria-CC/feedback_rota.md (unsupported)"]


# -- D3: a project folder the identifier rule refuses ------------------------------------------


def test_real_slug_with_a_space_is_refused_with_its_reason(cli, vault):
    name = "srv-equipo-Mis Proyectos-demo"
    write_note(vault, f"projects/{name}/_project.md", "CANARIO-SLUG-ESPACIO-7702",
               type="project")
    code, out, err = cli("memory", "context", name, HARNESS_VAULT_ROOT=str(vault))
    assert code == 1 and out == ""
    assert f"invalid project identifier {name!r}: it contains a space;" in err
    assert "CANARIO-SLUG-ESPACIO-7702" not in out + err
    # Not ignored: without a project filter the folder's notes are read like any other.
    code, out, err = cli("memory", "search", "CANARIO-SLUG-ESPACIO-7702",
                         HARNESS_VAULT_ROOT=str(vault))
    assert code == 0 and f"projects/{name}/_project.md" in out


# -- D4, D5: the index audit -------------------------------------------------------------------


def test_index_entries_are_paths_relative_to_memoria_cc(maintain, vault):
    index = vault / "Memoria-CC/MEMORY-tecnico.md"
    index.write_text(
        index.read_text(encoding="utf-8")
        + "- [Falta](../Lecciones/2026-11-30-no-existe.md) — lección que no está\n"
        + "- [Fuera](../../fuera-del-vault.md) — sale del vault\n"
        + "- [Rama](./MEMORY.md) — otra rama del índice\n",
        encoding="utf-8",
    )
    code, out, _ = maintain()
    assert code == 0
    # The fixture's own `../Lecciones/...` entries and the branch pointer are not dangling.
    assert _entries(out, "index_dangling") == [
        "Memoria-CC/MEMORY-tecnico.md -> ../fuera-del-vault.md",
        "Memoria-CC/MEMORY-tecnico.md -> Lecciones/2026-11-30-no-existe.md",
    ]


def test_orphans_and_duplicates_only_look_at_the_first_level(maintain, vault):
    write_note(vault, "Memoria-CC/antiguas/feedback_estilo.md", "Copia en una subcarpeta.")
    write_note(vault, "Memoria-CC/reference_suelta.md", "Sin entrada en el índice.")
    code, out, _ = maintain()
    assert code == 0
    assert _entries(out, "index_orphans") == ["Memoria-CC/reference_suelta.md"]
    assert _entries(out, "duplicate_candidates") == []


# -- D6: wiki links inside a Markdown table ----------------------------------------------------


def test_table_escaped_alias_is_not_a_broken_link(maintain, vault):
    write_note(vault, "Lecciones/2026-11-17-tabla.md",
               "| a | b |\n|---|---|\n| [[agents/skills/revisor\\|revisor]] | "
               "[[agents/skills/no-existe\\|otro]] |")
    code, out, _ = maintain()
    assert code == 0
    # The fixture's `_skills-index.md` link and the first one resolve; the second is broken.
    assert _entries(out, "broken_links") == [
        "Lecciones/2026-11-17-tabla.md -> (no unique candidate)"
    ]


def test_the_real_format_fixture_is_a_clean_vault(maintain):
    code, out, err = maintain()
    assert code == 0, err
    assert set(_counts(out).values()) == {0}


# -- mismatch 8, as it is today (an open decision of the owner) --------------------------------


def test_curated_note_without_project_stays_out_of_the_context_today(vault):
    # The curator of claude-memory-system writes `tags: []`. Which global notes enter the
    # context is the owner's decision 2 of the study of 2026-11-28; this test only records
    # today's behaviour, so that a change to it is deliberate.
    note = (vault / "Lecciones/2026-11-16-plazos-de-prueba.md").read_text(encoding="utf-8")
    assert "tags: []" in note
    context = build_context(vault.resolve(), "demo-alpha", 65536)
    assert "Lecciones/2026-11-16-plazos-de-prueba.md" not in header_paths(context.text)
    assert "CANARIO-LECCION-SIN-PROYECTO-5150" not in context.text
