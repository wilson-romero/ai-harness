"""SEC-04: reading never leaves the vault's real root, and excluded entries are not read (D4)."""

import os

import pytest

from harness.memory.paths import SKIP_HARD_LINK, SKIP_LINK, walk_vault
from tests.conftest import make_symlink, query, write_note

OUTSIDE_CANARY = "CANARIO-FUERA-8842"


@pytest.fixture
def outside(tmp_path):
    folder = tmp_path / "fuera"
    folder.mkdir()
    write_note(folder, "secreto.md", f"Nota de fuera con orquestador. {OUTSIDE_CANARY}")
    return folder


def _env(vault):
    return {"HARNESS_VAULT_ROOT": str(vault)}


def test_symlink_to_outside_file_ignored(cli, vault, outside):
    make_symlink(vault / "projects" / "demo-alpha" / "enlace.md", outside / "secreto.md")
    code, out, err = cli("memory", "search", OUTSIDE_CANARY, **_env(vault))
    assert code == 0
    assert out.strip() == "No results."
    assert OUTSIDE_CANARY not in out + err
    assert f"{SKIP_LINK}: 1" in err


def test_symlinked_directory_to_outside_ignored(cli, vault, outside):
    make_symlink(vault / "Lecciones" / "externas", outside)
    code, out, err = cli("memory", "search", OUTSIDE_CANARY, **_env(vault))
    assert code == 0 and out.strip() == "No results."
    assert f"{SKIP_LINK}: 1" in err
    walked = walk_vault(vault.resolve())
    assert all(not f.relative.startswith("Lecciones/externas") for f in walked.files)
    assert ("Lecciones/externas", SKIP_LINK) in walked.skipped


def test_symlink_inside_the_vault_is_not_followed_either(vault):
    make_symlink(vault / "copia.md", vault / "projects" / "demo-alpha" / "_project.md")
    walked = walk_vault(vault.resolve())
    assert ("copia.md", SKIP_LINK) in walked.skipped
    assert "copia.md" not in {f.relative for f in walked.files}


def test_vault_root_that_is_a_link(cli, vault, tmp_path, data_dir):
    link = tmp_path / "vault-enlace"
    make_symlink(link, vault)
    code, out, err = cli("memory", "search", "orquestador ventas", HARNESS_VAULT_ROOT=str(link))
    assert code == 0, err
    assert "projects/demo-alpha/_project.md" in out
    assert query(data_dir, "SELECT vault_root FROM memory_binding") == [(str(vault.resolve()),)]


def test_hard_linked_file_is_skipped(vault, outside):
    try:
        os.link(outside / "secreto.md", vault / "Decisiones" / "duro.md")
    except OSError as exc:
        pytest.skip(f"cannot create hard links here: {exc}")
    walked = walk_vault(vault.resolve())
    assert ("Decisiones/duro.md", SKIP_HARD_LINK) in walked.skipped
    assert "Decisiones/duro.md" not in {f.relative for f in walked.files}


def test_atomic_write_temporary_ignored(cli, vault):
    (vault / "Decisiones" / ".tmp.AbC123").write_text("borrador CANARIO-TEMPORAL-3356\n")
    code, out, err = cli("memory", "search", "CANARIO-TEMPORAL-3356", **_env(vault))
    assert code == 0 and out.strip() == "No results."
    assert "hidden: 1" in err


def test_hidden_folders_ignored(cli, vault):
    write_note(vault, ".obsidian/plantilla.md", "CANARIO-OCULTO-2290")
    write_note(vault, ".trash/borrada.md", "CANARIO-OCULTO-2290")
    code, out, err = cli("memory", "search", "CANARIO-OCULTO-2290", **_env(vault))
    assert code == 0 and out.strip() == "No results."
    assert "hidden: 2" in err


def test_archive_excluded(cli, vault):
    code, out, err = cli("memory", "search", "CANARIO-ARCHIVO-5521", **_env(vault))
    assert code == 0 and out.strip() == "No results."
    assert "archive: 1" in err


def test_non_markdown_and_large_files_ignored(cli, vault):
    (vault / "Decisiones" / "anexo.txt").write_text("CANARIO-TXT-6612\n")
    big = vault / "Decisiones" / "enorme.md"
    big.write_text("CANARIO-GRANDE-6613\n" + "x" * (1024 * 1024))
    code, out, err = cli("memory", "search", "CANARIO", **_env(vault))
    assert code == 0
    assert "CANARIO-TXT-6612" not in out and "CANARIO-GRANDE-6613" not in out
    assert "not-markdown: 1" in err and "too-large: 1" in err


def test_project_with_different_case(cli, vault):
    code, out, err = cli("memory", "search", "latencia", "--project", "Demo-Alpha", **_env(vault))
    assert code != 0 and out == ""
    assert "project 'Demo-Alpha' does not exist" in err
    code, out, err = cli("memory", "context", "Demo-Alpha", **_env(vault))
    assert code != 0 and "project 'Demo-Alpha' does not exist" in err


def test_missing_project(cli, vault):
    code, out, err = cli("memory", "search", "latencia", "--project", "demo-gamma", **_env(vault))
    assert code != 0 and out == ""
    assert "project 'demo-gamma' does not exist" in err


def test_project_folder_that_is_a_link_does_not_count(cli, vault, tmp_path):
    target = tmp_path / "otro-proyecto"
    target.mkdir()
    make_symlink(vault / "projects" / "demo-enlace", target)
    code, _, err = cli("memory", "context", "demo-enlace", **_env(vault))
    assert code != 0 and "does not exist" in err


def test_traversal_in_project_rejected_by_the_cli(cli, vault, data_dir):
    code, out, err = cli("memory", "context", "../../etc", HARNESS_VAULT_ROOT=str(vault))
    assert code != 0 and out == ""
    assert "invalid project identifier" in err
    assert not (data_dir / "harness.sqlite3").exists()  # refused before anything was opened


@pytest.mark.parametrize("raw", ["..\\otro", "C:\\vault", "\\\\servidor\\recurso", "CON"])
def test_windows_path_forms_rejected_by_the_cli(cli, vault, raw):
    code, out, err = cli("memory", "context", raw, HARNESS_VAULT_ROOT=str(vault))
    assert code != 0 and out == ""
    assert f"invalid project identifier {raw!r}" in err
