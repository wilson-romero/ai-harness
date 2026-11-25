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
