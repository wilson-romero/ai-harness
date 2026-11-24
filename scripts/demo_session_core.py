"""Demo of Corte 1 on a temporary data directory with synthetic content.

Usage: uv run python scripts/demo_session_core.py
"""

from __future__ import annotations

import sys
import tempfile
import time

from demo_common import base_env, check, harness, header, run, spawn, step


def demo() -> list[str]:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work:
        env = base_env(HARNESS_DATA_DIR=f"{work}/data")
        header()

        step("(a) three sessions")
        a, b, c = (
            harness(env, "session", "create", name, show=False).stdout.strip()
            for name in ("Arquitectura WhatsApp", "Migracion de pagos", "Revision HLS")
        )
        listing = harness(env, "session", "list")
        check(all(s and s in listing.stdout for s in (a, b, c)), "a session is missing")

        step("(b) one question in each")
        for session, label in ((a, "A"), (b, "B"), (c, "C")):
            asked = harness(env, "ask", session, f"Pregunta sintetica de la sesion {label}")
            check(asked.returncode == 0, f"the question in session {label} failed")

        step("(c) history from new processes, without mixing")
        for session in (a, b, c):
            print(f"-- {session}")
            harness(env, "history", session)
        history_a = harness(env, "history", a, show=False).stdout
        check("sesion A" in history_a, "session A lost its own history")
        check("sesion B" not in history_a, "session A shows data of session B")

        step("(d) kill a question half way")
        slow = spawn(env | {"HARNESS_MOCK_DELAY_MS": "60000"}, "ask", a, "Pregunta que se interrumpe")
        try:
            deadline = time.monotonic() + 30
            while "[running]" not in harness(env, "history", a, show=False).stdout:
                check(time.monotonic() < deadline, "the question never reached the running state")
                time.sleep(0.1)
        finally:
            slow.kill()
            slow.wait(timeout=30)
        listing = harness(env, "session", "list")
        history_a = harness(env, "history", a)
        check(
            "[uncertain] user: Pregunta que se interrumpe" in history_a.stdout,
            "the killed request is not uncertain",
        )
        row = next(line for line in listing.stdout.splitlines() if line.startswith(a))
        check("\tuncertain\t" in row, "the session is not uncertain")

        step("(e) malformed identifier")
        bad = harness(env, "history", "no-es-un-uuid")
        check(bad.returncode != 0, "a malformed identifier was accepted")
        check("Traceback" not in bad.stderr, "a traceback was shown")
    return []


if __name__ == "__main__":
    sys.exit(run(demo))
