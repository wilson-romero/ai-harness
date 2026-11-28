#!/usr/bin/env python3
"""Check that the SEC matrix only cites what exists.

Usage:
    python scripts/check_sec_matrix.py                       # the repository's matrix
    python scripts/check_sec_matrix.py --matrix PATH --root PATH [--collected FILE]

It fails (exit code 1) unless `docs/security/sec-matrix.md`:

- has exactly the sections SEC-01 to SEC-15, in order, each with every field;
- gives each one a state from the closed list, at least one test when the state is `cubierto`
  or `parcial`, and a reason when it is `pendiente de merge`, `no cubierto` or `BLOCKED`;
- gives each row the state pinned for it in `docs/security/sec-states.json`, so that a state
  change needs two edits (the row and the pin) and shows in two places of the diff;
- cites each test at most once per row;
- cites only pytest node ids that `pytest --collect-only -q` collects today, anywhere in the
  document (the `Tests` lists, the mutation table, the negative controls, the limits). An id
  with a parametrised case (`file::test[case]`) must be collected exactly; an id without one
  stands for the function and is satisfied by any of its cases;
- never cites a test marked `skip` or `xfail` (or that calls `pytest.xfail`), and, when a cited
  test can be skipped (`skipif`, a `pytest.skip` call in the test, in a helper or in a fixture
  of the test module or of `tests/*.py`), says so in the row's `Windows` field ("omite");
- cites only requirements that exist, by name, in the named spec under `openspec/`.

It also checks that every pytest node id cited in the known-debt list is collected, and that
every relative link of the security documents, `README.md` and `SECURITY.md` points to a file
that exists.

What it does NOT check (written limits):
- that a cited test proves what the matrix says: replacing the tests of a row by an unrelated
  test that exists passes. That is the job of the review of the document, of the negative
  control each row cites and of the mutation table (hardening design D2);
- a test cited by its function whose individual cases are deleted, as long as one remains;
- a skip decided at run time by code outside the test module and `tests/*.py`, or a mark
  attached through `pytest.param(..., marks=...)`.

Standard library, plus the harness's bounded child process for the collection
(`harness.mcp.client.run_bounded`). Text is read as UTF-8 with universal newlines, so a checkout with CRLF
line endings gives the same result.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from harness.mcp.client import run_bounded  # noqa: E402 - the same kill scope as MCP sessions

MATRIX = Path("docs") / "security" / "sec-matrix.md"
STATES_PIN = Path("docs") / "security" / "sec-states.json"
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
# How the collection is run: `sys.executable` followed by these (a test replaces them with a
# stand-in whose child outlives it).
COLLECT_ARGS = ["-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"]

SEC_HEADING = re.compile(r"^## (SEC-\d+)\b(.*)$")
ANY_H2 = re.compile(r"^#{1,2} ")
FIELD_LINE = re.compile(r"^\*\*([^*]+):\*\*\s*(.*)$")
BULLET = re.compile(r"^- (.*)$")
_ID = r"tests/[A-Za-z0-9_/]+\.py::[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)?(?:\[[^\]\n`]+\])?"
TEST_ID = re.compile(rf"^{_ID}$")
TEST_ID_IN_TEXT = re.compile(_ID)
SKIP_WORD = "omit"  # "omite", "omiten", "omitido": the Windows field says what is skipped
REQUIREMENT_SEPARATOR = " · "
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1")


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
        cited = [strip_ticks(item) for item in row.lists.get("Tests", [])]
        for item in cited:
            if not TEST_ID.match(item):
                problems.append(f"{row.sec}: not a pytest node id: {item!r}")
        for item in sorted({item for item in cited if cited.count(item) > 1}):
            problems.append(f"{row.sec}: test cited more than once: {item}")
    return problems


def check_pinned_states(rows: list[Row], pin: Path) -> list[str]:
    """Each row's state must be the one pinned in the data file, and the file must pin
    exactly the 15 rows."""
    if not pin.is_file():
        return [f"state pin not found: {STATES_PIN.as_posix()}"]
    try:
        pinned = json.loads(read_text(pin))
    except ValueError as exc:
        return [f"{STATES_PIN.as_posix()}: not valid JSON: {exc}"]
    if not isinstance(pinned, dict) or sorted(pinned) != list(ROW_IDS):
        return [f"{STATES_PIN.as_posix()}: must map exactly SEC-01 to SEC-15 to a state"]
    problems = []
    for row in rows:
        state = row.fields.get("Estado")
        if row.sec in pinned and state is not None and state != pinned[row.sec]:
            problems.append(f"{row.sec}: state {state!r} differs from the pinned "
                            f"{pinned[row.sec]!r} in {STATES_PIN.as_posix()}")
    return problems


def is_collected(test_id: str, collected: set[str]) -> bool:
    """An id with a case must be collected exactly (no collected id starts with `id[case][`);
    one without stands for the function and is satisfied by any of its cases (`id[...]`)."""
    if test_id in collected:
        return True
    return any(item.startswith(test_id + "[") for item in collected)


# -- skip and xfail ---------------------------------------------------------------------------

def _dotted(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - an odd node is simply not a mark
        return ""


def _mark_kind(expression: ast.AST) -> str | None:
    """`never` for skip/xfail marks, `maybe` for skipif, None otherwise."""
    text = _dotted(expression.func if isinstance(expression, ast.Call) else expression)
    if text.endswith(("mark.xfail", "mark.skip")):
        return "never"
    if text.endswith("mark.skipif"):
        return "maybe"
    return None


def _calls(function: ast.AST) -> set[str]:
    return {_dotted(node.func) for node in ast.walk(function) if isinstance(node, ast.Call)}


def _functions(tree: ast.AST) -> dict[str, ast.AST]:
    return {node.name: node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(read_text(path))
    except (OSError, SyntaxError, ValueError):
        return None


def _skipping_helpers(root: Path, tree: ast.AST) -> set[str]:
    """Names of the functions and fixtures, in the test module and in `tests/*.py`, that can
    skip: they call `pytest.skip`, call one that can, or take one as a fixture."""
    functions: dict[str, ast.AST] = {}
    for path in sorted((root / "tests").glob("*.py")):
        other = _parse(path)
        if other is not None:
            functions.update(_functions(other))
    functions.update(_functions(tree))
    skippers: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, function in functions.items():
            if name in skippers:
                continue
            calls = _calls(function)
            short = {call.split(".")[-1] for call in calls}
            arguments = {arg.arg for arg in function.args.args}
            if "pytest.skip" in calls or short & skippers or arguments & skippers:
                skippers.add(name)
                changed = True
    return skippers


def skip_kind(root: Path, test_id: str) -> str | None:
    """`never` if the cited test can never pass (skip/xfail mark, `pytest.xfail`), `maybe` if
    it can be skipped, None if not, or if its source cannot be read."""
    file_part, _, rest = test_id.partition("::")
    name = rest.split("[", 1)[0].split("::")[-1]
    tree = _parse(root / Path(*file_part.split("/")))
    if tree is None:
        return None
    function = _functions(tree).get(name)
    if function is None:
        return None
    kinds = {_mark_kind(d) for d in function.decorator_list}
    for node in tree.body:  # pytestmark = pytest.mark.skip(...) or a list of marks
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "pytestmark"
                for target in node.targets):
            values = (node.value.elts if isinstance(node.value, (ast.List, ast.Tuple))
                      else [node.value])
            kinds |= {_mark_kind(value) for value in values}
    calls = _calls(function)
    if "pytest.xfail" in calls:
        kinds.add("never")
    if "never" in kinds:
        return "never"
    skippers = _skipping_helpers(root, tree)
    short = {call.split(".")[-1] for call in calls}
    arguments = {arg.arg for arg in function.args.args}
    if "maybe" in kinds or "pytest.skip" in calls or short & skippers or arguments & skippers:
        return "maybe"
    return None


def check_skips(rows: list[Row], root: Path) -> list[str]:
    problems = []
    for row in rows:
        says_skipped = SKIP_WORD in row.fields.get("Windows", "").lower()
        for item in row.lists.get("Tests", []):
            test_id = strip_ticks(item)
            kind = skip_kind(root, test_id)
            if kind == "never":
                problems.append(f"{row.sec}: cited test is marked skip or xfail: {test_id}")
            elif kind == "maybe" and not says_skipped:
                problems.append(f"{row.sec}: cited test can be skipped and the Windows field "
                                f"does not say what is omitted: {test_id}")
    return problems


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


def without_code(text: str) -> str:
    """The text without fenced blocks and inline code spans: a link written as code is an
    example, not a link."""
    kept, fenced = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if not fenced:
            kept.append(INLINE_CODE.sub("", line))
    return "\n".join(kept)


def check_links(doc: Path, label: str) -> list[str]:
    if not doc.is_file():
        return []  # a document that does not exist has no links (a link TO it is checked)
    problems = []
    for target in LINK.findall(without_code(read_text(doc))):
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

    The child runs in its own kill scope and its output is read from a pipe while it runs
    (`harness.mcp.client.run_bounded`, the MCP session process's mechanism): it can never block
    on a full pipe, and nothing is written to disk that a surviving descendant could keep open.
    On the deadline its whole tree is ended. A failed or late collection raises CollectError.
    """
    try:
        run = run_bounded([sys.executable, *COLLECT_ARGS], cwd=root, deadline_s=timeout_s,
                          end_tree_on_exit=True)
    except OSError as exc:
        raise CollectError(f"pytest --collect-only could not start: {exc}") from exc
    if run.returncode is None:
        raise CollectError(f"pytest --collect-only did not finish in {timeout_s} s")
    text = run.output.decode("utf-8", errors="replace")
    if run.returncode != 0:
        said = text + "\n" + run.errors.decode("utf-8", errors="replace")
        tail = " | ".join(line for line in said.splitlines()[-5:] if line.strip())
        raise CollectError(f"pytest --collect-only exited {run.returncode}: {tail}")
    if run.truncated:
        raise CollectError("pytest --collect-only printed more than the check reads")
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
    problems += [problem.replace("test not collected", "test cited in the text not collected")
                 for problem in check_cited_ids(matrix, MATRIX.as_posix(), collected)]
    problems += check_pinned_states(rows, root / STATES_PIN)
    problems += check_skips(rows, root)
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
