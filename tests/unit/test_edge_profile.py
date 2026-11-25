"""Only a dedicated profile is accepted: new, empty, or carrying the harness marker."""

import os
import stat

import pytest

from harness.browser.errors import ProfileRejected
from harness.browser.profile import PROFILE_MARKER, prepare_profile


def test_new_profile_is_created_with_the_marker(tmp_path):
    profile = tmp_path / "nested" / "edge-profile"
    assert prepare_profile(profile) == profile
    assert (profile / PROFILE_MARKER).is_file()


def test_empty_directory_is_accepted_and_marked(tmp_path):
    prepare_profile(tmp_path)
    assert (tmp_path / PROFILE_MARKER).is_file()


def test_marked_profile_with_browser_data_is_accepted(tmp_path):
    prepare_profile(tmp_path)
    (tmp_path / "Default").mkdir()
    (tmp_path / "Local State").write_text("{}", encoding="utf-8")
    prepare_profile(tmp_path)


def test_foreign_directory_is_rejected_and_left_untouched(tmp_path):
    (tmp_path / "Local State").write_text("{}", encoding="utf-8")
    with pytest.raises(ProfileRejected, match="not an ai-harness Edge profile"):
        prepare_profile(tmp_path)
    assert not (tmp_path / PROFILE_MARKER).exists()
    assert [p.name for p in tmp_path.iterdir()] == ["Local State"]


def test_a_file_is_not_a_profile(tmp_path):
    target = tmp_path / "profile"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(ProfileRejected, match="not a directory"):
        prepare_profile(target)


# The profile holds the session cookies, and with the basic password store (design D3) whoever
# can read the directory can decrypt them. Mode bits are checked where the system has them;
# elsewhere `os.chmod` only clears a read-only flag and the check below is skipped.
owner_only = pytest.mark.skipif(not hasattr(os, "getuid"), reason="no POSIX mode bits here")


@owner_only
def test_new_profile_is_readable_by_its_owner_only(tmp_path):
    previous = os.umask(0o022)  # the common default, which would leave it readable by all
    try:
        profile = prepare_profile(tmp_path / "nested" / "edge-profile")
    finally:
        os.umask(previous)
    assert stat.S_IMODE(profile.stat().st_mode) == 0o700


@owner_only
def test_existing_harness_profile_is_narrowed_to_its_owner(tmp_path):
    profile = prepare_profile(tmp_path / "edge-profile")
    profile.chmod(0o755)  # made by an earlier version, or loosened by hand
    prepare_profile(profile)
    assert stat.S_IMODE(profile.stat().st_mode) == 0o700


@owner_only
def test_foreign_directory_keeps_its_permissions(tmp_path):
    foreign = tmp_path / "someone-elses"
    foreign.mkdir()
    (foreign / "Local State").write_text("{}", encoding="utf-8")
    foreign.chmod(0o755)
    with pytest.raises(ProfileRejected):
        prepare_profile(foreign)
    assert stat.S_IMODE(foreign.stat().st_mode) == 0o755
