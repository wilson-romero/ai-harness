"""Demo of the hardening change: the SEC matrix is checked, and the check says NO when the
matrix rots.

Usage: uv run python scripts/demo_hardening.py

Standard library only; same code on every platform. The matrix is copied to a temporary
directory before it is broken: the repository is never touched.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from demo_common import ROOT, check, header, run, step

import check_sec_matrix as checker

RENAMED = "tests/unit/test_skill_approval.py::test_approval_reused"


def demo() -> list[str]:
    header()

    step("(a) the matrix of the repository passes the check")
    result = subprocess.run(
        [sys.executable, "scripts/check_sec_matrix.py"], cwd=ROOT, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    sys.stdout.write(result.stdout + result.stderr)
    check(result.returncode == 0 and "sec-matrix: PASS (15 rows," in result.stdout,
          "the matrix of the repository does not pass")

    step("(b) rows by state")
    text = checker.read_text(ROOT / checker.MATRIX)
    rows, problems = checker.parse_matrix(text)
    check(not problems, f"format problems: {problems}")
    states = Counter(row.fields.get("Estado") for row in rows)
    for state in checker.STATES:
        names = ", ".join(row.sec for row in rows if row.fields.get("Estado") == state)
        print(f"{state}: {states.get(state, 0)}" + (f" ({names})" if names else ""))
    check(sum(states.values()) == 15, "the matrix does not have 15 rows")

    collected = checker.collect_ids(ROOT)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work:
        copy = Path(work) / "sec-matrix.md"

        step("(c) the citation of a test renamed in a copy of the matrix (the test is "
             "untouched): the check says NO")
        check(RENAMED in text, f"the matrix no longer cites {RENAMED}")
        copy.write_text(text.replace(RENAMED, RENAMED + "_renamed"), encoding="utf-8",
                        newline="\n")
        problems, _, _ = checker.run(copy, ROOT, collected)
        print("\n".join(problems))
        check(any(p.startswith("SEC-12: test not collected") for p in problems),
              "a citation of a test that does not exist was not reported")

        step("(d) a state outside the closed list in a copy: the check says NO")
        copy.write_text(text.replace("**Estado:** cubierto", "**Estado:** casi", 1),
                        encoding="utf-8", newline="\n")
        problems, _, _ = checker.run(copy, ROOT, collected)
        print("\n".join(problems))
        check(any("unknown state 'casi'" in p for p in problems),
              "an unknown state was not reported")

        step("(e) a state changed in a copy but not in sec-states.json: the check says NO")
        copy.write_text(text.replace("**Estado:** parcial", "**Estado:** cubierto", 1),
                        encoding="utf-8", newline="\n")
        problems, _, _ = checker.run(copy, ROOT, collected)
        print("\n".join(problems))
        check(any("differs from the pinned 'parcial'" in p for p in problems),
              "a state flipped without its pin was not reported")

        step("(f) the same matrix with CRLF line endings still passes")
        copy.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        problems, rows_seen, _ = checker.run(copy, ROOT, collected)
        check(not problems and rows_seen == 15, f"CRLF changed the result: {problems}")
        print("sec-matrix: PASS with CRLF")
    return []


if __name__ == "__main__":
    sys.exit(run(demo))
