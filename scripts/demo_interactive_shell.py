"""Demo of Corte 9 (interactive shell) on a temporary data directory and a copy of the synthetic
vault, with scripted Mock answers.

The conversation runs here, in this process, with a scripted terminal in place of the console:
it types the lines a person would type and, at the approval prompt, the 8 characters of the hash
it was just shown, exactly like the tests' terminal. Nothing in the product can do that: the only
terminal `main.py chat` uses is the console. The real console and a real Ctrl+C are exercised by
the pseudo-terminal test (run below where one exists) and by the manual demo whose commands this
script prints at the end.

Usage: uv run python scripts/demo_interactive_shell.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from demo_common import ROOT, base_env, check, header, run, step

sys.path.insert(0, str(ROOT))

from harness.config import Settings  # noqa: E402
from harness.core.service import SessionService  # noqa: E402
from harness.memory.config import load_memory_settings  # noqa: E402
from harness.providers.registry import provider_factory  # noqa: E402
from harness.shell.conversation import Conversation, ConversationDeps  # noqa: E402
from harness.skills.config import load_skill_settings  # noqa: E402
from harness.storage.database import open_database  # noqa: E402
from harness.storage.locks import SessionLock  # noqa: E402

VAULT_FIXTURE = ROOT / "tests" / "fixtures" / "vault-synthetic"
INPUTS = ROOT / "tests" / "fixtures" / "skill-inputs"
EXTRACT_KEY = "tarea: architecture-memory/extract"


class DemoTerminal:
    """Types the scripted lines and echoes everything, as a person at a console would see it."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = list(lines)
        self.shown: list[str] = []

    def is_interactive(self) -> bool:
        return True

    def show(self, text: str) -> None:
        self.shown.extend(text.split("\n"))
        print(text, flush=True)

    def identity(self) -> str:
        return "persona-demo"

    def interrupt_wait(self) -> bool:
        return False

    async def read_line(self, prompt: str) -> str | None:
        line = self.lines.pop(0) if self.lines else None
        print(f"{prompt}{line if line is not None else '<end of input>'}", flush=True)
        return line

    def ask(self, question: str) -> str | None:
        hash_line = next(l for l in reversed(self.shown) if l.strip().startswith("hash:"))
        code = hash_line.split()[-1][:8]
        print(f"{question}{code}    <- typed by the demo's scripted terminal", flush=True)
        return code


def files(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def demo() -> list[str]:
    header()
    skipped: list[str] = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        vault = work / "vault"
        shutil.copytree(VAULT_FIXTURE, vault)
        data = work / "data"
        answers = work / "respuestas.json"
        answers.write_text(json.dumps({
            EXTRACT_KEY: (INPUTS / "decision-ok.json").read_text(encoding="utf-8"),
        }, ensure_ascii=False), encoding="utf-8")
        env = base_env(HARNESS_DATA_DIR=str(data), HARNESS_VAULT_ROOT=str(vault),
                       HARNESS_MOCK_RESPONSES=str(answers))
        before = files(vault)

        step("(a)-(f) one conversation: two questions, /context, a skill with approval, "
             "/history, /exit")
        source = INPUTS / "fuente-decision.md"
        terminal = DemoTerminal([
            "¿Qué decisiones de mensajería tiene el proyecto?",
            "¿Qué riesgos ves en esa decisión?",
            "/context",
            f'/skill architecture-memory --file "source={source}"',
            "/history",
            "/exit",
        ])
        os.environ.update(env)  # this process is the conversation: the vault effect reads it
        settings = Settings.from_env(env)
        conn = open_database(data)
        try:
            factory = provider_factory(settings)
            provider = factory(settings.provider)
            service = SessionService(conn, data, lambda name: provider, settings.provider,
                                     settings.request_timeout_s)
            conversation = Conversation(terminal, ConversationDeps(
                conn=conn, data_dir=data, service=service, provider=provider,
                provider_name=settings.provider, timeout_s=settings.request_timeout_s,
                memory=lambda: load_memory_settings(env),
                skills=lambda: load_skill_settings(env),
            ))
            code = asyncio.run(conversation.run(None, "demo-alpha", "Demo conversación"))
        finally:
            conn.close()
        check(code == 0, f"the conversation ended with {code}")

        db = sqlite3.connect(data / "harness.sqlite3")
        try:
            sessions = db.execute("SELECT session_id, project_id FROM sessions").fetchall()
            requests = [r[0] for r in db.execute("SELECT status FROM requests ORDER BY rowid")]
            runs = [r[0] for r in db.execute("SELECT status FROM skill_runs")]
            contexts = db.execute("SELECT count(DISTINCT request_id) FROM request_context"
                                  ).fetchone()[0]
        finally:
            db.close()
        print()
        check(len(sessions) == 1 and sessions[0][1] == "demo-alpha", "not one demo-alpha session")
        print(f"sessions: 1 ({sessions[0][0]}, project demo-alpha)")
        check(requests == ["completed"] * 3, f"requests: {requests}")
        print("requests: 3 completed (two questions and the skill's extract step)")
        check(contexts == 3, "a request went without the project's memory")
        print("memory: the project block went with each of the 3 requests (request_context)")
        check(runs == ["completed"], f"skill runs: {runs}")
        print("skill: architecture-memory completed after the approval")
        added = sorted(set(files(vault)) - set(before))
        check(len(added) == 1 and added[0].startswith("Decisiones/"), f"vault added {added}")
        check(all(files(vault)[k] == v for k, v in before.items()), "a vault file changed")
        print(f"vault: exactly one new file, {added[0]}; nothing else changed")
        check(any(l.startswith("| ") and "[skill architecture-memory/extract intento 1]" in l
                  for l in terminal.shown), "/history does not show the step marker")
        check(not any("Acta sintética" in l for l in terminal.shown if l.startswith("| [")),
              "the source text is in the history")
        print("history: the step marker, never the source text")
        lock = SessionLock(data, __import__("uuid").UUID(sessions[0][0]))
        check(lock.acquire(), "the session is still held after /exit")
        lock.release()
        print("exit: code 0 and the session is free")

        step("(g) a real Ctrl+C at a (pseudo-)terminal")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider",
             "tests/integration/test_chat_terminal.py"],
            cwd=ROOT, env=base_env(), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=600,
        )
        last = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr
        print(last)
        check(result.returncode == 0, "the pseudo-terminal test failed")
        if "skipped" in last:
            skipped.append("(g) no pseudo-terminal here: try Ctrl+C by hand (below)")

        step("by hand at a real terminal (the approval and Ctrl+C need a person)")
        print("Follow README.md > Conversación > Paso a paso (PowerShell and zsh): enter with")
        print("`main.py` alone, /new --project demo-alpha, two questions, /context, /skill")
        print("architecture-memory approved by typing the 8 characters, /exit; then a slow")
        print("question interrupted with Ctrl+C after `chat --session`, and /history.")
    return skipped


if __name__ == "__main__":
    sys.exit(run(demo))
