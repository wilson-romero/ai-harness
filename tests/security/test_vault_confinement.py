"""SEC-04: reading never leaves the vault's real root, and excluded entries are not read (D4)."""

import os
import sys
from pathlib import Path

import pytest

from harness.memory.config import load_memory_settings
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


# Every file or directory the process opens or lists while a command runs, through the
# interpreter's audit events: an oracle that does not depend on how the harness reads.
_ACCESSED: list[str] | None = None


def _audit(event, args):
    if _ACCESSED is not None and event in ("open", "os.listdir", "os.scandir") and args:
        target = args[0]
        if isinstance(target, (str, bytes, os.PathLike)):
            _ACCESSED.append(os.fsdecode(target))


sys.addaudithook(_audit)


@pytest.fixture
def accessed():
    global _ACCESSED
    _ACCESSED = []
    yield _ACCESSED
    _ACCESSED = None


def _under(paths, folder):
    folders = {str(folder), str(Path(folder).resolve())}
    return [p for p in paths if any(p == f or p.startswith(f + os.sep) for f in folders)]


def test_symlinked_directory_to_outside_ignored(cli, vault, outside, data_dir, recorder, accessed):
    # A curated folder linked to the outside, holding a note that declares the project and
    # has no frontmatter problem: without the confinement every command would use it.
    write_note(outside, "decision-de-fuera.md", f"orquestador {OUTSIDE_CANARY}",
               project_slug="demo-alpha")
    make_symlink(vault / "Decisiones" / "externas", outside)
    env = _env(vault)
    accessed.clear()  # what the test itself wrote does not count

    code, out, err = cli("memory", "search", OUTSIDE_CANARY, **env)
    assert code == 0 and out.strip() == "No results."
    assert f"{SKIP_LINK}: 1" in err
    walked = walk_vault(vault.resolve())
    assert all(not f.relative.startswith("Decisiones/externas") for f in walked.files)
    assert ("Decisiones/externas", SKIP_LINK) in walked.skipped

    code, out, err = cli("memory", "context", "demo-alpha", **env)
    assert code == 0 and OUTSIDE_CANARY not in out and "Decisiones/externas" not in out

    code, out, _ = cli("memory", "maintain", "--dry-run", **env)
    assert code == 0 and OUTSIDE_CANARY not in out
    assert [line.strip() for line in out.splitlines() if "externas" in line] == [
        "Decisiones/externas (link)"
    ]

    session_id = cli("session", "create", "S", "--project", "demo-alpha")[1].strip()
    code, _, err = cli("ask", session_id, "pregunta", "--project", "demo-alpha", **env)
    assert code == 0, err
    (sent,) = recorder.prompts
    assert OUTSIDE_CANARY not in sent
    stored = [row[0] for row in query(data_dir, "SELECT note_path FROM request_context")]
    assert not [p for p in stored if "externas" in p]
    # And nothing under the linked folder was even opened, by any of the four commands.
    assert _under(accessed, outside) == []


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
    # Reading is confined to the real directory the link points to.
    assert load_memory_settings({"HARNESS_VAULT_ROOT": str(link)}).vault_root == vault.resolve()


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


def test_traversal_in_project_rejected_by_the_cli(cli, vault, data_dir, tmp_path, accessed):
    # What `projects/../../etc` would reach from this vault, with a project inside it.
    target = Path(os.path.normpath(vault / "projects" / ".." / ".." / "etc"))
    assert target == tmp_path / "etc"
    write_note(target, "_project.md", "CANARIO-TRAVERSAL-5150")
    write_note(target, "sessions/2026-11-21-121500.md", "CANARIO-TRAVERSAL-5150")
    accessed.clear()  # what the test itself wrote does not count

    code, out, err = cli("memory", "context", "../../etc", HARNESS_VAULT_ROOT=str(vault))
    assert code != 0 and out == ""
    assert "invalid project identifier" in err
    assert "CANARIO-TRAVERSAL" not in out + err
    assert not (data_dir / "harness.sqlite3").exists()  # refused before anything was opened
    # Not one file or directory of the vault or of what lies beyond it was opened or listed.
    assert _under(accessed, tmp_path) == []

    session_id = cli("session", "create", "S", "--project", "demo-alpha")[1].strip()
    accessed.clear()
    code, out, err = cli("ask", session_id, "pregunta", "--project", "../../etc",
                         HARNESS_VAULT_ROOT=str(vault))
    assert code != 0 and "invalid project identifier" in err
    assert "CANARIO-TRAVERSAL" not in out + err
    assert _under(accessed, vault) == [] and _under(accessed, target) == []


@pytest.mark.parametrize("raw", ["..\\otro", "C:\\vault", "\\\\servidor\\recurso", "CON"])
def test_windows_path_forms_rejected_by_the_cli(cli, vault, raw):
    code, out, err = cli("memory", "context", raw, HARNESS_VAULT_ROOT=str(vault))
    assert code != 0 and out == ""
    assert f"invalid project identifier {raw!r}" in err
