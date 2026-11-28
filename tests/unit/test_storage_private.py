"""`private_file` and `private_dir` give the same outcome on every system (hardening F-08,
second Windows run of 2026-11-27).

Where the systems differ in how they report a case, the case is also run with the other
system's report simulated: Windows answers `os.open(..., O_CREAT | O_EXCL)` on an existing
directory with PermissionError (errno 13), where POSIX says FileExistsError.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

import pytest

from harness.storage import private
from harness.storage.private import private_dir, private_file
from tests.conftest import make_symlink

OWNER_ONLY = hasattr(os, "getuid")  # POSIX permission bits mean something here
REAL_OPEN = os.open


def _windows_open(path, flags, mode=0o777, *args, **kwargs):
    """`os.open` as Windows answers it: an existing directory is 'permission denied'."""
    if flags & os.O_EXCL and os.path.isdir(path):
        raise PermissionError(errno.EACCES, "Permission denied", str(path))
    return REAL_OPEN(path, flags, mode, *args, **kwargs)


@pytest.fixture(params=["this system", "windows open"])
def system(request, monkeypatch):
    if request.param == "windows open":
        monkeypatch.setattr(private.os, "open", _windows_open)
    return request.param


def _kind(path: Path) -> str:
    if path.is_symlink():
        return "link"
    return "dir" if path.is_dir() else "file"


# -- private_file -----------------------------------------------------------------------------


def test_a_missing_file_is_created_empty(tmp_path, system):
    target = tmp_path / "new.db"
    private_file(target)
    assert target.is_file() and target.read_bytes() == b""


@pytest.mark.skipif(not OWNER_ONLY, reason="POSIX permission bits are not used on this system")
def test_a_missing_file_is_created_owner_only(tmp_path, system):
    target = tmp_path / "new.db"
    private_file(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize("existing", ["file", "dir", "link to file", "link to dir", "broken link"])
def test_whatever_already_exists_is_left_as_it_is(tmp_path, system, existing):
    target = tmp_path / "entry"
    other = tmp_path / "other"
    if existing == "file":
        target.write_bytes(b"kept")
    elif existing == "dir":
        target.mkdir()
    elif existing == "link to file":
        other.write_bytes(b"kept")
        make_symlink(target, other)
    elif existing == "link to dir":
        other.mkdir()
        make_symlink(target, other)
    else:
        make_symlink(target, tmp_path / "missing")
    before = _kind(target)
    private_file(target)  # returns: the caller's own open says what is wrong, if anything
    assert _kind(target) == before
    if existing in ("file", "link to file"):
        assert target.read_bytes() == b"kept"


def test_a_missing_parent_is_an_error(tmp_path, system):
    with pytest.raises(FileNotFoundError):
        private_file(tmp_path / "missing" / "new.db")


def test_permission_denied_with_nothing_there_is_raised(tmp_path, monkeypatch):
    """The classification after the error never swallows a real refusal (negative control)."""
    def refuse(path, *args, **kwargs):
        raise PermissionError(errno.EACCES, "Permission denied", str(path))

    monkeypatch.setattr(private.os, "open", refuse)
    with pytest.raises(PermissionError):
        private_file(tmp_path / "new.db")
    assert not os.path.lexists(tmp_path / "new.db")


def test_a_directory_the_account_cannot_write_is_an_error(tmp_path):
    folder = tmp_path / "read-only"
    folder.mkdir()
    folder.chmod(0o500)
    try:
        try:
            (folder / "probe").touch()
        except PermissionError:
            pass
        else:
            pytest.skip("this account can write a 0500 directory here (no POSIX bits, or root)")
        with pytest.raises(PermissionError):
            private_file(folder / "new.db")
    finally:
        folder.chmod(0o700)


# -- private_dir ------------------------------------------------------------------------------


def test_missing_directories_are_created_with_their_parents(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    private_dir(target)
    assert target.is_dir()


@pytest.mark.skipif(not OWNER_ONLY, reason="POSIX permission bits are not used on this system")
def test_missing_directories_are_owner_only(tmp_path):
    private_dir(tmp_path / "a" / "b")
    for path in (tmp_path / "a", tmp_path / "a" / "b"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_an_existing_directory_or_a_link_to_one_is_accepted(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    private_dir(real)
    make_symlink(tmp_path / "link", real)
    private_dir(tmp_path / "link")
    assert (tmp_path / "link").is_symlink()


@pytest.mark.parametrize("existing", ["file", "link to file", "broken link"])
def test_something_else_at_the_path_is_not_a_directory(tmp_path, existing):
    target = tmp_path / "entry"
    if existing == "file":
        target.write_bytes(b"kept")
    elif existing == "link to file":
        (tmp_path / "other").write_bytes(b"kept")
        make_symlink(target, tmp_path / "other")
    else:
        make_symlink(target, tmp_path / "missing")
    with pytest.raises(NotADirectoryError):
        private_dir(target)
    with pytest.raises(NotADirectoryError):
        private_dir(target / "below")  # POSIX said NotADirectoryError, Windows FileNotFoundError


def test_a_directory_the_account_cannot_write_is_an_error_for_a_directory(tmp_path):
    folder = tmp_path / "read-only"
    folder.mkdir()
    folder.chmod(0o500)
    try:
        try:
            (folder / "probe").mkdir()
        except PermissionError:
            pass
        else:
            pytest.skip("this account can write a 0500 directory here (no POSIX bits, or root)")
        with pytest.raises(PermissionError):
            private_dir(folder / "new")
    finally:
        folder.chmod(0o700)
