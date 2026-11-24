"""SEC-13 and D9: the memory code has no way to copy, upload or write the vault."""

import re
from pathlib import Path

from tests.conftest import REPO_ROOT, fingerprint

MEMORY_PACKAGE = REPO_ROOT / "harness" / "memory"
FORBIDDEN = re.compile(
    r"\bshutil\.(copy\w*|move|rmtree)\b"
    r"|^\s*(import|from)\s+(subprocess|urllib|http|socket|requests|ftplib|smtplib)\b"
    r"|\bopen\([^)]*['\"][^'\"]*[wax+][^'\"]*['\"]"
    r"|\.(write_text|write_bytes|unlink|mkdir|rmdir|touch|symlink_to|hardlink_to|chmod)\("
    # Path.rename/replace take a path; str.replace takes a literal, which is not flagged.
    r"|\.(rename|replace)\((?![\"'])"
    r"|\bos\.(remove|unlink|rename|replace|makedirs|mkdir|rmdir|link|symlink|chmod|utime)\("
)


def test_memory_package_has_no_copy_upload_or_write_path():
    offenders = []
    for path in sorted(MEMORY_PACKAGE.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if FORBIDDEN.search(line):
                relative = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{relative}:{number}: {line.strip()}")
    assert offenders == []


def test_the_grep_says_no_to_each_forbidden_form():
    samples = [
        "shutil.copytree(root, target)",
        "import subprocess",
        "from urllib import request",
        "import socket",
        "with open(path, 'w') as handle:",
        'open(path, "ab")',
        "note.write_text(text)",
        "os.replace(tmp, path)",
        "path.unlink()",
        "tmp.replace(path)",
    ]
    assert all(FORBIDDEN.search(sample) for sample in samples)
    assert not FORBIDDEN.search("raw = file.path.read_bytes()")
    assert not FORBIDDEN.search("open(path, 'rb')")
    assert not FORBIDDEN.search('text.replace("\\r\\n", "\\n")')


def _outside_data(tmp_path: Path, data_dir: Path) -> dict[str, tuple]:
    prints = fingerprint(tmp_path)
    data = data_dir.relative_to(tmp_path).as_posix()
    return {k: v for k, v in prints.items() if k != data and not k.startswith(data + "/")}


def test_no_memory_command_writes_outside_the_data_dir(cli, vault, tmp_path, data_dir):
    env = {"HARNESS_VAULT_ROOT": str(vault)}
    session_id = cli("session", "create", "Huella", "--project", "demo-alpha")[1].strip()
    vault_before = fingerprint(vault)
    tree_before = _outside_data(tmp_path, data_dir)
    assert vault_before and tree_before

    commands = [
        ("memory", "search", "orquestador"),
        ("memory", "search", "latencia", "--project", "demo-alpha"),
        ("memory", "context", "demo-alpha"),
        ("memory", "maintain", "--dry-run"),
        ("ask", session_id, "Resume el contexto", "--project", "demo-alpha"),
    ]
    for command in commands:
        code, _, err = cli(*command, **env)
        assert code == 0, (command, err)
        assert fingerprint(vault) == vault_before, command
        assert _outside_data(tmp_path, data_dir) == tree_before, command
