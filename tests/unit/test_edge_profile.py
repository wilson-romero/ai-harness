"""Only a dedicated profile is accepted: new, empty, or carrying the harness marker."""

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
