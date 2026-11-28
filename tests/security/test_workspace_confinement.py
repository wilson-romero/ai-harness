"""The real path and the open (workspace-tools D2, phases 2 and 3): SEC-04 for the work folder.

Behaviours of Windows that cannot run here are simulated where the code asks the system a
question (a junction through `Path.is_junction`, a short name that the system would resolve);
the rest are NOT RUN until the Windows machine (tasks.md 8.2).
"""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import pytest

from harness.workspace import paths as paths_module
from harness.workspace.codes import WorkspaceRefused
from harness.workspace.paths import check_relative, locate, read_located
from harness.workspace.tools import read_file
from tests.conftest import make_symlink
from tests.workspace_support import built, root  # noqa: F401 - fixtures


def code_of(root, relative: str) -> str:
    with pytest.raises(WorkspaceRefused) as caught:
        read_file(root, relative)
    return caught.value.code


def test_an_ordinary_file_is_read(root):
    assert read_file(root, "src/app.py").total == 9


def test_a_name_with_other_case_is_refused(root):
    assert code_of(root, "src/App.py") == "name_not_exact"
    assert code_of(root, "SRC/app.py") == "name_not_exact"


def test_a_name_stored_in_another_normal_form_is_refused(root):
    nfd = unicodedata.normalize("NFD", "café.txt")
    (root.path / nfd).write_text("x\n", encoding="utf-8")
    listed = os.listdir(root.path)
    if "café.txt" in listed:  # the system stored the NFC form: nothing to tell apart
        pytest.skip("this file system normalises names to NFC")
    assert code_of(root, "café.txt") == "name_not_exact"


def test_a_name_the_system_would_resolve_but_does_not_list_is_never_opened(root, monkeypatch):
    # A Windows 8.3 short name (`PROGRA~1`) resolves to a long name that `listdir` returns
    # instead. Simulated: the walk must refuse from the listing alone, never `lstat` the alias.
    looked_up: list[str] = []
    real_lstat = os.lstat
    monkeypatch.setattr(paths_module.os, "lstat",
                        lambda p, *a, **k: (looked_up.append(str(p)), real_lstat(p, *a, **k))[1])
    assert code_of(root, "src/APP~1.PY") == "not_found"
    assert not any("APP~1" in path for path in looked_up)


def test_a_new_case_variant_is_never_looked_up_under_another_spelling(root):
    with pytest.raises(WorkspaceRefused) as caught:
        locate(root, check_relative("readme.md"))
    assert caught.value.code == "name_not_exact"


def test_a_link_to_a_file_outside_is_refused(built, root):
    if not built.links:
        pytest.skip("cannot create symbolic links here")
    assert code_of(root, "src/escape.py") == "link"


def test_a_folder_link_to_outside_is_refused(built, root):
    if not built.links:
        pytest.skip("cannot create symbolic links here")
    assert code_of(root, "docs/out/secret.txt") == "link"


def test_a_link_inside_pointing_inside_is_refused_too(root):
    make_symlink(root.path / "alias.py", root.path / "src" / "app.py")
    assert code_of(root, "alias.py") == "link"


def test_a_junction_on_the_path_is_refused(root, monkeypatch):
    # Windows behaviour simulated: a junction is a directory for `lstat`, not a symlink.
    real = Path.is_junction
    target = root.path / "docs"
    monkeypatch.setattr(Path, "is_junction", lambda self: self == target or real(self))
    assert code_of(root, "docs/guide.md") == "link"


def test_a_file_with_two_hard_links_is_refused(built, root):
    if not built.hard_link:
        pytest.skip("this file system has no hard links")
    assert code_of(root, "notes.txt") == "hard_link"
    assert code_of(root, "notes-again.txt") == "hard_link"


def test_a_file_swapped_for_a_link_between_the_walk_and_the_open(built, root, monkeypatch):
    victim = root.path / "src" / "util.py"
    probe = root.path / "probe"
    try:
        probe.symlink_to(built.outside / "secret.txt")
    except OSError:
        pytest.skip("cannot create symbolic links here")
    probe.unlink()

    def swap(path: Path) -> None:
        path.unlink()
        path.symlink_to(built.outside / "secret.txt")

    monkeypatch.setattr(paths_module, "before_open", swap)
    assert code_of(root, "src/util.py") == "changed"
    assert victim.is_symlink()


def test_a_file_replaced_by_another_between_the_walk_and_the_open(root, monkeypatch):
    def replace(path: Path) -> None:
        path.unlink()
        path.write_text("another file\n", encoding="utf-8")

    monkeypatch.setattr(paths_module, "before_open", replace)
    assert code_of(root, "src/util.py") == "changed"


def test_a_file_that_resolves_outside_after_the_open_is_refused(root, monkeypatch, tmp_path):
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("x\n", encoding="utf-8")
    real_resolve = Path.resolve
    target = root.path / "src" / "util.py"
    monkeypatch.setattr(Path, "resolve",
                        lambda self, strict=False: outside if self == target
                        else real_resolve(self, strict=strict))
    assert code_of(root, "src/util.py") == "outside_root"


def test_the_root_replaced_after_it_was_chosen_suspends_it(root, tmp_path):
    moved = tmp_path / "moved"
    root.path.rename(moved)
    root.path.mkdir()
    assert code_of(root, "README.md") == "workspace_changed"


def test_a_fifo_is_not_opened(root):
    if not hasattr(os, "mkfifo"):
        pytest.skip("os.mkfifo is not available here")
    os.mkfifo(root.path / "pipe")
    assert code_of(root, "pipe") == "not_regular"


def test_a_component_that_is_a_file_is_refused(root):
    assert code_of(root, "README.md/x") == "not_a_directory"


def test_reading_is_capped_on_the_descriptor(root, monkeypatch):
    # The file grows between the walk and the open (same file, so the identity still holds):
    # what is read is bounded by the cap, not by the size seen while walking.
    located = locate(root, check_relative("src/app.py"))

    def grow(path: Path) -> None:
        with path.open("ab") as handle:
            handle.write(b"#" * 100)

    monkeypatch.setattr(paths_module, "before_open", grow)
    with pytest.raises(WorkspaceRefused) as caught:
        read_located(root, located, max_bytes=located.info.st_size + 10)
    assert caught.value.code == "too_large"


def test_a_hard_link_made_between_the_walk_and_the_open_is_caught_on_the_descriptor(
        root, monkeypatch):
    def second_name(path: Path) -> None:
        try:
            os.link(path, path.with_name("second-name.py"))
        except OSError:
            pytest.skip("this file system has no hard links")

    monkeypatch.setattr(paths_module, "before_open", second_name)
    assert code_of(root, "src/util.py") == "hard_link"
