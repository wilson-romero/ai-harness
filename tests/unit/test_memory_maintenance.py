"""`memory maintain --dry-run`: a deterministic report that changes nothing (D10)."""

import shutil

import pytest

from harness.memory.maintenance import CATEGORIES, MAX_LISTED
from tests.conftest import SECRET_SAMPLES, fingerprint, make_symlink, run_main, write_note

CONFLICT = "Decisiones/alpha-mensajeria.sync-conflict-20261120-101010-ABCDEFG.md"


def _counts(out):
    counts = {}
    for line in out.splitlines():
        if not line.startswith((" ", "note:")):
            name, _, value = line.partition(": ")
            counts[name] = int(value)
    return counts


def _entries(out, category):
    lines = out.splitlines()
    start = lines.index(next(line for line in lines if line.startswith(f"{category}: ")))
    entries = []
    for line in lines[start + 1 :]:
        if not line.startswith("  "):
            break
        entries.append(line.strip())
    return entries


def plant_defects(vault, tmp_path):
    """One defect of each category in a copy of the synthetic vault."""
    shutil.copyfile(vault / "Decisiones/alpha-mensajeria.md", vault / CONFLICT)
    write_note(vault, "Lecciones/2026-11-14-enlaces.md", "Ver [[alpha-mensajeri]] antes.")
    index = vault / "Memoria-CC/MEMORY.md"
    index.write_text(
        index.read_text(encoding="utf-8")
        + "- [Estilos](feedback_estilos.md) — copia casi igual\n"
        + "- [Usuario](user_inexistente.md) — entrada sin nota\n",
        encoding="utf-8",
    )
    write_note(vault, "Memoria-CC/feedback_estilos.md", "Casi la misma nota de estilo.")
    write_note(vault, "Memoria-CC/reference_glosario.md", "Glosario fuera del índice.")
    (vault / "Lecciones/sin-frontmatter.md").write_text("Nota sin bloque inicial.\n")
    write_note(vault, "Decisiones/credencial.md", "despliegue con " + SECRET_SAMPLES["github"])
    outside = tmp_path / "fuera.md"
    outside.write_text("CANARIO-FUERA-MANT-3301\n")
    make_symlink(vault / "Decisiones/fuera.md", outside)


@pytest.fixture
def maintain(cli, vault):
    def run(*extra):
        return cli("memory", "maintain", "--dry-run", *extra, HARNESS_VAULT_ROOT=str(vault))

    return run


def test_without_dry_run(cli, vault):
    code, out, err = cli("memory", "maintain", HARNESS_VAULT_ROOT=str(vault))
    assert code == 2 and out == ""  # a usage error, as the README's table says
    assert "only exists as --dry-run" in err


def test_clean_vault(maintain):
    code, out, err = maintain()
    assert code == 0, err
    assert _counts(out) == dict.fromkeys(CATEGORIES, 0)
    assert list(_counts(out)) == list(CATEGORIES)
    assert "nothing in the vault was changed" in err


def test_planted_defects(maintain, vault, tmp_path):
    plant_defects(vault, tmp_path)
    code, out, err = maintain()
    assert code == 0, err
    assert _counts(out) == dict.fromkeys(CATEGORIES, 1)
    assert _entries(out, "sync_conflicts") == [CONFLICT]
    assert _entries(out, "broken_links") == [
        "Lecciones/2026-11-14-enlaces.md -> Decisiones/alpha-mensajeria.md"
    ]
    assert _entries(out, "index_dangling") == [
        "Memoria-CC/MEMORY.md -> Memoria-CC/user_inexistente.md"
    ]
    assert _entries(out, "index_orphans") == ["Memoria-CC/reference_glosario.md"]
    assert _entries(out, "duplicate_candidates") == [
        "Memoria-CC/feedback_estilo.md ~ Memoria-CC/feedback_estilos.md"
    ]
    assert _entries(out, "invalid_frontmatter") == ["Lecciones/sin-frontmatter.md (missing)"]
    assert _entries(out, "secrets_found") == ["Decisiones/credencial.md: github (1)"]
    assert _entries(out, "skipped") == ["Decisiones/fuera.md (link)"]
    assert "CANARIO-FUERA-MANT-3301" not in out


def test_credential_detected_without_showing_it(maintain, vault):
    token = SECRET_SAMPLES["aws"]
    write_note(vault, "Decisiones/acceso.md", f"clave {token} temporal")
    code, out, err = maintain()
    assert code == 0
    assert "Decisiones/acceso.md: aws (1)" in out
    assert token not in out + err
    assert "only covers known credential formats" in out


def test_report_shows_no_body_text(maintain, vault, tmp_path):
    plant_defects(vault, tmp_path)
    _, out, _ = maintain()
    for body_text in ["Ver [[", "alpha-mensajeri]]", "Glosario fuera", "despliegue con"]:
        assert body_text not in out


def test_two_identical_runs(vault, data_dir, tmp_path):
    plant_defects(vault, tmp_path)
    env = {"HARNESS_VAULT_ROOT": str(vault)}
    first = run_main(data_dir, "memory", "maintain", "--dry-run", **env)
    second = run_main(data_dir, "memory", "maintain", "--dry-run", **env)
    assert first.returncode == second.returncode == 0, first.stderr
    assert first.stdout.encode() == second.stdout.encode()
    assert first.stderr.encode() == second.stderr.encode()


def test_vault_untouched(maintain, vault, tmp_path):
    plant_defects(vault, tmp_path)
    before = fingerprint(vault)
    assert maintain()[0] == 0
    assert fingerprint(vault) == before


def test_rclone_conflict_name_and_link_forms(maintain, vault):
    (vault / "Decisiones/alpha-mensajeria.md..path1").write_text("copia\n")
    write_note(
        vault,
        "Lecciones/2026-11-15-formas.md",
        "[[alpha-mensajeria|alias]] [[Decisiones/alpha-mensajeria#Contexto]] [[#local]] "
        "[[nota-que-no-se-parece-a-nada]]",
    )
    # Links inside projects/ and daily/ are written by the capture and not checked.
    write_note(vault, "projects/demo-alpha/sessions/2026-11-22-080000.md", "[[rota-de-sesion]]")
    _, out, _ = maintain()
    assert _entries(out, "sync_conflicts") == ["Decisiones/alpha-mensajeria.md..path1"]
    assert _entries(out, "broken_links") == [
        "Lecciones/2026-11-15-formas.md -> (no unique candidate)"
    ]


def test_long_categories_are_cut_at_fifty_entries(maintain, vault):
    for i in range(MAX_LISTED + 5):
        (vault / f"Lecciones/sin-bloque-{i:02d}.md").write_text("x\n")
    _, out, _ = maintain()
    assert _counts(out)["invalid_frontmatter"] == MAX_LISTED + 5
    entries = _entries(out, "invalid_frontmatter")
    assert len(entries) == MAX_LISTED + 1 and entries[-1] == "... and 5 more"
