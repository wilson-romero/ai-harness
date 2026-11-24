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
    scripts = [
        REPO_ROOT / "scripts" / name
        for name in ("copilot_probe.py", "copilot_discovery.py", "diag_named_lock.py")
    ]
    for path in [REPO_ROOT / "main.py", *scripts, *sorted((REPO_ROOT / "harness").rglob("*.py"))]:
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative.startswith(EXEMPT):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if PLATFORM_CONDITIONAL.search(line):
                offenders.append(f"{relative}:{number}: {line.strip()}")
    assert offenders == []
