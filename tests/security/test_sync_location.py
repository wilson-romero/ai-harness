"""SEC-13: with the work profile, no vault or data directory in a synced or network location (D3).

`location_refusal` is pure, so Windows inputs are checked here with `PureWindowsPath`.
"""

from pathlib import PurePosixPath, PureWindowsPath

import pytest

from harness.memory.config import GIT_REMOTE_MARKER, collect_markers, location_refusal
from tests.conftest import query

W = PureWindowsPath
P = PurePosixPath


@pytest.mark.parametrize(
    ("path", "named"),
    [
        (P("/home-sintetico/u/Library/CloudStorage/Proveedor/vault"), "'CloudStorage'"),
        (P("/home-sintetico/u/Library/Mobile Documents/vault"), "'Mobile Documents'"),
        (W(r"C:\Datos\OneDrive - Ejemplo\vault"), "'OneDrive - Ejemplo'"),
        (W(r"C:\Datos\onedrive\vault"), "'onedrive'"),
        (P("/datos/Dropbox (Ejemplo)/vault"), "'Dropbox (Ejemplo)'"),
        (W(r"D:\Google Drive\vault"), "'Google Drive'"),
        (P("/datos/iCloud Drive/vault"), "'iCloud Drive'"),
    ],
)
def test_sync_folder_components(path, named):
    reason = location_refusal(path, {}, {})
    assert reason is not None and named in reason


def test_path_under_the_onedrive_commercial_variable():
    env = {"OneDriveCommercial": r"C:\Datos\Empresa Sincronizada"}
    path = W(r"c:\datos\empresa sincronizada\notas\vault")
    reason = location_refusal(path, {}, env)
    assert reason is not None and "OneDriveCommercial" in reason
    assert location_refusal(W(r"C:\Datos\Local\vault"), {}, env) is None


def test_variable_that_does_not_exist_adds_nothing():
    assert location_refusal(P("/srv/vault"), {}, {"OneDrive": ""}) is None


def test_ancestor_with_a_sync_marker():
    path = P("/srv/compartido/notas/vault")
    reason = location_refusal(path, {P("/srv/compartido"): frozenset({".stfolder"})}, {})
    assert reason is not None and ".stfolder" in reason


def test_ancestor_with_a_git_remote():
    path = W(r"C:\repos\notas\vault")
    reason = location_refusal(path, {W(r"C:\repos\notas"): frozenset({GIT_REMOTE_MARKER})}, {})
    assert reason is not None and ".git" in reason


@pytest.mark.parametrize(
    "path", [W(r"\\servidor\recurso\vault"), P("//servidor/recurso/vault")]
)
def test_network_path_refused(path):
    assert location_refusal(path, {}, {}) == "it is a network path"


@pytest.mark.parametrize(
    "path", [P("/srv/vault"), W(r"C:\Datos\vault"), P("/srv/Drive/vault"), W(r"C:\sync-notas")]
)
def test_ordinary_paths_accepted(path):
    assert location_refusal(path, {}, {}) is None


# -- markers on the real file system ------------------------------------------------------------


def test_collect_markers_finds_a_git_remote_but_not_a_plain_git(tmp_path):
    with_remote = tmp_path / "con-remoto"
    (with_remote / ".git").mkdir(parents=True)
    (with_remote / ".git" / "config").write_text('[core]\n\tbare = false\n[remote "origin"]\n')
    without = tmp_path / "sin-remoto"
    (without / ".git").mkdir(parents=True)
    (without / ".git" / "config").write_text("[core]\n\tbare = false\n")
    (with_remote / "vault").mkdir()
    (without / "vault").mkdir()

    assert collect_markers(with_remote / "vault").get(with_remote) == {GIT_REMOTE_MARKER}
    assert with_remote not in collect_markers(without / "vault")
    assert without not in collect_markers(without / "vault")


def test_collect_markers_follows_a_worktree_git_file(tmp_path):
    main_git = tmp_path / "principal" / ".git"
    (main_git / "worktrees" / "wt").mkdir(parents=True)
    (main_git / "config").write_text('[remote "origin"]\n')
    (main_git / "worktrees" / "wt" / "commondir").write_text("../..\n")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {main_git / 'worktrees' / 'wt'}\n")
    assert collect_markers(worktree).get(worktree) == {GIT_REMOTE_MARKER}


# -- end to end through the CLI -----------------------------------------------------------------


def _move(vault, new_parent):
    new_parent.mkdir(parents=True)
    target = new_parent / "vault"
    vault.rename(target)
    return target


def test_work_vault_in_sync_folder(cli, vault, tmp_path, data_dir):
    synced = _move(vault, tmp_path / "CloudStorage")
    code, out, err = cli("memory", "search", "orquestador", HARNESS_VAULT_ROOT=str(synced))
    assert code != 0 and out == ""
    assert "work profile" in err and "'CloudStorage'" in err
    assert not (data_dir / "harness.sqlite3").exists()


def test_work_vault_under_git_remote(cli, vault, tmp_path):
    repo = tmp_path / "repo"
    synced = _move(vault, repo)
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text('[remote "origin"]\n\turl = ejemplo\n')
    code, out, err = cli("memory", "search", "orquestador", HARNESS_VAULT_ROOT=str(synced))
    assert code != 0 and out == "" and ".git (with a remote)" in err


def test_work_vault_under_plain_git_is_accepted(cli, vault, tmp_path):
    repo = tmp_path / "repo"
    local = _move(vault, repo)
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[core]\n\tbare = false\n")
    code, out, err = cli("memory", "search", "orquestador", HARNESS_VAULT_ROOT=str(local))
    assert code == 0, err


def test_work_vault_on_network_path(cli, data_dir):
    network = "//servidor/recurso/vault"
    code, out, err = cli("memory", "search", "orquestador", HARNESS_VAULT_ROOT=network)
    assert code != 0 and out == ""
    assert "network path" in err


def test_work_vault_under_onedrive_variable(cli, vault, tmp_path):
    code, out, err = cli(
        "memory", "search", "orquestador", HARNESS_VAULT_ROOT=str(vault), OneDrive=str(tmp_path)
    )
    assert code != 0 and "OneDrive variable" in err


def test_personal_vault_in_sync_folder(cli, vault, tmp_path, data_dir):
    synced = _move(vault, tmp_path / "CloudStorage")
    code, out, err = cli(
        "memory", "search", "orquestador ventas",
        HARNESS_VAULT_ROOT=str(synced), HARNESS_PROFILE="personal",
    )
    assert code == 0, err
    assert "projects/demo-alpha/_project.md" in out
    assert query(data_dir, "SELECT profile FROM memory_binding") == [("personal",)]


def test_work_data_dir_in_sync_folder(cli, vault, tmp_path):
    synced_data = tmp_path / "OneDrive - Ejemplo" / "datos"
    env = {"HARNESS_VAULT_ROOT": str(vault), "HARNESS_DATA_DIR": str(synced_data)}
    code, out, err = cli("memory", "search", "orquestador", **env)
    assert code != 0 and out == ""
    assert "data directory" in err and "'OneDrive - Ejemplo'" in err
    assert not synced_data.exists()
