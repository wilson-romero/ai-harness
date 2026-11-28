"""Pure path validation (D4): the same answers for Windows and POSIX inputs, on any platform."""

from pathlib import PurePosixPath, PureWindowsPath

import pytest

from harness.core.errors import InvalidProject
from harness.memory.paths import is_within, validate_project_slug

SEPARATOR = "it contains a path separator"
RESERVED = "it is a reserved Windows device name"
OTHER = "it contains a character other than letters, digits, '.', '_' and '-'"
# Input -> the reason the message names (memory-format-conformance D3, 2026-11-28).
REJECTED = {
    "..": "it is a relative path part",
    ".": "it is a relative path part",
    "../../etc": SEPARATOR,
    "..\\otro": SEPARATOR,
    "a/b": SEPARATOR,
    "a\\b": SEPARATOR,
    "C:\\vault": SEPARATOR,
    "C:": OTHER,
    "\\\\servidor\\recurso": SEPARATOR,
    "CON": RESERVED,
    "con": RESERVED,
    "nul.txt": RESERVED,
    "COM1": RESERVED,
    "lpt9.md": RESERVED,
    "demo.": "it ends with a dot or a space",
    "demo ": "it ends with a dot or a space",
    "a:b": OTHER,
    "": "it is empty",
    ".oculto": "it does not start with a letter or a digit",
    "-guion": "it does not start with a letter or a digit",
    "x" * 129: "it is longer than 128 characters",
    "demo\x1balpha": OTHER,
    "demo\u00e9": "it contains a character that is not ASCII",
    # The forms a `vault_slug` of claude-memory-system takes from a real path (its
    # `scripts/lib/common.sh` at 92b19ea keeps spaces and accents): refused, with the reason.
    "srv-equipo-Mis Proyectos-demo": "it contains a space",
    "srv-equipo-Código-demo": "it contains a character that is not ASCII",
    "srv-" + "carpeta-" * 16 + "demo": "it is longer than 128 characters",
}


@pytest.mark.parametrize(("raw", "reason"), REJECTED.items())
def test_rejected_project_identifiers(raw, reason):
    with pytest.raises(InvalidProject) as caught:
        validate_project_slug(raw)
    # One message shape for every platform: it names the input, why it is refused and the
    # rule, nothing else.
    assert str(caught.value) == (
        f"invalid project identifier {raw!r}: {reason}; use the plain name of a folder under "
        "projects/ (letters, digits, '.', '_' and '-', starting with a letter or a digit, at "
        "most 128 characters)"
    )


@pytest.mark.parametrize(
    "raw", ["demo-alpha", "p_1.v2", "Demo-Alpha", "x" * 128, "console", "com10"]
)
def test_accepted_project_identifiers(raw):
    assert validate_project_slug(raw) == raw


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
    # Pure paths keep `..`, and pathlib alone says `C:\Vault\..\x` is relative to `C:\Vault`.
    assert PureWindowsPath(r"C:\Vault\..\x").is_relative_to(PureWindowsPath(r"C:\Vault"))
    assert not is_within(PureWindowsPath(r"C:\Vault\..\x"), PureWindowsPath(r"C:\Vault"))
    assert not is_within(PurePosixPath("/srv/vault/../x"), PurePosixPath("/srv/vault"))
    assert not is_within(PurePosixPath("/srv/vault/a"), PurePosixPath("/srv/vault/.."))
    assert is_within(PurePosixPath("/srv/vault/a..b/x"), PurePosixPath("/srv/vault"))
