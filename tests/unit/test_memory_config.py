"""Memory configuration is read and validated only by the commands that use it (D1)."""

import pytest

from harness.memory.config import CONTEXT_DEFAULT_BYTES, load_memory_settings
from tests.conftest import query, run_main


def test_memory_help_lists_the_three_subcommands(data_dir):
    result = run_main(data_dir, "memory", "--help")
    assert result.returncode == 0
    assert all(name in result.stdout for name in ("search", "context", "maintain"))


def test_ask_help_shows_project(data_dir):
    result = run_main(data_dir, "ask", "--help")
    assert result.returncode == 0 and "--project" in result.stdout


def test_vault_not_configured(cli):
    code, out, err = cli("memory", "search", "arquitectura", HARNESS_VAULT_ROOT="")
    assert code != 0 and out == ""
    assert "HARNESS_VAULT_ROOT is not set" in err and "Traceback" not in err


def test_relative_root_rejected(cli, vault, monkeypatch):
    monkeypatch.chdir(vault.parent)
    code, out, err = cli("memory", "context", "demo-alpha", HARNESS_VAULT_ROOT=vault.name)
    assert code != 0 and out == ""
    assert "must be an absolute path" in err


def test_missing_root_rejected(cli, tmp_path):
    code, out, err = cli("memory", "search", "x", HARNESS_VAULT_ROOT=str(tmp_path / "absent"))
    assert code != 0 and out == "" and "does not exist" in err


def test_default_profile_is_work(cli, vault, tmp_path, data_dir):
    code, _, err = cli("memory", "search", "orquestador", HARNESS_VAULT_ROOT=str(vault))
    assert code == 0, err
    assert query(data_dir, "SELECT profile FROM memory_binding") == [("work",)]
    # ...and the work rules apply: a vault in a sync folder is refused without a profile set.
    synced = tmp_path / "CloudStorage" / "vault"
    synced.parent.mkdir()
    vault.rename(synced)
    code, _, err = cli("memory", "search", "orquestador", HARNESS_VAULT_ROOT=str(synced))
    assert code != 0 and "'CloudStorage'" in err


def test_unknown_profile(cli, vault, data_dir):
    code, out, err = cli(
        "memory", "search", "orquestador", HARNESS_VAULT_ROOT=str(vault), HARNESS_PROFILE="casa"
    )
    assert code != 0 and out == ""
    assert "HARNESS_PROFILE must be one of work, personal" in err
    assert not (data_dir / "harness.sqlite3").exists()  # rejected before anything else


@pytest.mark.parametrize("value", ["1023", "65537", "0", "-5", "ocho mil"])
def test_context_limit_out_of_range(cli, vault, value):
    code, out, err = cli(
        "memory",
        "search",
        "orquestador",
        HARNESS_VAULT_ROOT=str(vault),
        HARNESS_MEMORY_CONTEXT_MAX_BYTES=value,
    )
    assert code != 0 and out == ""
    assert "HARNESS_MEMORY_CONTEXT_MAX_BYTES" in err


@pytest.mark.parametrize(
    ("value", "expected"), [("", CONTEXT_DEFAULT_BYTES), ("1024", 1024), ("65536", 65536)]
)
def test_context_limit_accepted(vault, data_dir, value, expected):
    env = {"HARNESS_VAULT_ROOT": str(vault), "HARNESS_MEMORY_CONTEXT_MAX_BYTES": value}
    settings = load_memory_settings(env, data_dir)
    assert settings.context_max_bytes == expected
    assert settings.profile == "work"
    assert settings.vault_root == vault.resolve()


def test_ask_without_project_does_not_read_the_vault(cli, tmp_path):
    env = {"HARNESS_VAULT_ROOT": str(tmp_path / "does-not-exist"), "HARNESS_PROFILE": "casa"}
    session_id = cli("session", "create", "Sin memoria", **env)[1].strip()
    code, out, err = cli("ask", session_id, "pregunta", **env)
    assert code == 0, err
    assert out.strip() != ""
    code, out, _ = cli("history", session_id, **env)
    assert code == 0 and "pregunta" in out


def test_ask_with_project_is_a_stub_in_this_build(cli, vault):
    session_id = cli("session", "create", "Con memoria", "--project", "demo-alpha")[1].strip()
    code, out, err = cli(
        "ask", session_id, "pregunta", "--project", "demo-alpha", HARNESS_VAULT_ROOT=str(vault)
    )
    assert code == 1 and out == ""
    assert "not implemented in this build" in err


def test_maintain_without_dry_run(cli, tmp_path):
    # The vault does not even exist: the usage error comes before any configuration is read.
    code, out, err = cli("memory", "maintain", HARNESS_VAULT_ROOT=str(tmp_path / "absent"))
    assert code != 0 and out == ""
    assert "--dry-run" in err
