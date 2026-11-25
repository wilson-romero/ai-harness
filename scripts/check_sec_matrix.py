#!/usr/bin/env python3
"""Check that the SEC matrix only cites what exists.

Usage:
    python scripts/check_sec_matrix.py                       # the repository's matrix
    python scripts/check_sec_matrix.py --matrix PATH --root PATH [--collected FILE]

It fails (exit code 1) unless `docs/security/sec-matrix.md`:

- has exactly the sections SEC-01 to SEC-15, in order, each with every field;
- gives each one a state from the closed list, at least one test when the state is `cubierto`
  or `parcial`, and a reason when it is `pendiente de merge`, `no cubierto` or `BLOCKED`;
- cites only pytest node ids that `pytest --collect-only -q` collects today;
- cites only requirements that exist, by name, in the named spec under `openspec/`.

It also checks that every pytest node id cited in the known-debt list is collected, and that
every relative link of the security documents, `README.md` and `SECURITY.md` points to a file
that exists.

What it does NOT check: that a cited test proves what the matrix says. That is the job of the
review of the document and of the negative control each row cites (hardening design D2).

Standard library only. Text is read as UTF-8 with universal newlines, so a checkout with CRLF
line endings gives the same result.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MATRIX = Path("docs") / "security" / "sec-matrix.md"
# Documents whose pytest node ids must be collected (besides the matrix).
CITING_DOCS = (Path("docs") / "security" / "known-debt.md",)
# Documents whose relative links must resolve.
LINKED_DOCS = (
    Path("README.md"),
    Path("SECURITY.md"),
    Path("docs") / "security" / "sec-matrix.md",
    Path("docs") / "security" / "known-debt.md",
)

ROW_IDS = tuple(f"SEC-{n:02d}" for n in range(1, 16))
STATES = ("cubierto", "parcial", "pendiente de merge", "no cubierto", "BLOCKED")
NEEDS_TESTS = ("cubierto", "parcial")
NEEDS_REASON = ("pendiente de merge", "no cubierto", "BLOCKED")
FIELDS = ("Propiedad", "Estado", "Requisitos", "Tests", "Control negativo", "Windows",
          "Límites")
LIST_FIELDS = ("Requisitos", "Tests")
REASON_FIELD = "Motivo"
NONE_MARK = "—"
COLLECT_TIMEOUT_S = 120

SEC_HEADING = re.compile(r"^## (SEC-\d+)\b(.*)$")
ANY_H2 = re.compile(r"^#{1,2} ")
FIELD_LINE = re.compile(r"^\*\*([^*]+):\*\*\s*(.*)$")
BULLET = re.compile(r"^- (.*)$")
TEST_ID = re.compile(r"^tests/[A-Za-z0-9_/]+\.py::[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)?$")
TEST_ID_IN_TEXT = re.compile(r"tests/[A-Za-z0-9_/]+\.py::[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)?")
REQUIREMENT_SEPARATOR = " · "
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


class CollectError(Exception):
    """The test collection could not be obtained: the check cannot say PASS."""


@dataclass
class Row:
    sec: str
    heading: str
    fields: dict[str, str] = field(default_factory=dict)
    lists: dict[str, list[str]] = field(default_factory=dict)


def read_text(path: Path) -> str:
    """UTF-8 with universal newlines: CRLF and LF checkouts read the same."""
    return path.read_text(encoding="utf-8", newline=None)


def parse_matrix(text: str) -> tuple[list[Row], list[str]]:
    """The SEC sections in document order, and the format problems found while reading."""
    rows: list[Row] = []
    problems: list[str] = []
    current: Row | None = None
    open_list: str | None = None
    for raw in text.split("\n"):
        line = raw.rstrip()
        heading = SEC_HEADING.match(line)
        if heading:
            current = Row(heading.group(1), line[3:].strip())
            rows.append(current)
            open_list = None
            continue
        if ANY_H2.match(line):
            current, open_list = None, None
            continue
        if current is None:
            continue
        found = FIELD_LINE.match(line)
        if found:
            name, value = found.group(1).strip(), found.group(2).strip()
            if name in current.fields:
                problems.append(f"{current.sec}: field {name!r} appears twice")
            current.fields[name] = value
            open_list = name if name in LIST_FIELDS else None
            if open_list is not None:
                current.lists[name] = []
                if value and value != NONE_MARK:
                    problems.append(f"{current.sec}: {name} must be a list of '- ' lines "
                                    f"or {NONE_MARK}")
            continue
        bullet = BULLET.match(line)
        if bullet and open_list is not None:
            item = bullet.group(1).strip()
            if item != NONE_MARK:
                current.lists[open_list].append(item)
            continue
        if line.strip() and not line.startswith(" "):
            open_list = None
    return rows, problems


def strip_ticks(text: str) -> str:
    return text.strip().strip("`").strip()


def check_rows(rows: list[Row]) -> list[str]:
    problems: list[str] = []
    found = [row.sec for row in rows]
    for sec in ROW_IDS:
        if sec not in found:
            problems.append(f"{sec}: row missing")
    for sec in found:
        if sec not in ROW_IDS:
            problems.append(f"{sec}: not a row of the matrix (SEC-01 to SEC-15 only)")
    duplicates = sorted({sec for sec in found if found.count(sec) > 1})
    for sec in duplicates:
        problems.append(f"{sec}: row appears more than once")
    known = [sec for sec in found if sec in ROW_IDS]
    if not duplicates and known != sorted(known):
        problems.append(f"rows out of order: {', '.join(known)}")
    for row in rows:
        for name in FIELDS:
            if name not in row.fields:
                problems.append(f"{row.sec}: field {name!r} missing")
            elif name not in LIST_FIELDS and not row.fields[name]:
                problems.append(f"{row.sec}: field {name!r} is empty")
        state = row.fields.get("Estado")
        if state is not None and state not in STATES:
            problems.append(f"{row.sec}: unknown state {state!r} (one of: {', '.join(STATES)})")
        if state in NEEDS_TESTS and not row.lists.get("Tests"):
            problems.append(f"{row.sec}: state {state!r} needs at least one test")
        if state in NEEDS_REASON and not row.fields.get(REASON_FIELD):
            problems.append(f"{row.sec}: state {state!r} needs a {REASON_FIELD!r} line")
        for item in row.lists.get("Tests", []):
            if not TEST_ID.match(strip_ticks(item)):
                problems.append(f"{row.sec}: not a pytest node id: {item!r}")
    return problems


def is_collected(test_id: str, collected: set[str]) -> bool:
    """The id itself, or a parametrised case of it (`id[...]`)."""
    if test_id in collected:
        return True
    return any(item.startswith(test_id + "[") for item in collected)


def check_tests(rows: list[Row], collected: set[str]) -> list[str]:
    problems = []
    for row in rows:
        for item in row.lists.get("Tests", []):
            test_id = strip_ticks(item)
            if TEST_ID.match(test_id) and not is_collected(test_id, collected):
                problems.append(f"{row.sec}: test not collected by pytest: {test_id}")
    return problems


def check_requirements(rows: list[Row], root: Path) -> list[str]:
    problems = []
    for row in rows:
        for item in row.lists.get("Requisitos", []):
            path_text, separator, name = item.partition(REQUIREMENT_SEPARATOR)
            path_text, name = strip_ticks(path_text), name.strip()
            if not separator or not name:
                problems.append(f"{row.sec}: requirement must be '`<spec path>`"
                                f"{REQUIREMENT_SEPARATOR}<name>': {item!r}")
                continue
            if not path_text.startswith("openspec/") or ".." in path_text.split("/"):
                problems.append(f"{row.sec}: spec path outside openspec/: {path_text}")
                continue
            spec = root / Path(*path_text.split("/"))
            if not spec.is_file():
                problems.append(f"{row.sec}: spec not found: {path_text}")
                continue
            headings = {line.strip() for line in read_text(spec).split("\n")}
            if f"### Requirement: {name}" not in headings:
                problems.append(f"{row.sec}: requirement {name!r} not in {path_text}")
    return problems


def check_cited_ids(doc: Path, label: str, collected: set[str]) -> list[str]:
    if not doc.is_file():
        return [f"{label}: document not found"]
    ids = sorted(set(TEST_ID_IN_TEXT.findall(read_text(doc))))
    return [f"{label}: test not collected by pytest: {test_id}"
            for test_id in ids if not is_collected(test_id, collected)]


def check_links(doc: Path, label: str) -> list[str]:
    if not doc.is_file():
        return []  # a document that does not exist has no links (a link TO it is checked)
    problems = []
    for target in LINK.findall(read_text(doc)):
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue  # a URL or an anchor in the same document
        relative = target.split("#", 1)[0]
        if not relative:
            continue
        if not (doc.parent / Path(*relative.split("/"))).exists():
            problems.append(f"{label}: broken link: {target}")
    return problems


def collect_ids(root: Path, timeout_s: float = COLLECT_TIMEOUT_S) -> set[str]:
    """The node ids `pytest --collect-only -q` prints, run under `root` with a deadline.

    The output goes to a file, not a pipe, so a large collection can never block the child; on
    the deadline the child is killed. A failed or late collection raises CollectError.
    """
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "collect.txt"
        with open(output, "wb") as sink:
            try:
                completed = subprocess.run(
                    [sys.executable, "-m", "pytest", "--collect-only", "-q",
                     "-p", "no:cacheprovider"],
                    cwd=root, stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT,
                    timeout=timeout_s, check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise CollectError(f"pytest --collect-only did not finish in {timeout_s} s") from exc
            except OSError as exc:
                raise CollectError(f"pytest --collect-only could not start: {exc}") from exc
        text = output.read_bytes().decode("utf-8", errors="replace")
    if completed.returncode != 0:
        tail = " | ".join(line for line in text.splitlines()[-5:] if line.strip())
        raise CollectError(f"pytest --collect-only exited {completed.returncode}: {tail}")
    return parse_collected(text)


def parse_collected(text: str) -> set[str]:
    """One node id per line; the summary and warnings are not ids (they have no `::` or start
    with a space)."""
    return {line.rstrip() for line in text.splitlines()
            if "::" in line and line[:1] not in ("", " ", "\t")}


def run(matrix: Path, root: Path, collected: set[str] | None) -> tuple[list[str], int, int]:
    """Problems, number of rows and number of distinct tests cited."""
    if not matrix.is_file():
        return [f"matrix not found: {matrix}"], 0, 0
    rows, problems = parse_matrix(read_text(matrix))
    problems += check_rows(rows)
    problems += check_requirements(rows, root)
    if collected is None:
        try:
            collected = collect_ids(root)
        except CollectError as exc:
            return [*problems, str(exc)], len(rows), 0
    problems += check_tests(rows, collected)
    for doc in CITING_DOCS:
        problems += check_cited_ids(root / doc, doc.as_posix(), collected)
    for doc in LINKED_DOCS:
        problems += check_links(root / doc, doc.as_posix())
    tests = {strip_ticks(item) for row in rows for item in row.lists.get("Tests", [])}
    return problems, len(rows), len(tests)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=REPO_ROOT,
                        help="repository root (default: this script's repository)")
    parser.add_argument("--matrix", type=Path, default=None,
                        help=f"matrix file (default: <root>/{MATRIX.as_posix()})")
    parser.add_argument("--collected", type=Path, default=None,
                        help="a file with the output of `pytest --collect-only -q` to use "
                             "instead of running it (tests of this script)")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    matrix = args.matrix if args.matrix is not None else root / MATRIX
    collected = None
    if args.collected is not None:
        collected = parse_collected(args.collected.read_bytes().decode("utf-8", errors="replace"))
    problems, rows, tests = run(matrix, root, collected)
    if problems:
        for problem in problems:
            print(f"sec-matrix: {problem}", file=sys.stderr)
        print(f"sec-matrix: FAIL ({len(problems)} problem(s))", file=sys.stderr)
        return 1
    print(f"sec-matrix: PASS ({rows} rows, {tests} tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
