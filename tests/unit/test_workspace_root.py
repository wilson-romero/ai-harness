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


# -- independent review of d0a65d8, finding 1: a second path to the same folders ----------------


def _mirror(monkeypatch, tmp_path: Path, volume: Path) -> None:
    """As APFS firmlinks (`/System/Volumes/Data/Users` is `/Users`) or a bind mount: under
    `volume`, `real/...` is the very directory `tmp_path/real/...` (same st_dev, st_ino) under
    another name; `volume` itself has an identity of its own, as the Data volume's root does."""
    real_identity = root_module._identity

    def identity(path):
        try:
            inside = Path(path).relative_to(volume)
        except ValueError:
            return real_identity(path)
        if inside.parts[:1] == ("real",):
            return real_identity(tmp_path / inside)
        return real_identity(path)

    monkeypatch.setattr(root_module, "_identity", identity)


@pytest.mark.parametrize("level", [0, 1, 2], ids=["the-volume", "its-parent", "its-grandparent"])
def test_a_folder_that_reaches_a_protected_folder_by_a_second_path_is_refused(
        tmp_path: Path, monkeypatch, level: int):
    data = tmp_path / "real" / "outer" / "data"
    data.mkdir(parents=True)
    volume = tmp_path / "system" / "volumes" / "data-volume"
    (volume / "real" / "outer" / "data").mkdir(parents=True)  # the second path, as a directory
    _mirror(monkeypatch, tmp_path, volume)
    candidate = [volume, volume.parent, volume.parent.parent][level]
    assert refused(str(candidate), data) == "data_dir"


def test_a_folder_beside_the_second_path_is_still_accepted(tmp_path: Path, monkeypatch):
    data = tmp_path / "real" / "outer" / "data"
    data.mkdir(parents=True)
    volume = tmp_path / "system" / "volumes" / "data-volume"
    (volume / "real" / "outer" / "data").mkdir(parents=True)
    (volume / "projects" / "work").mkdir(parents=True)
    _mirror(monkeypatch, tmp_path, volume)
    check_root(str(volume / "projects" / "work"), data_dir=data, environ={})


def test_a_folder_containing_the_home_folder_is_refused(tmp_path: Path, monkeypatch):
    home = tmp_path / "users" / "person"
    home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert refused(str(tmp_path / "users"), tmp_path / "data") == "home"
    # Two layers: the containment rule alone, without the search for a second path.
    monkeypatch.setattr(root_module, "_second_path", lambda candidate, protected: None)
    assert refused(str(tmp_path / "users"), tmp_path / "data") == "home"


def test_a_mount_point_is_refused(tmp_path: Path, monkeypatch):
    # A volume mounted on a folder: its st_dev differs from its parent's. Simulated, so that
    # the test does not depend on the machine's mounts.
    folder = tmp_path / "mounted"
    folder.mkdir()
    real_identity = root_module._identity

    def identity(path):
        found = real_identity(path)
        if found is not None and Path(path) == folder.resolve():
            return (found[0] + 1, found[1])
        return found

    monkeypatch.setattr(root_module, "_identity", identity)
    assert refused(str(folder), tmp_path / "data") == "mount_point"


@pytest.mark.parametrize("raw", [
    "\\\\?\\GLOBALROOT\\Device\\HarddiskVolume3\\Users",
    "\\\\localhost\\C$\\Users",
    "\\\\server\\share\\work",
    "//server/share/work",
    "/\\server\\share",
    "\\\\.\\C:\\work",
])
def test_a_network_or_device_path_is_refused_on_every_platform(tmp_path: Path, raw: str):
    assert refused(raw, tmp_path / "data") == "device_path"


def test_a_resolved_network_path_is_refused(tmp_path: Path, monkeypatch):
    # As a mapped network drive on Windows, which `resolve` may give back as UNC.
    folder = tmp_path / "mapped"
    folder.mkdir()
    real_resolve = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda self, strict=False: (
        Path("//server/share/mapped") if self == folder else real_resolve(self, strict=strict)))
    assert refused(str(folder), tmp_path / "data") == "device_path"


_DATA_VOLUME = Path("/System/Volumes/Data")


def _data_volume_mirrors(path: Path) -> bool:
    try:
        twin = _DATA_VOLUME / path.relative_to(path.anchor)
        a, b = os.stat(twin), os.stat(path)
    except (OSError, ValueError):
        return False
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


@pytest.mark.parametrize("raw", ["/System/Volumes/Data", "/System/Volumes", "/System"])
def test_the_real_data_volume_is_refused_where_the_machine_has_one(tmp_path: Path, raw: str):
    # Skipped by capability: only where the machine really shows the repository a second time
    # under /System/Volumes/Data (macOS with APFS firmlinks).
    data = tmp_path / "data"
    data.mkdir()
    if not _data_volume_mirrors(HARNESS_REPO) and not _data_volume_mirrors(data):
        pytest.skip("no second path to the repository or the data dir on this machine")
    assert refused(raw, data) in ("harness_repo", "data_dir", "home")
