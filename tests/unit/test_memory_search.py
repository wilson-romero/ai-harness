"""`memory search`: a deterministic text scan with terminal-safe, redacted snippets (D5)."""

import pytest

from tests.conftest import PRIVATE_KEY_SAMPLE, SECRET_SAMPLES, run_main, write_note


def _rows(out):
    return [line.split("\t") for line in out.strip().splitlines()]


@pytest.fixture
def search(cli, vault):
    def run(*args, **env):
        return cli("memory", "search", *args, HARNESS_VAULT_ROOT=str(vault), **env)

    return run


def test_terms_found(search):
    code, out, err = search("Orquestador ventas")
    assert code == 0, err
    assert sorted(row[0] for row in _rows(out)) == [
        "Decisiones/alpha-mensajeria.md",
        "projects/demo-alpha/_project.md",
    ]
    for path, updated, matches, snippet in _rows(out):
        assert updated in {"2026-11-16", "2026-11-21"} and int(matches) >= 2
        assert "orquestador" in snippet.casefold() or "ventas" in snippet.casefold()


def test_result_order_matches_then_updated_then_path(search, vault):
    write_note(vault, "Decisiones/zz-latencia.md", "latencia " * 3, updated="2026-01-01")
    write_note(vault, "Decisiones/aa-latencia.md", "latencia", updated="2026-11-19")
    code, out, _ = search("latencia")
    assert code == 0
    assert [(r[0], r[1], r[2]) for r in _rows(out)] == [
        ("Decisiones/zz-latencia.md", "2026-01-01", "3"),  # most matches first
        ("projects/demo-alpha/_project.md", "2026-11-21", "1"),  # then newest `updated`
        ("projects/demo-beta/_project.md", "2026-11-20", "1"),  # then path
        ("projects/demo-beta/sessions/2026-11-20-090000.md", "2026-11-20", "1"),
        ("Decisiones/aa-latencia.md", "2026-11-19", "1"),
        ("projects/demo-alpha/sessions/2026-11-19-101500.md", "2026-11-19", "1"),
        ("Lecciones/2026-11-12-colas-beta.md", "2026-11-12", "1"),
    ]


def test_no_results(search):
    code, out, err = search("inexistente-xyz")
    assert (code, out.strip()) == (0, "No results.")
    assert "0 result(s)" in err


@pytest.mark.parametrize("query", ["", "   "])
def test_empty_query(cli, tmp_path, data_dir, query):
    # The vault does not exist: an empty query is refused before the vault is even looked at.
    code, out, err = cli(
        "memory", "search", query, HARNESS_VAULT_ROOT=str(tmp_path / "no-existe")
    )
    assert code != 0 and out == ""
    assert "query must not be empty" in err
    assert not data_dir.exists()


def test_query_limits(search):
    assert "at most 200 characters" in search("x" * 201)[2]
    assert "at most 10 terms" in search(" ".join(f"t{i}" for i in range(11)))[2]
    assert "--limit must be between 1 and 200" in search("x", "--limit", "0")[2]
    assert "--limit must be between 1 and 200" in search("x", "--limit", "201")[2]


def test_same_query_same_output(vault, data_dir):
    env = {"HARNESS_VAULT_ROOT": str(vault)}
    first = run_main(data_dir, "memory", "search", "nota sintética", **env)
    second = run_main(data_dir, "memory", "search", "nota sintética", **env)
    assert first.returncode == second.returncode == 0, first.stderr
    assert first.stdout.encode() == second.stdout.encode()
    assert first.stderr.encode() == second.stderr.encode()
    # 17 since memory-format-conformance (2026-11-28): the real `_index.md` is links only,
    # without the "Nota sintética" sentence the fixture's one had.
    assert len(first.stdout.splitlines()) == 17


def test_result_limit(search):
    code, out, err = search("sintética", "--limit", "3")
    assert code == 0
    assert len(_rows(out)) == 3
    assert "warning: 14 more result(s) omitted" in err  # 17 notes, as above


def test_other_project_excluded(search):
    code, out, err = search("latencia", "--project", "demo-alpha")
    assert code == 0, err
    paths = [row[0] for row in _rows(out)]
    assert paths == [
        "projects/demo-alpha/_project.md",
        "projects/demo-alpha/sessions/2026-11-19-101500.md",
    ]
    assert not any(p.startswith("projects/demo-beta/") for p in paths)
    assert "Lecciones/2026-11-12-colas-beta.md" not in paths  # tagged only demo-beta
    # Without the filter the other project's notes are there: the filter is what removes them.
    code, out, _ = search("latencia")
    everywhere = [row[0] for row in _rows(out)]
    assert "projects/demo-beta/_project.md" in everywhere
    assert "Lecciones/2026-11-12-colas-beta.md" in everywhere


def test_project_filter_includes_curated_notes(search):
    code, out, _ = search("sintética", "--project", "demo-alpha")
    assert code == 0
    paths = {row[0] for row in _rows(out)}
    assert {
        "Decisiones/alpha-mensajeria.md",
        "Lecciones/2026-11-10-reintentos-idempotentes.md",
        "Memoria-CC/project_alpha-integraciones.md",
    } <= paths
    assert not any(p.startswith(("Memoria/", "daily/", "agents/", "_index")) for p in paths)


def test_escape_sequence_neutralised(search, vault):
    write_note(vault, "Decisiones/escape.md", "alerta \x1b[31mroja\x1b[0m\tcon tab y ‮oculto")
    code, out, _ = search("alerta")
    assert code == 0
    (row,) = _rows(out)
    assert len(row) == 4  # the tab inside the note did not add a column
    assert "\x1b" not in out and "‮" not in out
    # Since the review of 2026-11-24 the whole sequence goes, not only its ESC byte.
    assert row[3].startswith("alerta roja con tab")


def test_credential_in_a_snippet(search, vault):
    token = SECRET_SAMPLES["aws"]
    write_note(vault, "Decisiones/acceso.md", f"acceso temporal {token} para pruebas")
    code, out, err = search("acceso temporal")
    assert code == 0
    assert "[REDACTED:aws]" in out and token not in out + err
    assert "1 credential(s) redacted" in err


def test_snippet_is_cut_at_160_characters(search, vault):
    write_note(vault, "Decisiones/larga.md", "marcador " + "palabra " * 60)
    _, out, _ = search("marcador")
    assert len(_rows(out)[0][3]) == 160


def test_token_in_a_search_snippet(cli, vault):
    write_note(vault, "Decisiones/credencial.md", "despliegue con " + SECRET_SAMPLES["github"])
    code, out, err = cli("memory", "search", "despliegue", HARNESS_VAULT_ROOT=str(vault))
    assert code == 0
    assert "[REDACTED:github]" in out and SECRET_SAMPLES["github"] not in out + err
    assert "1 credential(s) redacted" in err


def test_private_key_line_in_a_search_snippet(cli, vault):
    write_note(vault, "Decisiones/clave.md", PRIVATE_KEY_SAMPLE)
    code, out, err = cli("memory", "search", "K" * 10, HARNESS_VAULT_ROOT=str(vault))
    assert code == 0
    assert "[REDACTED:private-key]" in out and "K" * 10 not in out
