"""`scripts/check_sec_matrix.py` (hardening D2): it says PASS only for a matrix that cites what
exists, and NO to each way the matrix can rot. Synthetic matrices, specs and collections under
`tmp_path`; the real collection only in the tests that need a subprocess."""

import importlib.util
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_sec_matrix.py"
_spec = importlib.util.spec_from_file_location("check_sec_matrix_under_test", SCRIPT)
checker = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = checker
_spec.loader.exec_module(checker)

SPEC_PATH = "openspec/specs/demo-cap/spec.md"
REQUIREMENT = "Demo denegado"
TEST_A = "tests/unit/test_demo.py::test_denied"
TEST_B = "tests/unit/test_demo.py::test_param"
TEST_SKIP = "tests/unit/test_demo.py::test_always_skipped"
TEST_XFAIL = "tests/unit/test_demo.py::test_expected_to_fail"
TEST_MAYBE = "tests/unit/test_demo.py::test_skipped_on_some_systems"
TEST_HELPER = "tests/unit/test_demo.py::test_needs_a_link"
TEST_FIXTURE = "tests/unit/test_demo.py::test_needs_a_closed_folder"
TEST_DEEP = "tests/unit/test_demo.py::test_needs_a_linked_vault"
COLLECTED = "\n".join([TEST_A, f"{TEST_B}[case-1]", f"{TEST_B}[case-2]", TEST_SKIP, TEST_XFAIL,
                       TEST_MAYBE, TEST_HELPER, TEST_FIXTURE, TEST_DEEP, "",
                       "9 tests collected in 0.01s",
                       ""])
TEST_SOURCE = """import sys
import pytest

from tests.conftest import make_link


def test_denied():
    pass


@pytest.mark.parametrize("case", [1, 2])
def test_param(case):
    pass


@pytest.mark.skip(reason="never runs")
def test_always_skipped():
    pass


def test_expected_to_fail():
    pytest.xfail("known bug")


@pytest.mark.skipif(sys.platform == "x", reason="not here")
def test_skipped_on_some_systems():
    pass


def test_needs_a_link(tmp_path):
    make_link(tmp_path)


@pytest.fixture
def closed_folder(tmp_path):
    if not tmp_path.exists():
        pytest.skip("cannot close a folder here")
    return tmp_path


def test_needs_a_closed_folder(closed_folder):
    pass


@pytest.fixture
def linked_vault(tmp_path):
    make_link(tmp_path)  # two levels: the fixture calls a helper that can skip
    return tmp_path


def test_needs_a_linked_vault(linked_vault):
    pass
"""
CONFTEST_SOURCE = """import pytest


def make_link(path):
    try:
        path.symlink_to(path)
    except OSError:
        pytest.skip("cannot create links here")
"""


def pin(project: Path, **states: str) -> None:
    """Pin every row to `cubierto`, except the ones given (SEC_11="BLOCKED")."""
    import json

    pinned = {f"SEC-{n:02d}": "cubierto" for n in range(1, 16)}
    pinned.update({key.replace("_", "-"): value for key, value in states.items()})
    (project / "docs" / "security" / "sec-states.json").write_text(
        json.dumps(pinned), encoding="utf-8", newline="\n")


def section(sec: str, state: str = "cubierto", tests: tuple[str, ...] = (TEST_A,),
            requirement: str = f"`{SPEC_PATH}` · {REQUIREMENT}", reason: str | None = None,
            windows: str = "no ejecutado.", limits: str = "ninguno conocido.") -> str:
    lines = [f"## {sec} · Propiedad sintética", "",
             "**Propiedad:** algo se deniega.",
             f"**Estado:** {state}"]
    if reason is not None:
        lines.append(f"**Motivo:** {reason}")
    lines.append("**Requisitos:**")
    lines.append(f"- {requirement}" if requirement else "- —")
    lines.append("**Tests:**")
    lines += [f"- `{test}`" for test in tests] or ["- —"]
    lines += ["**Control negativo:** recibo sintético.",
              f"**Windows:** {windows}",
              f"**Límites:** {limits}", ""]
    return "\n".join(lines)


def matrix(sections: dict[str, str] | None = None, order: list[str] | None = None) -> str:
    rows = {f"SEC-{n:02d}": section(f"SEC-{n:02d}") for n in range(1, 16)}
    rows.update(sections or {})
    ids = order or list(rows)
    return "# Matriz\n\nIntro.\n\n" + "\n".join(rows[i] for i in ids if rows[i]) + \
        "\n## Deuda\n\n- algo\n"


@pytest.fixture
def project(tmp_path):
    spec = tmp_path / SPEC_PATH
    spec.parent.mkdir(parents=True)
    spec.write_text(f"# demo\n\n### Requirement: {REQUIREMENT}\n\ntexto\n",
                    encoding="utf-8", newline="\n")
    security = tmp_path / "docs" / "security"
    security.mkdir(parents=True)
    (security / "known-debt.md").write_text(f"Lo produce `{TEST_A}`.\n", encoding="utf-8",
                                            newline="\n")
    collected = tmp_path / "collected.txt"
    collected.write_text(COLLECTED, encoding="utf-8", newline="\n")
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "test_demo.py").write_text(TEST_SOURCE, encoding="utf-8",
                                                              newline="\n")
    (tmp_path / "tests" / "conftest.py").write_text(CONFTEST_SOURCE, encoding="utf-8",
                                                    newline="\n")
    pin(tmp_path)
    return tmp_path


def check(project: Path, text: str, capsys, newline: str = "\n") -> tuple[int, str]:
    path = project / "docs" / "security" / "sec-matrix.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline=newline)
    code = checker.main(["--root", str(project), "--collected", str(project / "collected.txt")])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_a_valid_matrix_passes(project, capsys):
    code, out = check(project, matrix(), capsys)
    assert code == 0, out
    assert "sec-matrix: PASS (15 rows, 1 tests)" in out


def test_a_parametrised_test_is_cited_by_its_function(project, capsys):
    code, out = check(project, matrix({"SEC-03": section("SEC-03", tests=(TEST_B,))}), capsys)
    assert code == 0, out


def test_crlf_line_endings_give_the_same_result(project, capsys):
    code, out = check(project, matrix(), capsys, newline="\r\n")
    assert code == 0, out


def test_a_missing_row(project, capsys):
    code, out = check(project, matrix({"SEC-07": ""}), capsys)
    assert code == 1 and "SEC-07: row missing" in out


def test_a_sixteenth_row(project, capsys):
    text = matrix().replace("## Deuda", section("SEC-16") + "\n## Deuda")
    code, out = check(project, text, capsys)
    assert code == 1 and "SEC-16: not a row of the matrix" in out


def test_rows_out_of_order(project, capsys):
    order = [f"SEC-{n:02d}" for n in (1, 2, 4, 3, *range(5, 16))]
    code, out = check(project, matrix(order=order), capsys)
    assert code == 1 and "rows out of order" in out


def test_an_unknown_state(project, capsys):
    code, out = check(project, matrix({"SEC-05": section("SEC-05", state="casi")}), capsys)
    assert code == 1 and "SEC-05: unknown state 'casi'" in out


def test_a_covered_row_without_tests(project, capsys):
    code, out = check(project, matrix({"SEC-02": section("SEC-02", tests=())}), capsys)
    assert code == 1 and "SEC-02: state 'cubierto' needs at least one test" in out


def test_a_test_that_does_not_exist(project, capsys):
    ghost = "tests/unit/test_ghost.py::test_nothing"
    code, out = check(project, matrix({"SEC-09": section("SEC-09", tests=(ghost,))}), capsys)
    assert code == 1 and f"SEC-09: test not collected by pytest: {ghost}" in out


def test_a_renamed_test_in_a_file_that_exists(project, capsys):
    """The file is collected (it has other tests); the function is not: still a NO."""
    renamed = "tests/unit/test_demo.py::test_denied_old_name"
    code, out = check(project, matrix({"SEC-12": section("SEC-12", tests=(renamed,))}), capsys)
    assert code == 1 and f"SEC-12: test not collected by pytest: {renamed}" in out


def test_a_prefix_of_a_test_name_is_not_that_test(project, capsys):
    prefix = "tests/unit/test_demo.py::test_den"
    code, out = check(project, matrix({"SEC-12": section("SEC-12", tests=(prefix,))}), capsys)
    assert code == 1 and "SEC-12: test not collected" in out


def test_a_spec_path_that_does_not_exist(project, capsys):
    gone = "`openspec/specs/gone/spec.md` · " + REQUIREMENT
    code, out = check(project, matrix({"SEC-04": section("SEC-04", requirement=gone)}), capsys)
    assert code == 1 and "SEC-04: spec not found: openspec/specs/gone/spec.md" in out


def test_a_renamed_requirement(project, capsys):
    renamed = f"`{SPEC_PATH}` · Demo denegado siempre"
    code, out = check(project, matrix({"SEC-13": section("SEC-13", requirement=renamed)}),
                      capsys)
    assert code == 1 and "SEC-13: requirement 'Demo denegado siempre' not in" in out


def test_a_requirement_outside_openspec(project, capsys):
    outside = "`docs/x.md` · " + REQUIREMENT
    code, out = check(project, matrix({"SEC-13": section("SEC-13", requirement=outside)}),
                      capsys)
    assert code == 1 and "SEC-13: spec path outside openspec/" in out


def test_a_blocked_row_without_a_reason(project, capsys):
    pin(project, SEC_11="BLOCKED")
    code, out = check(project, matrix({"SEC-11": section("SEC-11", state="BLOCKED", tests=())}),
                      capsys)
    assert code == 1 and "SEC-11: state 'BLOCKED' needs a 'Motivo' line" in out


def test_a_blocked_row_with_a_reason_and_no_tests_passes(project, capsys):
    pin(project, SEC_11="BLOCKED")
    row = section("SEC-11", state="BLOCKED", tests=(), requirement="", reason="EA en pausa.")
    code, out = check(project, matrix({"SEC-11": row}), capsys)
    assert code == 0, out


def test_a_missing_field(project, capsys):
    text = matrix().replace("**Límites:** ninguno conocido.", "", 1)
    code, out = check(project, text, capsys)
    assert code == 1 and "SEC-01: field 'Límites' missing" in out


def test_an_invented_id_in_the_known_debt_list(project, capsys):
    guide = project / "docs" / "security" / "known-debt.md"
    guide.write_text("Lo produce `tests/unit/test_demo.py::test_invented`.\n",
                     encoding="utf-8", newline="\n")
    code, out = check(project, matrix(), capsys)
    assert code == 1
    assert "docs/security/known-debt.md: test not collected by pytest: " \
           "tests/unit/test_demo.py::test_invented" in out


def test_a_broken_relative_link(project, capsys):
    guide = project / "docs" / "security" / "known-debt.md"
    guide.write_text(f"`{TEST_A}`; ver [la matriz](../security/no-existe.md) y "
                     "[otra](https://example.com) y [aquí](#ancla).\n"
                     "Como código: `[texto](url)` y\n```\n[bloque](tampoco.md)\n```\n",
                     encoding="utf-8", newline="\n")
    code, out = check(project, matrix(), capsys)
    assert code == 1
    assert "docs/security/known-debt.md: broken link: ../security/no-existe.md" in out
    assert "example.com" not in out and "#ancla" not in out
    assert "url" not in out and "tampoco.md" not in out  # code is an example, not a link


def test_the_collection_is_real_and_a_broken_one_is_a_failure(tmp_path, capsys):
    """Without --collected the script runs pytest; a collection error is a NO, not a PASS."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    pass\n",
                                                   encoding="utf-8", newline="\n")
    assert checker.collect_ids(tmp_path) == {"tests/test_ok.py::test_ok"}
    (tmp_path / "tests" / "test_broken.py").write_text("import no_such_module_here\n",
                                                       encoding="utf-8", newline="\n")
    with pytest.raises(checker.CollectError, match="exited"):
        checker.collect_ids(tmp_path)


def test_a_collection_past_its_deadline_is_a_failure(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_slow.py").write_text(
        "import time\ntime.sleep(30)\n\ndef test_x():\n    pass\n", encoding="utf-8",
        newline="\n")
    with pytest.raises(checker.CollectError, match="did not finish"):
        checker.collect_ids(tmp_path, timeout_s=2)


# Windows parity (hardening 9.1): in a uv environment on Windows `sys.executable` is a launcher
# that runs the real interpreter as its child; that child inherits the output handle and outlives
# a kill of the launcher by a few milliseconds. The stand-in below reproduces it on any system:
# it starts a grandchild that holds the output open and would write `survived` if not ended.
STAND_IN = """import subprocess, sys, time
from pathlib import Path
marks = Path(sys.argv[1])
subprocess.Popen([sys.executable, "-c",
                  "import sys, time; from pathlib import Path; time.sleep(4); "
                  "Path(sys.argv[1], 'survived').write_text('yes')", str(marks)],
                 stdin=subprocess.DEVNULL, stdout=sys.stdout.fileno(),
                 stderr=sys.stderr.fileno())
(marks / "ready").write_text("yes")
time.sleep(30)
"""


def empty_soon(folder: Path) -> list[Path]:
    """The folder's listing once it is empty, or after 1 s. On Windows the errors file of a
    bounded run is a named `O_TEMPORARY` file that stays listed until the last descendant that
    inherited it closes its handle, and the end of the tree waits only for the leader there."""
    for _ in range(20):
        left = list(folder.iterdir())
        if not left:
            break
        time.sleep(0.05)
    return left


@pytest.fixture
def late_child(tmp_path, monkeypatch):
    """A collection that is late and whose child outlives it; an empty temporary directory to
    see whether anything is left behind. Returns (marks folder, temporary directory)."""
    marks, scratch = tmp_path / "marks", tmp_path / "scratch"
    marks.mkdir()
    scratch.mkdir()
    script = tmp_path / "stand_in.py"
    script.write_text(STAND_IN, encoding="utf-8", newline="\n")
    monkeypatch.setattr(checker, "COLLECT_ARGS", [str(script), str(marks)])
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    return marks, scratch


def test_a_late_collection_whose_child_outlives_it_ends_the_whole_tree(late_child, tmp_path):
    marks, scratch = late_child
    with pytest.raises(checker.CollectError, match="did not finish"):
        checker.collect_ids(tmp_path, timeout_s=2)
    assert (marks / "ready").exists()  # the grandchild was started before the deadline
    time.sleep(4)  # past the moment the grandchild would have written `survived`
    assert not (marks / "survived").exists(), "a process of the collection outlived it"
    assert empty_soon(scratch) == []


def test_a_cleanup_that_fails_does_not_hide_a_late_collection(late_child, tmp_path, monkeypatch):
    """Windows refuses to delete a file another process still has open (WinError 32); the
    first removal is refused here on any system. The answer is still the late collection, and
    nothing is left in the temporary directory."""
    marks, scratch = late_child
    refused = []
    real_rmtree = shutil.rmtree

    def rmtree_refused_once(path, *args, **kwargs):  # noqa: ANN002, ANN003
        if not refused:
            refused.append(path)
            raise PermissionError(13, "simulated: the file is used by another process", path)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", rmtree_refused_once)
    with pytest.raises(checker.CollectError, match="did not finish"):
        checker.collect_ids(tmp_path, timeout_s=2)
    assert empty_soon(scratch) == []


def test_a_child_that_exits_leaving_a_descendant_returns_and_ends_it(tmp_path):
    """The bounded run returns soon after the child's exit even though a descendant keeps the
    output open, ends that descendant, and keeps only `output_limit` bytes."""
    marks = tmp_path / "marks"
    marks.mkdir()
    script = tmp_path / "exits.py"
    script.write_text(STAND_IN.replace("time.sleep(30)", "print('x' * 5000)"),
                      encoding="utf-8", newline="\n")
    started = time.monotonic()
    run = checker.run_bounded([sys.executable, str(script), str(marks)], cwd=tmp_path,
                              deadline_s=20, output_limit=1000, end_tree_on_exit=True)
    assert time.monotonic() - started < 10
    assert run.returncode == 0 and run.truncated and run.output == b"x" * 1000
    assert run.tree_ended
    time.sleep(4)
    assert not (marks / "survived").exists()


def test_without_a_deadline_a_descendant_survives_unless_asked(tmp_path):
    """What the demos need (review of windows-parity-3, finding 1): a process that `main.py`
    leaves alive must still be alive after `harness_bounded` returns, or a leak check after it
    proves nothing. By default the tree is ended only when the deadline expires."""
    marks = tmp_path / "marks"
    marks.mkdir()
    script = tmp_path / "exits.py"
    script.write_text(STAND_IN.replace("time.sleep(30)", "pass"), encoding="utf-8",
                      newline="\n")
    run = checker.run_bounded([sys.executable, str(script), str(marks)], cwd=tmp_path,
                              deadline_s=20)
    assert run.returncode == 0 and run.tree_ended is None
    for _ in range(100):  # the descendant writes `survived` 4 s after it starts
        if (marks / "survived").exists():
            break
        time.sleep(0.1)
    assert (marks / "survived").exists(), "the bounded run ended a descendant it was not asked to"


def test_main_without_collected_fails_on_a_broken_collection(project, capsys):
    (project / "tests").mkdir(exist_ok=True)
    (project / "tests" / "test_broken.py").write_text("import no_such_module_here\n",
                                                      encoding="utf-8", newline="\n")
    path = project / "docs" / "security" / "sec-matrix.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(matrix(), encoding="utf-8", newline="\n")
    code = checker.main(["--root", str(project)])
    out = capsys.readouterr()
    assert code == 1 and "PASS" not in out.out
    assert "pytest --collect-only exited" in out.err


# -- independent review of hardening (2026-11-25): holes that gave PASS -------------------------


def test_a_state_changed_without_its_pin(project, capsys):
    """A row flipped from `parcial` to `cubierto` in the document alone is a NO."""
    pin(project, SEC_04="parcial")
    code, out = check(project, matrix(), capsys)
    assert code == 1
    assert "SEC-04: state 'cubierto' differs from the pinned 'parcial'" in out
    code, out = check(project, matrix({"SEC-04": section("SEC-04", state="parcial")}), capsys)
    assert code == 0, out


def test_a_missing_or_incomplete_pin(project, capsys):
    (project / "docs" / "security" / "sec-states.json").unlink()
    code, out = check(project, matrix(), capsys)
    assert code == 1 and "state pin not found" in out
    (project / "docs" / "security" / "sec-states.json").write_text('{"SEC-01": "cubierto"}',
                                                                  encoding="utf-8")
    code, out = check(project, matrix(), capsys)
    assert code == 1 and "must map exactly SEC-01 to SEC-15" in out


def test_the_same_test_cited_twice_in_a_row(project, capsys):
    code, out = check(project, matrix({"SEC-06": section("SEC-06", tests=(TEST_A, TEST_A))}),
                      capsys)
    assert code == 1 and f"SEC-06: test cited more than once: {TEST_A}" in out


def test_a_parametrised_case_is_cited_exactly(project, capsys):
    code, out = check(project, matrix({"SEC-03": section("SEC-03", tests=(f"{TEST_B}[case-2]",))}),
                      capsys)
    assert code == 0, out
    deleted = f"{TEST_B}[case-3]"
    code, out = check(project, matrix({"SEC-03": section("SEC-03", tests=(deleted,))}), capsys)
    assert code == 1 and f"SEC-03: test not collected by pytest: {deleted}" in out


def test_an_id_in_the_text_of_the_document_is_checked(project, capsys):
    ghost = "tests/unit/test_demo.py::test_gone"
    table = f"\n## Comprobación por mutación\n\n| 01 | algo | `{ghost}` |\n"
    text = matrix().replace("## Deuda", table + "\n## Deuda")
    code, out = check(project, text, capsys)
    assert code == 1 and f"test cited in the text not collected by pytest: {ghost}" in out
    in_limits = section("SEC-08", limits=f"lo prueba a medias `{ghost}[x]`.")
    code, out = check(project, matrix({"SEC-08": in_limits}), capsys)
    assert code == 1 and f"{ghost}[x]" in out


@pytest.mark.parametrize("test_id", [TEST_SKIP, TEST_XFAIL])
def test_a_test_that_never_runs_cannot_be_cited(project, capsys, test_id):
    row = section("SEC-10", tests=(test_id,), windows="se omite en Windows.")
    code, out = check(project, matrix({"SEC-10": row}), capsys)
    assert code == 1 and f"SEC-10: cited test is marked skip or xfail: {test_id}" in out


@pytest.mark.parametrize("test_id", [TEST_MAYBE, TEST_HELPER, TEST_FIXTURE, TEST_DEEP])
def test_a_test_that_can_be_skipped_needs_the_windows_field_to_say_so(project, capsys, test_id):
    code, out = check(project, matrix({"SEC-10": section("SEC-10", tests=(test_id,))}), capsys)
    assert code == 1
    assert f"SEC-10: cited test can be skipped and the Windows field does not say what is " \
           f"omitted: {test_id}" in out
    said = section("SEC-10", tests=(test_id,), windows="se omite donde no hay enlaces.")
    code, out = check(project, matrix({"SEC-10": said}), capsys)
    assert code == 0, out
