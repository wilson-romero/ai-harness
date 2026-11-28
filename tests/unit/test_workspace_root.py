"""Choosing the work folder (workspace-tools D1, B1-1, B1-2)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.workspace import root as root_module
from harness.workspace.codes import WorkspaceRefused
from harness.workspace.root import HARNESS_REPO, check_root
from tests.conftest import make_symlink


def refused(raw: str, data_dir: Path, environ=None) -> str:
    with pytest.raises(WorkspaceRefused) as caught:
        check_root(raw, data_dir=data_dir, environ=environ or {})
    return caught.value.code


def test_an_ordinary_folder_is_accepted_resolved(tmp_path: Path):
    folder = tmp_path / "work"
    folder.mkdir()
    root = check_root(str(folder), data_dir=tmp_path / "data", environ={})
    assert root.path == folder.resolve()
    info = os.stat(folder)
    assert (root.device, root.inode) == (info.st_dev, info.st_ino)


def test_a_relative_folder_is_refused(tmp_path: Path):
    assert refused("work", tmp_path / "data") == "not_absolute"
    assert refused("", tmp_path / "data") == "not_absolute"


def test_a_missing_folder_is_refused(tmp_path: Path):
    assert refused(str(tmp_path / "missing"), tmp_path / "data") == "root_not_found"


def test_a_file_is_refused(tmp_path: Path):
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    assert refused(str(tmp_path / "file.txt"), tmp_path / "data") == "not_a_directory"


def test_a_link_as_the_folder_is_refused(tmp_path: Path):
    (tmp_path / "real").mkdir()
    make_symlink(tmp_path / "alias", tmp_path / "real")
    assert refused(str(tmp_path / "alias"), tmp_path / "data") == "link"


def test_a_junction_as_the_folder_is_refused(tmp_path: Path, monkeypatch):
    # Windows behaviour simulated: a directory junction is not a symlink for `lstat`.
    folder = tmp_path / "junction"
    folder.mkdir()
    real = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda self: self == folder or real(self))
    assert refused(str(folder), tmp_path / "data") == "link"


def test_a_folder_under_a_system_link_is_accepted_resolved(tmp_path: Path):
    (tmp_path / "real" / "work").mkdir(parents=True)
    make_symlink(tmp_path / "alias", tmp_path / "real")
    root = check_root(str(tmp_path / "alias" / "work"), data_dir=tmp_path / "data", environ={})
    assert root.path == (tmp_path / "real" / "work").resolve()


@pytest.mark.parametrize("where", ["itself", "inside"])
def test_the_harness_repository_is_refused(tmp_path: Path, where: str):
    target = HARNESS_REPO if where == "itself" else HARNESS_REPO / "harness"
    assert refused(str(target), tmp_path / "data") == "harness_repo"


def test_a_folder_containing_the_harness_repository_is_refused(tmp_path: Path):
    assert refused(str(HARNESS_REPO.parent), tmp_path / "data") == "harness_repo"


@pytest.mark.parametrize("where", ["itself", "inside", "containing"])
def test_the_data_dir_is_refused_both_ways(tmp_path: Path, where: str):
    data = tmp_path / "outer" / "data"
    (data / "sub").mkdir(parents=True)
    target = {"itself": data, "inside": data / "sub", "containing": tmp_path / "outer"}[where]
    assert refused(str(target), data) == "data_dir"


def test_a_data_dir_that_does_not_exist_yet_is_still_protected(tmp_path: Path):
    (tmp_path / "work").mkdir()
    assert refused(str(tmp_path / "work"), tmp_path / "work" / "data") == "data_dir"


@pytest.mark.parametrize("where", ["itself", "inside", "containing"])
def test_the_vault_is_refused_both_ways(tmp_path: Path, where: str):
    vault = tmp_path / "outer" / "vault"
    (vault / "projects").mkdir(parents=True)
    target = {"itself": vault, "inside": vault / "projects", "containing": tmp_path / "outer"}
    code = refused(str(target[where]), tmp_path / "data", {"HARNESS_VAULT_ROOT": str(vault)})
    assert code == "vault"


def test_no_vault_configured_protects_nothing_more(tmp_path: Path):
    (tmp_path / "work").mkdir()
    check_root(str(tmp_path / "work"), data_dir=tmp_path / "data",
               environ={"HARNESS_VAULT_ROOT": "  "})


def test_the_home_folder_itself_is_refused_but_not_inside_it(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    (home / "code").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert refused(str(home), tmp_path / "data") == "home"
    check_root(str(home / "code"), data_dir=tmp_path / "data", environ={})


def test_a_filesystem_root_is_refused(tmp_path: Path):
    anchor = Path(tmp_path.anchor)
    code = refused(str(anchor), tmp_path / "data")
    # The file-system root contains the repository, so the first rule may already catch it;
    # with the protected folders elsewhere, the root rule itself says no.
    assert code in ("harness_repo", "filesystem_root")


def test_the_filesystem_root_rule_alone(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(root_module, "protected_folders", lambda data_dir, environ: [])
    assert refused(str(Path(tmp_path.anchor)), tmp_path / "data") == "filesystem_root"


def test_protected_folder_written_with_other_case_is_refused(tmp_path: Path):
    data = tmp_path / "Data"
    data.mkdir()
    # The protected folder is named with other case (as a person may type it on a file
    # system that does not tell case apart): the name rule alone refuses it.
    assert refused(str(data), tmp_path / "DATA") == "data_dir"


def test_containment_by_identity_when_names_differ(tmp_path: Path, monkeypatch):
    real = tmp_path / "real"
    (real / "data").mkdir(parents=True)
    make_symlink(tmp_path / "alias", real)
    # As on a file system where resolving does not give one spelling (case on APFS or NTFS):
    # the protected path keeps a name that differs from the folder's, only the identity
    # (st_dev, st_ino) of the ancestors says they are the same.
    monkeypatch.setattr(root_module, "_resolved", lambda path: path)
    assert refused(str(real), tmp_path / "alias" / "data") == "data_dir"
    assert refused(str(real / "data"), tmp_path / "alias") == "data_dir"


def _refused(raw: Path, **kwargs) -> str:
    with pytest.raises(WorkspaceRefused) as caught:
        check_root(str(raw), **kwargs)
    return caught.value.code


def test_a_vault_that_does_not_exist_yet_is_still_protected_by_name(tmp_path: Path, monkeypatch):
    # No identity to compare (the folder is not there, or the system gives none): the name
    # rule alone must refuse a work folder that would contain the vault later.
    monkeypatch.setattr(root_module, "_identity", lambda path: None)
    parent = tmp_path / "projects"
    parent.mkdir()
    env = {"HARNESS_VAULT_ROOT": str(parent / "vault-later")}
    assert _refused(parent, data_dir=tmp_path / "data", environ=env) == "vault"


def test_the_name_rule_ignores_case(tmp_path: Path, monkeypatch):
    # On a case-sensitive system `Projects` and `projects` are two folders and identity does
    # not tie them; the name rule still refuses (a protected name is protected in every case).
    monkeypatch.setattr(root_module, "_identity", lambda path: None)
    folder = tmp_path / "projects"
    folder.mkdir()
    env = {"HARNESS_VAULT_ROOT": str(tmp_path / "PROJECTS" / "vault")}
    assert _refused(folder, data_dir=tmp_path / "data", environ=env) == "vault"
