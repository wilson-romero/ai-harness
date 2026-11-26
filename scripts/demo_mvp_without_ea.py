"""Demo of the "MVP without EA" gate with the scripted Mock: requirement -> project memory ->
`hls-review` -> the person's decision -> `architecture-memory` -> approval -> a new note in
`Decisiones/` -> `memory context`.

Everything runs on a temporary copy of the synthetic vault and a temporary data directory.
Granting the approval needs a person at a terminal: the demo never simulates it. It prints the
exact commands to approve this very run (PowerShell and a POSIX shell); the approval itself, the
note coming back through `memory context`, the duplicates (the same decision file, refused
before the model is asked; another text with the same title, refused after it) and the check
that the project memory is in the prompt run in `tests/integration/test_mvp_flow.py`, which the
demo runs. Every other
step runs the real CLI in a separate process and checks the vault's fingerprint around it.

The Mock answers by the first key (alphabetical) contained in the prompt. Here the keys are the
unique phrases of the requirement and of the person's decision, so a scripted answer comes back
only if that input reached the provider; otherwise the Mock's unscripted answer fails `validate`.

Usage:
    uv run python scripts/demo_mvp_without_ea.py           # cancels the run and cleans up
    uv run python scripts/demo_mvp_without_ea.py --keep    # leaves the run waiting for you
"""

from __future__ import annotations

import argparse
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
FIXTURES = ROOT / "tests" / "fixtures" / "mvp"
REQUIREMENT_CANARY = "R1-7Q4"  # only in the requirement (and in the decision, which says so)
DECISION_CANARY = "D-5K2"  # only in the person's decision; sorts before the other key
HEADINGS = ("Resumen", "Alternativas", "Restricciones", "Requisitos no funcionales",
            "Supuestos", "Preguntas pendientes")
CANARIES = (REQUIREMENT_CANARY, DECISION_CANARY)


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


def query(data: Path, sql: str, *params: object) -> list[tuple]:
    conn = sqlite3.connect(data / "harness.sqlite3")
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def last_run(data: Path) -> str:
    return query(data, "SELECT run_id FROM skill_runs ORDER BY created_at DESC, rowid DESC "
                       "LIMIT 1")[0][0]


def copy_lf(source: Path, target: Path) -> Path:
    """Copy a fixture with `\\n` line ends, whatever the checkout did."""
    with target.open("w", encoding="utf-8", newline="\n") as out:
        out.write(source.read_text(encoding="utf-8"))
    return target


def memory_lines(output: str) -> list[str]:
    lines = output.splitlines()
    opening = [i for i, line in enumerate(lines) if line.startswith("<<<MEMORIA ")]
    check(len(opening) == 1, "memory context has not exactly one opening data marker")
    nonce = lines[opening[0]].split()[1]
    check(f"MEMORIA {nonce}>>>" in lines, "memory context has no closing data marker")
    return lines[opening[0] + 1:lines.index(f"MEMORIA {nonce}>>>")]


def pytest(env: dict[str, str], *tests: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600,
    )
    lines = result.stdout.strip().splitlines()
    print(lines[-1] if lines else result.stderr)
    check(result.returncode == 0, f"tests failed: {' '.join(tests)}")


def approval_instructions(data: Path, vault: Path, responses: Path, run_id: str,
                          decision: Path) -> None:
    print("Approving needs a person at an interactive terminal; this demo never does it.")
    print("From the repository root, in PowerShell:")
    print(f"  $env:HARNESS_DATA_DIR = '{data}'")
    print(f"  $env:HARNESS_VAULT_ROOT = '{vault}'")
    print(f"  $env:HARNESS_MOCK_RESPONSES = '{responses}'")
    print(f"  uv run python main.py skill resume {run_id} --input-file 'source={decision}'")
    print("  uv run python main.py memory context demo-alpha")
    print("Or in zsh/bash:")
    print(f"  export HARNESS_DATA_DIR='{data}'")
    print(f"  export HARNESS_VAULT_ROOT='{vault}'")
    print(f"  export HARNESS_MOCK_RESPONSES='{responses}'")
    print(f"  uv run python main.py skill resume {run_id} --input-file 'source={decision}'")
    print("  uv run python main.py memory context demo-alpha")
    print("`skill resume` shows the whole note between two dashed lines, with `target:` and")
    print("`hash:`; typing the first 8 characters of the hash writes exactly that note and")
    print("prints `applied: Decisiones/...` (exit code 0); `n` cancels it (exit code 1).")
    print("`memory context demo-alpha` then lists the note inside the MEMORIA markers.")


def demo(keep: bool) -> list[str]:
    header()
    work = Path(tempfile.mkdtemp(prefix="ai-harness-mvp-"))
    try:
        result = _demo(work, keep)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    if keep:
        print(f"\nkept: {work} (delete it when you are done)")
    else:
        shutil.rmtree(work, ignore_errors=True)
    return result


def _demo(work: Path, keep: bool) -> list[str]:
    vault = work / "vault"
    shutil.copytree(VAULT_FIXTURE, vault)
    data = work / "data"
    responses = work / "respuestas-por-entrada.json"
    responses.write_text(json.dumps({
        REQUIREMENT_CANARY: (FIXTURES / "revision-mock.md").read_text(encoding="utf-8"),
        DECISION_CANARY: (FIXTURES / "decision-mock.json").read_text(encoding="utf-8"),
    }, ensure_ascii=False), encoding="utf-8", newline="\n")
    requirement = copy_lf(FIXTURES / "requerimiento-1-eventos-pedidos.md",
                          work / "requerimiento.md")
    env = base_env(HARNESS_DATA_DIR=str(data), HARNESS_VAULT_ROOT=str(vault),
                   HARNESS_MOCK_RESPONSES=str(responses))
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

    step("(b) a session bound to demo-alpha, and the project memory it will use")
    created = harness(env, "session", "create", "Puerta MVP", "--project", "demo-alpha",
                      show=False)
    check(created.returncode == 0, "the session could not be created")
    session = created.stdout.strip()
    print(f"session: {session}")
    context = harness(env, "memory", "context", "demo-alpha", show=False)
    check(context.returncode == 0, "memory context failed")
    print(context.stdout.splitlines()[0])
    notes = [line for line in memory_lines(context.stdout) if line.startswith("--- nota: ")]
    for line in notes:
        print(f"  {line}")
    check(any("projects/demo-alpha/_project.md" in line for line in notes),
          "the project note is not in the context")
    untouched("memory context")

    step("(c) hls-review over the requirement: the review by stdout, exit code 0")
    review = harness(env, "skill", "run", "hls-review", "--session", session,
                     "--input-file", f"document={requirement}")
    check(review.returncode == 0, f"hls-review ended with {review.returncode}")
    for heading in HEADINGS:
        check(f"## {heading}\n" in review.stdout, f"the review has no '{heading}'")
    review_run = last_run(data)
    sent = {row[0] for row in query(
        data, "SELECT c.note_path FROM request_context c JOIN skill_steps s ON "
              "s.request_id = c.request_id WHERE s.run_id = ? AND s.step_key = 'review'",
        review_run)}
    print(f"scripted review returned: the requirement ({REQUIREMENT_CANARY}) reached the provider")
    print(f"notes recorded as sent (request_context, not the prompt itself): {len(sent)}")
    check("projects/demo-alpha/_project.md" in sent, "the project note is not recorded as sent")
    check(query(data, "SELECT count(*) FROM approvals")[0][0] == 0, "an approval appeared")
    untouched("hls-review")

    step("(d) the person reads the review and writes the decision they take")
    print("A person does this by hand, in a file of their own outside the repository; the")
    print("demo uses the synthetic one in tests/fixtures/mvp/decision-persona.md.")
    decision = copy_lf(FIXTURES / "decision-persona.md", work / "decision.md")
    print(f"decision file: {decision}")

    step("(e) architecture-memory in the same session, stdin redirected: exit code 3")
    waiting = harness(env, "skill", "run", "architecture-memory", "--session", session,
                      "--input-file", f"source={decision}")
    check(waiting.returncode == 3, f"expected exit code 3, got {waiting.returncode}")
    run_id = last_run(data)
    status = harness(env, "skill", "status", run_id)
    check(f"session: {session}" in status.stdout, "the run is not in the same session")
    check("approval: save pending" in status.stdout, "no pending approval")
    print(f"scripted decision returned: the person's decision ({DECISION_CANARY}) reached the "
          "provider")
    untouched("architecture-memory without a terminal")

    step("(f) the approval: printed as instructions for a person; the flow test approves")
    approval_instructions(data, vault, responses, run_id, decision)
    if keep:
        print("--keep: the run stays waiting for your approval.")
    else:
        print("Rerun with --keep to leave this directory and approve this very run. Here the")
        print("demo cancels it and runs the end-to-end test that approves with the test")
        print("terminal (note written once, back in memory context; the same decision again is")
        print("refused before asking the model, another text with the same title after it).")
        cancelled = harness(env, "skill", "cancel", run_id)
        check(cancelled.returncode == 0, "the run could not be cancelled")
        untouched("the cancellation")
    print("tests/integration/test_mvp_flow.py (on its own copy of the vault):")
    pytest(env, "tests/integration/test_mvp_flow.py")

    step("(g) history: the step markers, never the requirement nor the decision text")
    history = harness(env, "history", session, show=False)
    check(history.returncode == 0, "history failed")
    for marker in ("[skill hls-review/review intento 1]",
                   "[skill architecture-memory/extract intento 1]"):
        check(marker in history.stdout, f"no marker {marker}")
        print(f"marker: {marker}")
    for canary in CANARIES:
        check(canary not in history.stdout, "an input text is in the history")
    print("history: no text of the requirement nor of the decision")
    untouched("history")
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", action="store_true",
                        help="keep the temporary directory and leave the run waiting")
    args = parser.parse_args()
    return run(lambda: demo(args.keep))


if __name__ == "__main__":
    sys.exit(main())
