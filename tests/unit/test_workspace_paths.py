"""The shape of a relative path (workspace-tools D2, phase 1): a pure function of the string.

Every case here runs unchanged on every platform: the Windows forms (drives, UNC, `\\`,
streams, reserved names, trailing dots) are refused by rule, not by asking the system.
"""

from __future__ import annotations

import pytest

from harness.workspace.codes import FORM_CODES, WorkspaceRefused
from harness.workspace.paths import check_relative

REFUSED = [
    ("", "empty_path"),
    ("a" * 1025, "path_too_long"),  # literal bounds: a mutated constant must fail
    ("a\x00b", "forbidden_character"),
    ("a\u200bb", "invisible_character"),
    ("a\u202eb", "invisible_character"),
    ("a\x1b[31mb", "invisible_character"),
    ("a\nb", "invisible_character"),
    ("a\u2028b", "invisible_character"),
    ("a\tb", "invisible_character"),
    ("cafe\u0301.txt", "not_nfc"),
    ("/etc/hosts", "absolute"),
    ("//server/share/x", "absolute"),
    ("\\\\server\\share\\x", "absolute"),
    ("\\\\?\\C:\\x", "absolute"),
    ("\\x", "absolute"),
    ("C:\\x", "absolute"),
    ("C:x", "absolute"),
    ("c:/x", "absolute"),
    ("a\\b", "backslash"),
    ("a.txt:stream", "colon"),
    ("a.txt::$DATA", "colon"),
    ("a<b", "forbidden_character"),
    ("a>b", "forbidden_character"),
    ('a"b', "forbidden_character"),
    ("a|b", "forbidden_character"),
    ("a?b", "forbidden_character"),
    ("a*b", "forbidden_character"),
    ("a//b", "empty_component"),
    ("a/", "empty_component"),
    ("./a", "dot_component"),
    ("a/../b", "dot_component"),
    ("..", "dot_component"),
    ("a/" + "b" * 256, "component_too_long"),
    ("a/" + "é" * 128, "component_too_long"),  # 256 bytes in UTF-8
    ("a.", "trailing_dot_or_space"),
    ("a ", "trailing_dot_or_space"),
    ("dir./x", "trailing_dot_or_space"),
    ("NUL", "reserved_name"),
    ("nul", "reserved_name"),
    ("con.txt", "reserved_name"),
    ("src/Aux.py", "reserved_name"),
    ("COM1", "reserved_name"),
    ("lpt9.log", "reserved_name"),
    ("COM¹", "reserved_name"),
    ("CONIN$", "reserved_name"),
    ("CON .txt", "reserved_name"),
]

ACCEPTED = [
    ("src/app.py", ("src", "app.py")),
    ("README.md", ("README.md",)),
    (".github/workflows/ci.yml", (".github", "workflows", "ci.yml")),
    ("café.txt", ("café.txt",)),
    ("console.txt", ("console.txt",)),
    ("COM10", ("COM10",)),
    ("a b/c-d_e.f", ("a b", "c-d_e.f")),
    ("b" * 255, ("b" * 255,)),
    ("/".join(["a" * 200] * 5), ("a" * 200,) * 5),  # 1 004 characters: under the cap
]


@pytest.mark.parametrize(("text", "code"), REFUSED, ids=[repr(t)[:40] for t, _ in REFUSED])
def test_each_form_is_refused_with_its_reason(text: str, code: str):
    with pytest.raises(WorkspaceRefused) as caught:
        check_relative(text)
    assert caught.value.code == code


@pytest.mark.parametrize(("text", "parts"), ACCEPTED, ids=[t[:40] for t, _ in ACCEPTED])
def test_ordinary_relative_paths_are_accepted(text: str, parts: tuple[str, ...]):
    assert check_relative(text) == parts


def test_every_form_code_has_a_case():
    assert {code for _, code in REFUSED} == set(FORM_CODES)


def test_the_refusal_detail_never_repeats_the_path():
    hostile = "\x1b[31merror: fake/../x"
    with pytest.raises(WorkspaceRefused) as caught:
        check_relative(hostile)
    assert "fake" not in str(caught.value)
