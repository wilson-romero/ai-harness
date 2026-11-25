"""`scripts/check_sec_matrix.py` (hardening D2): it says PASS only for a matrix that cites what
exists, and NO to each way the matrix can rot. Synthetic matrices, specs and collections under
`tmp_path`; the real collection only in the tests that need a subprocess."""

import importlib.util
import sys
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
COLLECTED = f"{TEST_A}\n{TEST_B}[case-1]\n{TEST_B}[case-2]\n\n3 tests collected in 0.01s\n"


def section(sec: str, state: str = "cubierto", tests: tuple[str, ...] = (TEST_A,),
            requirement: str = f"`{SPEC_PATH}` · {REQUIREMENT}", reason: str | None = None) -> str:
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
              "**Windows:** no ejecutado.",
              "**Límites:** ninguno conocido.", ""]
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
    code, out = check(project, matrix({"SEC-11": section("SEC-11", state="BLOCKED", tests=())}),
                      capsys)
    assert code == 1 and "SEC-11: state 'BLOCKED' needs a 'Motivo' line" in out


def test_a_blocked_row_with_a_reason_and_no_tests_passes(project, capsys):
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
                     "[otra](https://example.com) y [aquí](#ancla).\n",
                     encoding="utf-8", newline="\n")
    code, out = check(project, matrix(), capsys)
    assert code == 1
    assert "docs/security/known-debt.md: broken link: ../security/no-existe.md" in out
    assert "example.com" not in out and "#ancla" not in out


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


def test_main_without_collected_fails_on_a_broken_collection(project, capsys):
    (project / "tests").mkdir()
    (project / "tests" / "test_broken.py").write_text("import no_such_module_here\n",
                                                      encoding="utf-8", newline="\n")
    path = project / "docs" / "security" / "sec-matrix.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(matrix(), encoding="utf-8", newline="\n")
    code = checker.main(["--root", str(project)])
    out = capsys.readouterr()
    assert code == 1 and "PASS" not in out.out
    assert "pytest --collect-only exited" in out.err
