"""What is never read, even inside the work folder (workspace-tools D3)."""

from __future__ import annotations

import pytest

from harness.workspace.codes import WorkspaceRefused
from harness.workspace.rules import (
    DENIED_COMPONENTS,
    DENIED_NAMES,
    DENIED_PREFIXES,
    DENIED_SUFFIXES,
    FILE_MAX_BYTES,
    decode_checked,
    name_refusal,
)
from harness.workspace.tools import read_file
from tests.workspace_support import built, builder, root  # noqa: F401 - fixtures

NAME_CASES = (
    [(f"{c}/config", "denied_component") for c in sorted(DENIED_COMPONENTS)]
    + [(f"sub/{c}", "denied_component") for c in sorted(DENIED_COMPONENTS)]
    + [(n, "denied_name") for n in sorted(DENIED_NAMES)]
    + [(f"keys/{p}.pub", "denied_name") for p in DENIED_PREFIXES]
    + [(f"tls/server{s}", "denied_name") for s in DENIED_SUFFIXES]
    + [(".env.local", "denied_name"), (".ENV", "denied_name"), (".Git/HEAD", "denied_component"),
       ("Server.PEM", "denied_name")]
)


@pytest.mark.parametrize(("relative", "code"), NAME_CASES, ids=[r for r, _ in NAME_CASES])
def test_each_denied_name_is_refused(relative: str, code: str):
    assert name_refusal(tuple(relative.split("/"))) == code


@pytest.mark.parametrize("relative", [".env.example", ".env.sample", ".env.template",
                                      "src/env.py", "gitignore.txt", "keys.md", "pem.txt",
                                      ".github/workflows/ci.yml"])
def test_look_alikes_are_not_denied(relative: str):
    assert name_refusal(tuple(relative.split("/"))) is None


@pytest.mark.parametrize(("relative", "code"), [
    (".env", "denied_name"),
    (".git/config", "denied_component"),
    ("deploy.pem", "denied_name"),
    ("config/settings.py", "credential_in_file"),
    ("image.bin", "binary"),
    ("latin1.txt", "binary"),
    ("big.txt", "too_large"),
])
def test_the_fixture_cases_are_refused(root, relative: str, code: str):
    with pytest.raises(WorkspaceRefused) as caught:
        read_file(root, relative)
    assert caught.value.code == code


def test_a_denied_name_is_refused_before_the_disk_is_touched(root, monkeypatch):
    from harness.workspace import paths as paths_module

    monkeypatch.setattr(paths_module.os, "listdir",
                        lambda *a: pytest.fail("the walk ran for a denied name"))
    with pytest.raises(WorkspaceRefused):
        read_file(root, ".git/config")


def test_a_credential_split_by_an_invisible_character_is_found():
    key = builder.fake_aws_key()
    hidden = (key[:6] + "​" + key[6:]).encode("utf-8")
    with pytest.raises(WorkspaceRefused) as caught:
        decode_checked(hidden)
    assert caught.value.code == "credential_in_file"


def test_a_nul_after_the_sniff_window_is_still_text_but_shown_escaped():
    raw = b"a" * (8 * 1024) + b"\x00b\n"
    assert decode_checked(raw).text.endswith("\x00b\n")


def test_the_size_cap_is_exact():
    decode_checked(b"a" * FILE_MAX_BYTES)
    with pytest.raises(WorkspaceRefused):
        decode_checked(b"a" * (FILE_MAX_BYTES + 1))


def test_a_bom_is_accepted_and_reported():
    decoded = decode_checked(b"\xef\xbb\xbfhi\n")
    assert decoded.bom and decoded.text == "hi\n"
