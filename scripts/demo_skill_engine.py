"""Demo of the skill engine (Corte 4, first half) with the synthetic skills of the tests, a
temporary data directory and scripted Mock answers. Granting an approval needs a person at a
terminal: that step is printed as instructions, never simulated here.

Usage: uv run python scripts/demo_skill_engine.py
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from demo_common import ROOT, base_env, check, harness, header, run, step

FIXTURES = ROOT / "tests" / "fixtures" / "skills"
GOOD = "## Resumen\nTexto sintético resumido.\n\n## Preguntas pendientes\n- Ninguna."


def query(data: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(data / "harness.sqlite3")
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def last_run(data: Path) -> str:
    return query(data, "SELECT run_id FROM skill_runs ORDER BY created_at DESC LIMIT 1")[0][0]


def demo() -> list[str]:
    header()
    skipped: list[str] = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        data = work / "data"
        responses = work / "respuestas.json"
        responses.write_text(json.dumps({"tarea: demo-echo/draft": GOOD}), encoding="utf-8")
        env = base_env(
            HARNESS_DATA_DIR=str(data),
            HARNESS_SKILLS_DIR=str(FIXTURES),
            HARNESS_MOCK_RESPONSES=str(responses),
        )

        step("(a) skill list and skill show over the synthetic skills")
        listing = harness(env, "skill", "list")
        check(listing.returncode == 0, "skill list failed")
        rows = {line.split("\t")[0]: line for line in listing.stdout.splitlines()}
        check("\tvalid\t" in rows.get("demo-echo", ""), "demo-echo is not valid")
        check("unexpected file" in rows.get("bad-script", ""), "the script was not refused")
        check("unknown step kind 'tool'" in rows.get("bad-tool-kind", ""), "tool kind accepted")
        linked = work / "con-enlace"
        shutil.copytree(FIXTURES / "demo-echo", linked / "demo-echo")
        outside = work / "fuera.md"
        outside.write_text("CANARIO-DEMO-ENLACE\n", encoding="utf-8")
        try:
            (linked / "demo-echo" / "templates" / "review.md").symlink_to(outside)
        except OSError as exc:
            skipped.append(f"(a) link inside a skill: cannot create symbolic links here ({exc})")
        else:
            with_link = harness(env | {"HARNESS_SKILLS_DIR": str(linked)}, "skill", "list")
            check("link: templates/review.md" in with_link.stdout, "the link was not refused")
            check("CANARIO-DEMO-ENLACE" not in with_link.stdout + with_link.stderr,
                  "the linked file was shown")
        shown = harness(env, "skill", "show", "demo-echo")
        check(shown.returncode == 0 and "step 3: confirm approval" in shown.stdout,
              "skill show failed")

        step("(b) skill run demo-echo without a terminal: exit code 3, awaiting_approval")
        session = harness(env, "session", "create", "Demo Skills", show=False).stdout.strip()
        print(f"session: {session}")
        result = harness(env, "skill", "run", "demo-echo", "--session", session,
                         "--input", "text=Texto sintético de la demo")
        check(result.returncode == 3, f"expected exit code 3, got {result.returncode}")
        run_id = last_run(data)

        step("(c) skill status from another process")
        status = harness(env, "skill", "status", run_id)
        check("status: awaiting_approval" in status.stdout, "the run is not awaiting approval")
        check("approval: confirm pending" in status.stdout, "no pending approval shown")
        check("Texto sintético resumido" not in status.stdout, "status shows the content")

        step("(d) approve at a terminal: needs a person, printed as instructions")
        print("In an interactive terminal, with the same variables, run:")
        print(f"  uv run python main.py skill resume {run_id} "
              '--input "text=Texto sintético de la demo"')
        print("Read the proposal, type the first 8 characters of its hash; the run ends completed.")
        print("(Not done here: this demo cancels the run to go on.)")
        harness(env, "skill", "cancel", run_id)

        step("(e) a second use of a consumed approval is denied (test of task 5.4)")
        test = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "tests/unit/test_skill_approval.py::test_approval_reused"],
            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300,
        )
        print(test.stdout.strip().splitlines()[-1] if test.stdout.strip() else test.stderr)
        check(test.returncode == 0, "the reuse test failed")

        copy = work / "skills"
        shutil.copytree(FIXTURES, copy)
        workflow = copy / "demo-echo" / "workflow.json"
        workflow.write_text(
            workflow.read_text(encoding="utf-8").replace('"timeout_s": 30', '"timeout_s": 2'),
            encoding="utf-8",
        )
        copied = env | {"HARNESS_SKILLS_DIR": str(copy)}

        step("(f) Mock in timeout_after_send: uncertain, resume refused, --retry-step accepted")
        result = harness(copied | {"HARNESS_MOCK_BEHAVIOR": "timeout_after_send"},
                         "skill", "run", "demo-echo", "--session", session, "--input", "text=x")
        run_id = last_run(data)
        check(result.returncode == 1 and "uncertain" in result.stderr, "the step is not uncertain")
        refused = harness(copied, "skill", "resume", run_id, "--input", "text=x")
        check(refused.returncode == 1 and "--retry-step draft" in refused.stderr,
              "resume of an uncertain run was not refused")
        retried = harness(copied, "skill", "resume", run_id, "--input", "text=x",
                          "--retry-step", "draft")
        check(retried.returncode == 3, "the retry did not reach the approval")

        step("(g) edit the template between run and resume: refused by hash")
        template = copy / "demo-echo" / "templates" / "draft.md"
        template.write_text(template.read_text(encoding="utf-8") + "\nEditada.\n",
                            encoding="utf-8")
        changed = harness(copied, "skill", "resume", run_id, "--input", "text=x")
        check(changed.returncode == 1 and "changed on disk" in changed.stderr,
              "a changed skill was resumed")
        harness(copied, "skill", "cancel", run_id)

        step("(h) a response of 131 073 bytes: failed by limit")
        big = work / "grande.json"
        big.write_text(json.dumps({"tarea: demo-echo/draft": "x" * 131_073}), encoding="utf-8")
        result = harness(env | {"HARNESS_MOCK_RESPONSES": str(big)}, "skill", "run",
                         "demo-echo", "--session", session, "--input", "text=x")
        run_id = last_run(data)
        check(result.returncode == 1, "the run did not fail")
        status = harness(env, "skill", "status", run_id)
        check("limit:response_bytes" in status.stdout, "the limit is not named")
    return skipped


if __name__ == "__main__":
    sys.exit(run(demo))
