"""Pure path validation (D4): the same answers for Windows and POSIX inputs, on any platform."""

from pathlib import PurePosixPath, PureWindowsPath

import pytest

from harness.core.errors import InvalidProject
from harness.memory.paths import is_network_path, is_within, validate_project_slug

REJECTED = [
    "..",
    ".",
    "../../etc",
    "..\\otro",
    "a/b",
    "a\\b",
    "C:\\vault",
    "C:",
    "\\\\servidor\\recurso",
    "CON",
    "con",
    "nul.txt",
    "COM1",
    "lpt9.md",
    "demo.",
    "demo ",
    "a:b",
    "",
    ".oculto",
    "-guion",
    "x" * 129,
    "demo\x1balpha",
    "demo\u00e9",
]


@pytest.mark.parametrize("raw", REJECTED)
def test_rejected_project_identifiers(raw):
    with pytest.raises(InvalidProject) as caught:
        validate_project_slug(raw)
    # One message shape for every platform: it names the input and the rule, nothing else.
    assert str(caught.value) == (
        f"invalid project identifier {raw!r}: use the plain name of a folder under projects/"
    )


@pytest.mark.parametrize(
    "raw", ["demo-alpha", "p_1.v2", "Demo-Alpha", "x" * 128, "console", "com10"]
)
def test_accepted_project_identifiers(raw):
    assert validate_project_slug(raw) == raw


@pytest.mark.parametrize(
    "path",
    [
        PureWindowsPath(r"\\servidor\recurso\vault"),
        PureWindowsPath(r"\\servidor\recurso"),
        PureWindowsPath("//servidor/recurso/vault"),
        PurePosixPath("//servidor/recurso/vault"),
    ],
)
def test_network_paths(path):
    assert is_network_path(path)


@pytest.mark.parametrize(
    "path",
    [PureWindowsPath(r"C:\vault"), PureWindowsPath(r"\vault"), PurePosixPath("/srv/vault")],
)
def test_local_paths(path):
    assert not is_network_path(path)


def test_containment_windows_is_case_insensitive():
    root = PureWindowsPath(r"c:\vault")
    assert is_within(PureWindowsPath(r"C:\Vault\projects\x.md"), root)
    assert not is_within(PureWindowsPath(r"C:\vault-b\x.md"), root)
    assert not is_within(PureWindowsPath(r"D:\vault\x.md"), root)


def test_containment_posix_is_exact():
    root = PurePosixPath("/srv/vault")
    assert is_within(PurePosixPath("/srv/vault/projects/x.md"), root)
    assert not is_within(PurePosixPath("/srv/Vault/projects/x.md"), root)
    assert not is_within(PurePosixPath("/srv/vault-b/x.md"), root)


def test_containment_is_not_fooled_by_unresolved_parent_parts():
    # Pure paths keep `..`: containment must be checked on resolved paths, which the walk does.
    assert PureWindowsPath(r"C:\Vault\..\x").parts[-2] == ".."
