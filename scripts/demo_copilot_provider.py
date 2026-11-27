"""Demo of the Copilot Web provider against the local SYNTHETIC chat, headless.

It runs anywhere Microsoft Edge is installed and never contacts a real service: the chat page,
its server and every prompt and answer are invented. The real-page commands are in
`docs/runbook/copilot.md`.

Usage: uv run python scripts/demo_copilot_provider.py
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

from demo_common import ROOT, base_env, check, harness, header, run, step

sys.path.insert(0, str(ROOT))
from tests.copilot_app import CANARY_REPLY, SyntheticCopilot  # noqa: E402

SYNTHETIC_UI = ROOT / "tests" / "fixtures" / "copilot_ui" / "ui.json"
# Never inherit a real Copilot address or the real dedicated profile.
COPILOT_VARS = (
    "HARNESS_COPILOT_URL",
    "HARNESS_EDGE_PROFILE",
    "HARNESS_COPILOT_READY_TIMEOUT_S",
    "HARNESS_COPILOT_MAX_PROMPT_CHARS",
)


def remote_ref(history: str) -> str | None:
    match = re.search(r"^remote conversation: ([A-Za-z0-9_-]+)$", history, flags=re.M)
    return match.group(1) if match else None


def demo() -> list[str]:
    app = SyntheticCopilot().start()
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work:
            data = Path(work) / "data"
            (data / "copilot").mkdir(parents=True)
            shutil.copy(SYNTHETIC_UI, data / "copilot" / "ui.json")
            env = {k: v for k, v in base_env().items() if k not in COPILOT_VARS}
            env |= {
                "HARNESS_DATA_DIR": str(data),
                "HARNESS_PROVIDER": "copilot_web",
                "HARNESS_COPILOT_URL": app.url(),
                "HARNESS_EDGE_PROFILE": str(Path(work) / "edge-profile"),
                "HARNESS_REQUEST_TIMEOUT_S": "40",
                "HARNESS_TEST_HEADLESS": "1",  # the synthetic page needs no window
            }
            header()
            print(f"synthetic chat: {app.url()}")

            step("(a) three sessions with the copilot_web provider, one question in each")
            sessions = [
                harness(env, "session", "create", name, show=False).stdout.strip()
                for name in ("Integraciones", "Pagos", "Revision")
            ]
            for n, session in enumerate(sessions):
                asked = harness(env, "ask", session, f"Pregunta sintetica {n} ZQX-END-{n}")
                check(asked.returncode == 0, f"the question in session {n} failed")
                check(CANARY_REPLY in asked.stdout, f"session {n} printed no answer")
            refs = [remote_ref(harness(env, "history", s, show=False).stdout) for s in sessions]
            check(None not in refs and len(set(refs)) == 3, "three sessions, not three conversations")
            for ref in refs:
                users = [t for t in app.conversations[ref] if t["role"] == "user"]
                check(len(users) == 1, "a conversation holds another session's question")
            print(f"three remote conversations, one question each: {len(set(refs))}")

            step("(b) a second process continues the first conversation")
            again = harness(env, "ask", sessions[0], "Segunda pregunta sintetica ZQX-END-9")
            check(again.returncode == 0, "the second question failed")
            users = [t["text"] for t in app.conversations[refs[0]] if t["role"] == "user"]
            check(len(users) == 2 and users[1].endswith("ZQX-END-9"), "not the same conversation")
            print(f"questions in the first conversation: {len(users)}")

            step("(c) history: reference and states, no text")
            history = harness(env, "history", sessions[0])
            check(history.stdout.count("[completed]") == 2, "the history lacks two requests")
            check("Pregunta" not in history.stdout and CANARY_REPLY not in history.stdout,
                  "the history shows text")

            step("(d) a reply that never ends: uncertain, sent exactly once")
            before = app.prompt_count
            stuck = env | {
                "HARNESS_COPILOT_URL": app.url("/app", never_finish="1"),
                "HARNESS_REQUEST_TIMEOUT_S": "10",
            }
            uncertain = harness(stuck, "ask", sessions[1], "Pregunta que no termina")
            check(uncertain.returncode == 1 and "uncertain" in uncertain.stderr, "not uncertain")
            check(app.prompt_count == before + 1, "the prompt did not arrive exactly once")

            step("(e) the next question warns about the extra turn and sends only itself")
            warned = harness(env, "ask", sessions[1], "Pregunta siguiente")
            check(warned.returncode == 0 and "more turn(s)" in warned.stderr, "no turn warning")
            check(app.prompt_count == before + 2, "something was resent")

            step("(f) a prompt over the limit is refused before Edge opens")
            limited = env | {"HARNESS_COPILOT_MAX_PROMPT_CHARS": "20"}
            refused = harness(limited, "ask", sessions[2], "x" * 21)
            check(refused.returncode == 1 and "the most Copilot takes here is 20" in refused.stderr,
                  "the long prompt was not refused")
            check(app.prompt_count == before + 2, "the long prompt was sent")
    finally:
        app.stop()
    return []


if __name__ == "__main__":
    sys.exit(run(demo))
