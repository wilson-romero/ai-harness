"""What passes on one platform must be the same code that runs on the other.

Product code may not branch on the platform. Enterprise Architect, which is Windows-only by
nature, lives in its own package and is the single exception.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PLATFORM_CONDITIONAL = re.compile(
    r"\bsys\.platform\b|\bos\.name\b|\bplatform\.system\b|\bimport (msvcrt|fcntl|winreg)\b"
)
EXEMPT = ("harness/enterprise_architect/",)


def test_product_code_has_no_platform_branches():
    offenders = []
    for path in [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "harness").rglob("*.py"))]:
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative.startswith(EXEMPT):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if PLATFORM_CONDITIONAL.search(line):
                offenders.append(f"{relative}:{number}: {line.strip()}")
    assert offenders == []


POSIX_ONLY_PROGRAM = re.compile(r'''["']command["']\s*:\s*\[\s*["']/''')


def test_tests_do_not_declare_posix_only_program_paths():
    """A server command written as "/opt/..." validates on POSIX and fails on Windows.

    It broke the collection of two test modules on Windows (v0.2.0), so the whole suite
    did not run there. Tests take an absolute program from `sys.executable` instead. The
    one place that passes such a literal on purpose sends it as a tool ARGUMENT that must
    be refused, never as an allowlist entry, and is listed here.
    """
    allowed = {"tests/integration/test_mcp_cli.py"}
    offenders = []
    for path in sorted((REPO_ROOT / "tests").rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative in allowed or relative == "tests/unit/test_portability.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if POSIX_ONLY_PROGRAM.search(line):
                offenders.append(f"{relative}:{number}: {line.strip()}")
    assert offenders == []


# -- every data descriptor is binary (hotfix 0.2.1) --------------------------------------------
#
# On Windows a descriptor from `os.open` without O_BINARY is in text mode: every b"\n" written
# becomes b"\r\n" and the bytes read back differ. It damaged one MCP argument key in about
# eight (v0.2.0). Every `os.open` in the product and its scripts must carry
# `getattr(os, "O_BINARY", 0)`, directly or through a name assigned that expression in the
# same function or module.
#
# Allowed without the flag: a descriptor on `os.devnull`. Nothing written there is kept, read
# back or compared, so a newline translation cannot change any result.

BINARY_SOURCES = ("main.py", "harness", "scripts")


def _is_binary_flag(node) -> bool:
    import ast

    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "os"
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "O_BINARY"
    )


def _carries_binary(expr, scopes) -> bool:
    import ast

    if any(_is_binary_flag(node) for node in ast.walk(expr)):
        return True
    if isinstance(expr, ast.Name):
        for scope in scopes:
            values = [
                node.value
                for node in ast.walk(scope)
                if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == expr.id for t in node.targets)
            ]
            if values:
                return all(_carries_binary(value, ()) for value in values)
    return False


def os_open_without_binary(source: str, label: str) -> list[str]:
    """Every `os.open(...)` in `source` whose flags do not carry O_BINARY."""
    import ast

    tree = ast.parse(source)
    offenders = []

    def visit(node, scopes):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            scopes = (node, *scopes)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "open"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
        ):
            target = node.args[0] if node.args else None
            on_devnull = (
                isinstance(target, ast.Attribute)
                and target.attr == "devnull"
                and isinstance(target.value, ast.Name)
                and target.value.id == "os"
            )
            flags = node.args[1] if len(node.args) > 1 else next(
                (k.value for k in node.keywords if k.arg == "flags"), None
            )
            if not on_devnull and (flags is None or not _carries_binary(flags, scopes)):
                offenders.append(f"{label}:{node.lineno}: {ast.unparse(node)}")
        for child in ast.iter_child_nodes(node):
            visit(child, scopes)

    visit(tree, (tree,))
    return offenders


def _binary_source_files() -> list[Path]:
    files = []
    for name in BINARY_SOURCES:
        path = REPO_ROOT / name
        files.extend([path] if path.is_file() else sorted(path.rglob("*.py")))
    return files


def test_every_os_open_in_the_product_and_scripts_is_binary():
    offenders = []
    files = _binary_source_files()
    for path in files:
        label = path.relative_to(REPO_ROOT).as_posix()
        offenders += os_open_without_binary(path.read_text(encoding="utf-8"), label)
    assert len(files) > 50  # the walk really covered the tree
    assert offenders == []


def test_the_binary_oracle_flags_what_it_must():
    flagged = os_open_without_binary(
        "import os\n"
        "def a(p):\n    return os.open(p, os.O_WRONLY | os.O_CREAT, 0o600)\n"
        "def b(p):\n    flags = os.O_RDONLY\n    return os.open(p, flags)\n"
        "def c(p):\n    return os.open(p, flags=os.O_RDONLY)\n",
        "sample",
    )
    assert [line.split(":")[1] for line in flagged] == ["3", "6", "8"]
    passed = os_open_without_binary(
        "import os\n"
        "FLAGS = os.O_WRONLY | getattr(os, 'O_BINARY', 0)\n"
        "def a(p):\n    return os.open(p, os.O_RDONLY | getattr(os, 'O_BINARY', 0))\n"
        "def b(p):\n    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0)\n    return os.open(p, flags)\n"
        "def c(p):\n    return os.open(p, FLAGS, 0o644)\n"
        "def d():\n    return os.open(os.devnull, os.O_WRONLY)\n",
        "sample",
    )
    assert passed == []
