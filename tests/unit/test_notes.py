"""Reading notes and the minimal frontmatter parser (D10)."""

import pytest

from harness.memory.notes import (
    decode,
    frontmatter_problem,
    load_note,
    parse_frontmatter,
    project_section,
)
from harness.memory.paths import walk_vault
from tests.conftest import VAULT_FIXTURE


def test_inline_lists_form():
    text = (
        "---\ntype: decision\nproject_slug: demo-alpha\n"
        "tags: [demo-alpha, 'arquitectura']\n---\nCuerpo\n"
    )
    fm, body = parse_frontmatter(text)
    assert fm.present and fm.syntax_ok
    assert fm.fields == {
        "type": "decision",
        "project_slug": "demo-alpha",
        "tags": ("demo-alpha", "arquitectura"),
    }
    assert body == "Cuerpo\n"


def test_block_lists_form():
    text = "---\ntype: session\ntags:\n  - sesion\n  - demo-alpha\ncreated: 2026-11-18\n---\n# T\n"
    fm, body = parse_frontmatter(text)
    assert fm.syntax_ok
    assert fm.fields["tags"] == ("sesion", "demo-alpha")
    assert fm.fields["created"] == "2026-11-18"
    assert body == "# T\n"


def test_empty_inline_list():
    fm, _ = parse_frontmatter("---\ntype: x\ntags: []\n---\n")
    assert fm.syntax_ok and fm.fields["tags"] == ()


def test_crlf_and_bom_are_normalised():
    raw = "﻿---\r\ntype: leccion\r\ntags: [a]\r\n---\r\nLinea uno\r\nLinea dos\r\n".encode()
    text = decode(raw)
    assert text == "---\ntype: leccion\ntags: [a]\n---\nLinea uno\nLinea dos\n"
    fm, body = parse_frontmatter(text)
    assert fm.syntax_ok and fm.fields["type"] == "leccion" and body == "Linea uno\nLinea dos\n"


def test_invalid_utf8_is_replaced_not_raised():
    assert decode(b"caf\xe9 y m\xc3\xa1s") == "caf� y más"


def test_no_frontmatter():
    fm, body = parse_frontmatter("# Solo cuerpo\n\ntexto\n")
    assert not fm.present and not fm.syntax_ok and fm.fields == {}
    assert body == "# Solo cuerpo\n\ntexto\n"
    assert frontmatter_problem(fm) == "missing"


@pytest.mark.parametrize(
    "block",
    [
        "type: x\nmeta:\n  clave: valor",  # nested mapping
        "type: x\nancla: &a valor",  # anchor
        "type: x\nbloque: |\n  texto",  # block scalar
        "type: x\nflujo: {a: 1}",  # flow mapping
        "type: x\n# comentario",  # comment
        "type: x\ntype: y",  # duplicate key
        "- suelto",  # list item without a key
        "type: x\ntags: [a, b",  # unclosed inline list
        "solo texto",  # no colon
    ],
)
def test_unsupported_yaml_is_invalid_without_raising(block):
    fm, _ = parse_frontmatter(f"---\n{block}\n---\ncuerpo\n")
    assert fm.present and not fm.syntax_ok and fm.fields == {}
    assert frontmatter_problem(fm) == "unsupported"


def test_unclosed_block_is_invalid():
    fm, body = parse_frontmatter("---\ntype: x\ncuerpo sin cierre\n")
    assert fm.present and not fm.syntax_ok
    assert body == "---\ntype: x\ncuerpo sin cierre\n"


@pytest.mark.parametrize(
    ("block", "problem"),
    [
        ("created: 2026-11-01\nupdated: 2026-11-01", "missing type"),
        ("type: x\ncreated: 2026-11-01", "updated is not YYYY-MM-DD"),
        ("type: x\ncreated: 2026-13-01\nupdated: 2026-11-01", "created is not YYYY-MM-DD"),
        ("type: x\ncreated: 2026-11-01\nupdated: 2026-11-01T10:00", "updated is not YYYY-MM-DD"),
        ("type: x\ncreated: 2026-11-01\nupdated: 2026-11-02", None),
    ],
)
def test_maintenance_validity(block, problem):
    fm, _ = parse_frontmatter(f"---\n{block}\n---\n")
    assert frontmatter_problem(fm) == problem


def test_every_fixture_note_is_valid_and_loads():
    walked = walk_vault(VAULT_FIXTURE.resolve())
    notes = [load_note(f) for f in walked.files]
    assert len(notes) >= 19
    problems = {
        n.relative: frontmatter_problem(n.frontmatter)
        for n in notes
        if n.relative != "Memoria-CC/MEMORY.md"  # an index, not a note
    }
    assert {k: v for k, v in problems.items() if v} == {}
    assert all(len(n.sha256) == 64 and n.size > 0 for n in notes)


def test_project_membership_rule():
    fm_alpha, _ = parse_frontmatter("---\nproject_slug: demo-alpha\n---\n")
    fm_tag, _ = parse_frontmatter("---\ntags: [demo-alpha]\n---\n")
    fm_beta, _ = parse_frontmatter("---\ntags: [demo-beta]\n---\n")
    fm_none, _ = parse_frontmatter("sin frontmatter")
    assert project_section("projects/demo-alpha/_project.md", fm_none, "demo-alpha") == "project"
    session = "projects/demo-alpha/sessions/2026-11-18-091500.md"
    assert project_section(session, fm_none, "demo-alpha") == "session"
    assert project_section("projects/demo-alpha/otra.md", fm_alpha, "demo-alpha") is None
    assert project_section("projects/demo-beta/_project.md", fm_alpha, "demo-alpha") is None
    assert project_section("Decisiones/a.md", fm_alpha, "demo-alpha") == "Decisiones"
    assert project_section("Lecciones/b.md", fm_tag, "demo-alpha") == "Lecciones"
    assert project_section("Memoria-CC/c.md", fm_beta, "demo-alpha") is None
    assert project_section("Memoria/personas.md", fm_alpha, "demo-alpha") is None
    assert project_section("daily/2026-11-21.md", fm_alpha, "demo-alpha") is None


@pytest.mark.parametrize(("block", "slug"), [
    ("project_slug: demo-alpha-2", "demo-alpha"),   # the slug is a prefix of the declared one
    ("project_slug: demo-alpha", "demo-alpha-2"),   # the declared one is a prefix of the slug
    ("project_slug: alpha", "demo-alpha"),          # a suffix
    ("tags: [decision, demo-alpha-2]", "demo-alpha"),
    ("tags: [decision, demo-alpha]", "demo-alpha-2"),
    ("tags: demo-alpha-2", "demo-alpha"),             # a scalar tag, not a list
    ("tags: [x-demo-alpha]", "demo-alpha"),
])
def test_a_project_named_inside_another_is_not_that_project(block, slug):
    """Independent review of hardening (2026-11-25), SEC-02: a note belongs to a project only
    by the exact slug, never by a substring or a prefix of it."""
    fm, _ = parse_frontmatter(f"---\ntype: decision\n{block}\n---\ncuerpo\n")
    assert project_section("Decisiones/a.md", fm, slug) is None


def test_the_exact_project_in_a_scalar_tag_still_counts():
    fm, _ = parse_frontmatter("---\ntype: decision\ntags: demo-alpha\n---\ncuerpo\n")
    assert project_section("Decisiones/a.md", fm, "demo-alpha") == "Decisiones"
