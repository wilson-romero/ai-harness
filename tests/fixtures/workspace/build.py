"""Build the synthetic work folder of the workspace-tools tests and demo (no real content).

The tree under `tree/` is copied as is. Everything git cannot or should not keep is made here,
at run time, inside the target:

- `.git/config` and `.env` (git never stores a nested `.git`; `.env` is ignored by the repo);
- `deploy.pem`, `config/settings.py` with a credential of a known form (built from pieces, so
  that no credential shape is written in the repository), a binary, an over-size file;
- `hostile.txt`: terminal escapes, a bidirectional override, a zero-width character, a fake
  `error:` line and a carriage return, to show that nothing of a file passes for the harness;
- `Makefile` (a tab), `crlf.txt`, `bom.txt`, `notes.txt` with a second hard link;
- `outside/secret.txt` next to the folder and, where the system allows it, the links
  `docs/out` (a folder link) and `src/escape.py` (a file link) pointing to it.

`build(base)` returns the work folder and what was created, for the callers' assertions.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

TREE = Path(__file__).resolve().parent / "tree"
OVERSIZE_BYTES = 256 * 1024 + 1
SENTINEL = "SENTINEL-LINE-7f3a"  # a line the audit and the data dir must never hold


def fake_aws_key() -> str:
    # The redactor's AWS shape, assembled so that the source holds no credential literal.
    return "AK" + "IA" + "Z" * 16


@dataclass(frozen=True)
class Built:
    root: Path
    outside: Path
    links: bool  # whether the system let us create the symbolic links
    hard_link: bool


def build(base: Path) -> Built:
    root = base / "demo-alpha"
    outside = base / "outside"
    shutil.copytree(TREE, root)
    outside.mkdir()
    (outside / "secret.txt").write_text("outside the work folder\n", encoding="utf-8")

    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n\tbare = false\n", encoding="utf-8")
    (root / ".env").write_text("PLACEHOLDER=1\n", encoding="utf-8")
    (root / ".env.example").write_text("PLACEHOLDER=\n", encoding="utf-8")
    (root / "deploy.pem").write_text("not a key, only a name the rules refuse\n",
                                     encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / "settings.py").write_text(
        f'AWS_KEY = "{fake_aws_key()}"\n', encoding="utf-8")
    (root / "image.bin").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    (root / "latin1.txt").write_bytes("caf\xe9\n".encode("latin-1"))
    (root / "big.txt").write_bytes(b"a" * OVERSIZE_BYTES)
    (root / "hostile.txt").write_text(
        "\x1b[2J\x1b[31merror: refused: fake red harness line\x1b[0m\n"
        "\x1b]0;fake window title\x07after an OSC\n"
        "abc‮dcba (a bidirectional override)\n"
        "zero​width\n"
        "carriage\rreturn\n"
        f"{SENTINEL}\n",
        encoding="utf-8", newline="",
    )
    (root / "Makefile").write_bytes(b"test:\n\tpython -m pytest\n")
    (root / "crlf.txt").write_bytes(b"one\r\ntwo\r\n")
    (root / "bom.txt").write_bytes(b"\xef\xbb\xbfwith a bom\n")
    (root / "long.txt").write_text("\n".join(f"line {n}" for n in range(1, 1001)) + "\n",
                                   encoding="utf-8")

    try:  # a name with an escape sequence (Windows refuses control characters in names)
        (root / "docs" / "evil\x1b[31mname.md").write_text("x\n", encoding="utf-8")
    except OSError:
        pass

    (root / "notes.txt").write_text("a file with two names\n", encoding="utf-8")
    try:
        os.link(root / "notes.txt", root / "notes-again.txt")
        hard_link = True
    except OSError:
        hard_link = False

    try:
        (root / "docs" / "out").symlink_to(outside, target_is_directory=True)
        (root / "src" / "escape.py").symlink_to(outside / "secret.txt")
        links = True
    except OSError:  # Windows without the privilege to create links
        links = False
    return Built(root, outside, links, hard_link)
