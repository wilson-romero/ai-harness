"""SEC-13 and D9: the memory code has no way to copy, upload or write the vault.

The structural oracle is an allowlist over the syntax tree of `harness/memory/`, not a list of
forbidden text: a primitive that nobody thought to forbid is refused because nobody allowed it.
What it proves: the package imports only the modules below; from `os` it uses only read and
walk functions and read-only flags; `open`/`os.open`/`.open` appear only in read mode; and no
method that writes, moves or deletes a file is called. What it does not prove: what code
outside `harness/memory/` does (the CLI and the service write SQLite in the data directory) or
what a module from the allowlist could do through an object passed in from outside. The second
oracle, the fingerprint of the vault around every command, covers behaviour end to end.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT, fingerprint

MEMORY_PACKAGE = REPO_ROOT / "harness" / "memory"
# The sanitising and redaction it uses moved to a neutral package (mcp-gateway D7); the same
# allowlist still applies to them.
TEXT_PACKAGE = REPO_ROOT / "harness" / "text"

ALLOWED_MODULES = {
    "__future__",
    "collections",
    "collections.abc",
    "dataclasses",
    "datetime",
    "difflib",
    "hashlib",
    "os",
    "pathlib",
    "re",
    "secrets",
    "stat",
    "typing",
    "unicodedata",
    "harness.core.errors",
}
ALLOWED_PREFIXES = ("harness.memory.", "harness.text.")
READ_FLAGS = {"O_RDONLY", "O_NONBLOCK", "O_BINARY", "O_NOINHERIT", "O_CLOEXEC"}
OS_ALLOWED = {"walk", "listdir", "open", "fstat", "read", "close", "path", *READ_FLAGS}
OS_PATH_ALLOWED = {"samefile"}
WRITING_METHODS = {
    "write_text", "write_bytes", "write", "writelines", "unlink", "mkdir", "makedirs", "rmdir",
    "touch", "symlink_to", "hardlink_to", "chmod", "lchmod", "chown", "rename", "truncate",
    "copy", "copy2", "copyfile", "copytree", "move", "rmtree", "utime", "link", "symlink",
}
DYNAMIC = {"exec", "eval", "compile", "__import__", "setattr", "globals", "vars"}
READ_MODE_CHARS = set("rbt")


def _module_allowed(name: str) -> bool:
    return name in ALLOWED_MODULES or name.startswith(ALLOWED_PREFIXES)


def _mode_problem(call: ast.Call, position: int) -> str | None:
    """None if the call's mode is absent or a read-only constant."""
    mode = call.args[position] if len(call.args) > position else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
    if mode is None:
        return None
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return None if set(mode.value) <= READ_MODE_CHARS else f"write mode {mode.value!r}"
    return "mode that is not a constant"


def _flags_problem(expr: ast.AST, assignments: dict[str, list[ast.AST]]) -> str | None:
    """os.open flags: only read-only `os.O_*` names, `getattr(os, "O_*", 0)`, 0 and `|`."""
    if isinstance(expr, ast.BinOp):
        if not isinstance(expr.op, ast.BitOr):
            return "flags combined with something other than |"
        return _flags_problem(expr.left, assignments) or _flags_problem(expr.right, assignments)
    if isinstance(expr, ast.Attribute):
        if isinstance(expr.value, ast.Name) and expr.value.id == "os" and expr.attr in READ_FLAGS:
            return None
        return f"flag {ast.unparse(expr)}"
    if isinstance(expr, ast.Constant):
        return None if expr.value == 0 else f"flag {expr.value!r}"
    if isinstance(expr, ast.Call):
        args = expr.args
        if (
            isinstance(expr.func, ast.Name)
            and expr.func.id == "getattr"
            and not expr.keywords
            and len(args) == 3
            and isinstance(args[0], ast.Name)
            and args[0].id == "os"
            and isinstance(args[1], ast.Constant)
            and args[1].value in READ_FLAGS
            and isinstance(args[2], ast.Constant)
            and args[2].value == 0
        ):
            return None
        return f"flags from {ast.unparse(expr)}"
    if isinstance(expr, ast.Name):
        sources = assignments.get(expr.id, [])
        if not sources:
            return f"flags from {expr.id!r}, which is never assigned here"
        for source in sources:
            if problem := _flags_problem(source, assignments):
                return problem
        return None
    return f"flags from {ast.unparse(expr)}"


def check_source(source: str) -> list[str]:
    """Every use in `source` that the allowlist does not cover, as `line: reason`."""
    tree = ast.parse(source)
    assignments: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)
    problems: list[str] = []

    def flag(node: ast.AST, reason: str) -> None:
        problems.append(f"{node.lineno}: {reason}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _module_allowed(alias.name):
                    flag(node, f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level or not _module_allowed(module):
                flag(node, f"from {module} import")
            elif module == "os":
                for alias in node.names:
                    if alias.name not in OS_ALLOWED:
                        flag(node, f"from os import {alias.name}")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "os" and node.attr not in OS_ALLOWED:
                flag(node, f"os.{node.attr}")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
            inner = node.value
            if isinstance(inner.value, ast.Name) and (inner.value.id, inner.attr) == ("os", "path"):
                if node.attr not in OS_PATH_ALLOWED:
                    flag(node, f"os.path.{node.attr}")
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            if func.id in DYNAMIC:
                flag(node, f"{func.id}()")
            elif func.id == "open" and (problem := _mode_problem(node, 1)):
                flag(node, f"open() with {problem}")
            elif func.id == "getattr":
                name = node.args[1] if len(node.args) > 1 else None
                if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
                    flag(node, "getattr() with a name that is not a constant")
                elif name.value in WRITING_METHODS or (
                    isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "os"
                    and name.value not in OS_ALLOWED
                ):
                    flag(node, f"getattr(..., {name.value!r})")
        elif isinstance(func, ast.Attribute):
            owner = func.value
            if isinstance(owner, ast.Name) and owner.id == "os" and func.attr == "open":
                flags = node.args[1] if len(node.args) > 1 else None
                if flags is None:
                    flag(node, "os.open() without flags")
                elif problem := _flags_problem(flags, assignments):
                    flag(node, f"os.open() with {problem}")
            elif func.attr in WRITING_METHODS:
                flag(node, f".{func.attr}()")
            elif func.attr == "open" and (problem := _mode_problem(node, 0)):
                flag(node, f".open() with {problem}")
            elif func.attr == "replace" and len(node.args) < 2:
                # str.replace takes two arguments; Path.replace (a rename) takes one.
                flag(node, ".replace() with one argument")
    return problems


def test_memory_package_has_no_copy_upload_or_write_path():
    offenders = []
    paths = [*MEMORY_PACKAGE.rglob("*.py"), *TEXT_PACKAGE.rglob("*.py")]
    assert any(p.parent == TEXT_PACKAGE for p in paths)
    for path in sorted(paths):
        relative = path.relative_to(REPO_ROOT).as_posix()
        offenders += [f"{relative}:{p}" for p in check_source(path.read_text(encoding="utf-8"))]
    assert offenders == []


# One sample per primitive. The first ten are the ones the earlier grep did not catch.
SAYS_NO = [
    "import os\nfd = os.open(p, os.O_WRONLY | os.O_CREAT)",
    "from shutil import copyfile",
    "import sqlite3\nsqlite3.connect(p)",
    "import os\nos.system('x')",
    "import os\nos.popen('x')",
    "import asyncio\nasyncio.create_subprocess_exec('x')",
    "import httpx",
    "open(path, mode)",
    "import os\nos.truncate(p, 0)",
    "import tempfile\ntempfile.NamedTemporaryFile(dir=root)",
    # and the ones it did catch
    "import shutil\nshutil.copytree(root, target)",
    "import subprocess",
    "from urllib import request",
    "import socket",
    "with open(path, 'w') as handle:\n    pass",
    'open(path, "ab")',
    "note.write_text(text)",
    "import os\nos.replace(tmp, path)",
    "path.unlink()",
    "tmp.replace(path)",
    # and a few more ways around an allowlist
    "import os\nos.open(p, 1)",
    "import os\nflags = os.O_RDWR\nos.open(p, flags)",
    "path.open('w')",
    "getattr(path, 'write_text')(x)",
    "getattr(path, name)(x)",
    "__import__('subprocess')",
    "from . import sibling",
]


@pytest.mark.parametrize("sample", SAYS_NO)
def test_the_allowlist_says_no(sample):
    assert check_source(sample), sample


@pytest.mark.parametrize(
    "sample",
    [
        "raw = file.path.read_bytes()",
        "open(path, 'rb')",
        'text.replace("\\r\\n", "\\n")',
        "import os\nflags = os.O_RDONLY | getattr(os, 'O_BINARY', 0)\nos.open(p, flags)",
        "from harness.memory.paths import walk_vault",
    ],
)
def test_the_allowlist_says_yes(sample):
    assert check_source(sample) == []


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
