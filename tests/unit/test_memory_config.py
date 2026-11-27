"""Memory configuration is read and validated only by the commands that use it (D1)."""

import pytest

from harness.memory.config import CONTEXT_DEFAULT_BYTES, load_memory_settings
from tests.conftest import note_header, query, run_main


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


def test_memory_commands_open_no_database(cli, vault, data_dir):
    for command in [
        ("memory", "search", "orquestador"),
        ("memory", "context", "demo-alpha"),
        ("memory", "maintain", "--dry-run"),
    ]:
        assert cli(*command, HARNESS_VAULT_ROOT=str(vault))[0] == 0, command
    assert not data_dir.exists()


def test_synced_folders_and_repositories_are_accepted(cli, vault, tmp_path):
    # Revised on 2026-11-24 (D3 reverted): the harness is for work only and the vault may live
    # in a corporate sync folder. A sync folder name, a git repository with a remote or a
    # leftover HARNESS_PROFILE no longer refuse anything.
    synced = tmp_path / "OneDrive - Ejemplo" / "CloudStorage" / "vault"
    synced.parent.mkdir(parents=True)
    vault.rename(synced)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text('[remote "origin"]\n')
    data = tmp_path / "Dropbox" / "data"
    for profile in ["", "work", "personal", "casa"]:
        code, out, err = cli(
            "memory", "context", "demo-alpha",
            HARNESS_VAULT_ROOT=str(synced), HARNESS_DATA_DIR=str(data), HARNESS_PROFILE=profile,
        )
        assert code == 0, (profile, err)
        assert note_header("projects/demo-alpha/_project.md") in out


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
    settings = load_memory_settings(env)
    assert settings.context_max_bytes == expected
    assert settings.vault_root == vault.resolve()


def test_ask_without_project_does_not_read_the_vault(cli, tmp_path):
    env = {"HARNESS_VAULT_ROOT": str(tmp_path / "does-not-exist")}
    session_id = cli("session", "create", "Sin memoria", **env)[1].strip()
    code, out, err = cli("ask", session_id, "pregunta", **env)
    assert code == 0, err
    assert out.strip() != ""
    code, out, _ = cli("history", session_id, **env)
    assert code == 0 and "pregunta" in out


def test_maintain_without_dry_run(cli, tmp_path):
    # The vault does not even exist: the usage error comes before any configuration is read.
    code, out, err = cli("memory", "maintain", HARNESS_VAULT_ROOT=str(tmp_path / "absent"))
    assert code != 0 and out == ""
    assert "--dry-run" in err
