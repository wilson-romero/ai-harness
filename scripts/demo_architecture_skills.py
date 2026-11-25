"""Demo of the architecture skills (Corte 4): `hls-review` and `architecture-memory` on a temporary
copy of the synthetic vault, with a temporary data directory and scripted Mock answers.

Granting an approval needs a person at a terminal: that step is printed as instructions (with
the exact commands), never simulated here; what it proves is run as the end-to-end tests that
drive the engine with the test terminal. Every other step runs the real CLI in a separate process
and checks the vault's fingerprint (paths, sizes, times and SHA-256) around it.

Usage: uv run python scripts/demo_architecture_skills.py
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from demo_common import ROOT, base_env, check, harness, header, run, step

VAULT_FIXTURE = ROOT / "tests" / "fixtures" / "vault-synthetic"
INPUTS = ROOT / "tests" / "fixtures" / "skill-inputs"
REVIEW_KEY = "tarea: hls-review/review"
EXTRACT_KEY = "tarea: architecture-memory/extract"
SOURCE_CANARY = "Acta sintética: mensajería de pedidos"


def fingerprint(root: Path) -> dict[str, tuple]:
    prints: dict[str, tuple] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in sorted(dirnames + filenames):
            path = Path(dirpath, name)
            info = path.lstat()
            relative = path.relative_to(root).as_posix()
            digest = "" if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
            prints[relative] = (path.is_dir(), info.st_size, info.st_mtime_ns, digest)
    return prints


def query(data: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(data / "harness.sqlite3")
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def last_run(data: Path) -> str:
    return query(data, "SELECT run_id FROM skill_runs ORDER BY created_at DESC LIMIT 1")[0][0]


def responses(work: Path, name: str, review: str) -> Path:
    path = work / name
    path.write_text(json.dumps({
        REVIEW_KEY: (INPUTS / review).read_text(encoding="utf-8"),
        EXTRACT_KEY: (INPUTS / "decision-ok.json").read_text(encoding="utf-8"),
    }, ensure_ascii=False), encoding="utf-8")
    return path


def pytest(env: dict[str, str], *tests: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600,
    )
    lines = result.stdout.strip().splitlines()
    print(lines[-1] if lines else result.stderr)
    check(result.returncode == 0, f"tests failed: {' '.join(tests)}")


def demo() -> list[str]:
    header()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        vault = work / "vault"
        shutil.copytree(VAULT_FIXTURE, vault)
        data = work / "data"
        good = responses(work, "respuestas.json", "hls-review-ok.md")
        incomplete = responses(work, "respuestas-incompletas.json", "hls-review-incompleta.md")
        env = base_env(HARNESS_DATA_DIR=str(data), HARNESS_VAULT_ROOT=str(vault),
                       HARNESS_MOCK_RESPONSES=str(good))
        original = fingerprint(vault)

        def untouched(what: str) -> None:
            check(fingerprint(vault) == original, f"the vault changed after {what}")
            print("vault: fingerprint unchanged")

        step("(a) skill list: hls-review and architecture-memory are valid")
        listing = harness(env, "skill", "list")
        rows = {line.split("\t")[0]: line.split("\t") for line in listing.stdout.splitlines()}
        for name in ("hls-review", "architecture-memory"):
            check(rows.get(name, [])[1:3] == ["1.0.0", "valid"], f"{name} is not valid")
        untouched("skill list")

        step("(b) hls-review in a demo-alpha session: the review by stdout")
        session = harness(env, "session", "create", "Demo", "--project", "demo-alpha",
                          show=False).stdout.strip()
        print(f"session: {session}")
        review = harness(env, "skill", "run", "hls-review", "--session", session,
                         "--input-file", f"document={INPUTS / 'hls-corto.md'}")
        check(review.returncode == 0, f"hls-review ended with {review.returncode}")
        check("## Preguntas pendientes" in review.stdout, "the review is not on stdout")
        check(query(data, "SELECT count(*) FROM approvals")[0][0] == 0, "an approval appeared")
        untouched("hls-review")

        step("(c) the same review with an incomplete answer: failed, the heading named")
        failed = harness(env | {"HARNESS_MOCK_RESPONSES": str(incomplete)}, "skill", "run",
                         "hls-review", "--session", session,
                         "--input-file", f"document={INPUTS / 'hls-corto.md'}")
        check(failed.returncode == 1, f"expected exit code 1, got {failed.returncode}")
        check("## Resumen" not in failed.stdout, "the incomplete answer was printed")
        status = harness(env, "skill", "status", last_run(data))
        check("error: validation_failed:required_headings:Preguntas pendientes" in status.stdout,
              "the missing heading is not named")
        untouched("the incomplete review")

        step("(d) architecture-memory with stdin redirected: exit code 3, nothing written")
        source = INPUTS / "fuente-decision.md"
        waiting = harness(env, "skill", "run", "architecture-memory", "--session", session,
                          "--input-file", f"source={source}")
        check(waiting.returncode == 3, f"expected exit code 3, got {waiting.returncode}")
        run_id = last_run(data)
        status = harness(env, "skill", "status", run_id)
        check("approval: save pending" in status.stdout, "no pending approval")
        check("Cola gestionada" not in status.stdout, "status shows the note")
        untouched("architecture-memory without a terminal")

        step("(e) approve at a terminal: needs a person, printed as instructions")
        print("In an interactive terminal (PowerShell or zsh), with these variables:")
        print(f"  HARNESS_DATA_DIR={data}")
        print(f"  HARNESS_VAULT_ROOT={vault}")
        print(f"  HARNESS_MOCK_RESPONSES={good}")
        print(f"  uv run python main.py skill resume {run_id} --input-file source={source}")
        print("The note is shown whole with its target Decisiones/<fecha>-<slug>-<id8>.md and")
        print("its hash; typing the first 8 characters writes exactly those bytes. Here the")
        print("demo cancels the run and runs the tests that approve with the test terminal.")
        cancelled = harness(env, "skill", "cancel", run_id)
        check(cancelled.returncode == 0, "the run could not be cancelled")
        pytest(env,
               "tests/integration/test_architecture_memory.py::"
               "test_approved_in_the_terminal_writes_exactly_one_new_file",
               "tests/integration/test_architecture_memory.py::"
               "test_rejected_cancels_and_leaves_the_vault_untouched",
               "tests/integration/test_decision_crash.py")
        untouched("the cancelled run")

        step("(f) and (g) the note in memory context, and the same title again: duplicate")
        pytest(env,
               "tests/integration/test_architecture_memory.py::"
               "test_a_written_decision_comes_back_through_memory_context_as_data",
               "tests/integration/test_architecture_memory.py::"
               "test_the_same_title_again_is_a_duplicate_without_an_approval")

        step("(h) the memory commands still write nothing")
        for command in (("memory", "search", "cola"), ("memory", "context", "demo-alpha"),
                        ("memory", "maintain", "--dry-run")):
            result = harness(env, *command, show=False)
            check(result.returncode == 0, f"{' '.join(command)} failed")
        untouched("the memory commands")

        step("(i) history: the step markers, never the source text")
        history = harness(env, "history", session)
        check("[skill hls-review/review intento 1]" in history.stdout, "no step marker")
        check("[skill architecture-memory/extract intento 1]" in history.stdout,
              "no extract marker")
        check(SOURCE_CANARY not in history.stdout, "the source text is in the history")
        untouched("history")
    return []


if __name__ == "__main__":
    sys.exit(run(demo))
