"""A data directory is bound to one profile and one vault (D2)."""

from tests.conftest import query


def _binding(data_dir):
    return query(data_dir, "SELECT profile, vault_root FROM memory_binding")


def test_first_use_binds_the_data_dir(cli, vault, data_dir):
    code, _, err = cli("memory", "search", "orquestador", HARNESS_VAULT_ROOT=str(vault))
    assert code == 0, err
    assert _binding(data_dir) == [("work", str(vault.resolve()))]


def test_profile_change_rejected(cli, vault, data_dir):
    assert cli("memory", "search", "arquitectura", HARNESS_VAULT_ROOT=str(vault))[0] == 0
    before = _binding(data_dir)

    env = {"HARNESS_VAULT_ROOT": str(vault), "HARNESS_PROFILE": "personal"}
    code, out, err = cli("memory", "search", "arquitectura", **env)
    assert code != 0 and out == ""
    assert "bound to the 'work' profile" in err and "HARNESS_DATA_DIR" in err
    assert "Traceback" not in err
    assert _binding(data_dir) == before


def test_vault_change_rejected(cli, vault, tmp_path, data_dir):
    other = tmp_path / "vault-b"
    other.mkdir()
    (other / "projects" / "demo-alpha").mkdir(parents=True)
    (other / "projects" / "demo-alpha" / "_project.md").write_text("CANARIO-VAULT-B-1203\n")
    assert cli("memory", "search", "arquitectura", HARNESS_VAULT_ROOT=str(vault))[0] == 0
    before = _binding(data_dir)

    code, out, err = cli("memory", "context", "demo-alpha", HARNESS_VAULT_ROOT=str(other))
    assert code != 0 and out == ""
    assert "bound to another vault root" in err
    assert "CANARIO-VAULT-B-1203" not in out + err
    assert _binding(data_dir) == before


def test_same_profile_and_vault_accepted(cli, vault, data_dir):
    env = {"HARNESS_VAULT_ROOT": str(vault), "HARNESS_PROFILE": "work"}
    first = cli("memory", "search", "orquestador ventas", **env)
    second = cli("memory", "search", "orquestador ventas", **env)
    assert first[0] == second[0] == 0
    assert first[1] == second[1] != ""
    assert _binding(data_dir) == [("work", str(vault.resolve()))]
