"""Test doubles for the skill engine: a scripted provider, a fake terminal, a test effect."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from harness.core.errors import UnknownProvider
from harness.core.service import SessionService
from harness.skills.effects import EffectContext, NoEffect, Prepared
from harness.skills.engine import SkillEngine
from harness.shell.render import CONTINUATION_PREFIX, FOREIGN_PREFIX
from tests.conftest import REPO_ROOT


def unmark_rows(rows: list[str]) -> str:
    """The content of an approval notice from its marked rows (security review 2026-11-27,
    F-04): each line starts with FOREIGN_PREFIX, each continuation row with
    CONTINUATION_PREFIX. Raises if a row carries neither mark."""
    lines: list[str] = []
    for row in rows:
        if row.startswith(CONTINUATION_PREFIX) and lines:
            lines[-1] += row[len(CONTINUATION_PREFIX):]
        elif row.startswith(FOREIGN_PREFIX):
            lines.append(row[len(FOREIGN_PREFIX):])
        else:
            raise AssertionError(f"an unmarked row inside the notice: {row!r}")
    return "\n".join(lines)

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "skills"
GOOD_ECHO = "## Resumen\nTexto resumido.\n\n## Preguntas pendientes\n- Ninguna."


class ScriptedProvider:
    """Answers by the first key (alphabetical) contained in the prompt, and records prompts."""

    name = "mock"

    def __init__(self, answers: Mapping[str, str] | None = None, *, synthetic: bool = True,
                 hang_after_send: bool = False) -> None:
        self.answers = dict(answers or {"tarea: demo-echo/draft": GOOD_ECHO})
        self.synthetic_content = synthetic
        self.hang_after_send = hang_after_send
        self.prompts: list[str] = []

    @property
    def calls(self) -> int:
        return len(self.prompts)

    async def ask(self, request, on_sent) -> str:
        self.prompts.append(request.prompt)
        on_sent()
        if self.hang_after_send:
            await asyncio.sleep(3600)
        for key in sorted(self.answers):
            if key in request.prompt:
                return self.answers[key]
        return "[scripted] no answer"


class FakeTerminal:
    """An interactive terminal whose answers are given in advance."""

    def __init__(self, answers: list[str | None] | None = None, *, interactive: bool = True,
                 on_ask=None) -> None:
        self.answers = list(answers or [])
        self.interactive = interactive
        self.shown: list[str] = []
        self.questions = 0
        self.on_ask = on_ask

    def is_interactive(self) -> bool:
        return self.interactive

    def show(self, text: str) -> None:
        self.shown.append(text)

    def ask(self, question: str) -> str | None:
        self.questions += 1
        if self.on_ask is not None:
            self.on_ask()
        return self.answers.pop(0) if self.answers else None

    def identity(self) -> str:
        return "persona-local"

    def code_of_last_proposal(self) -> str:
        line = next(l for l in self.shown[0].splitlines() if l.strip().startswith("hash:"))
        return line.split()[-1][:8]


class ApprovingTerminal(FakeTerminal):
    """A person at the terminal who types the code of the proposal just shown, every time."""

    def ask(self, question: str) -> str | None:
        self.questions += 1
        if self.on_ask is not None:
            self.on_ask()
        line = next(l for l in self.shown[-1].splitlines() if l.strip().startswith("hash:"))
        return line.split()[-1][:8]


class WriteEffect(NoEffect):
    """A test effect with consequences: each apply writes a new file in a temporary folder."""

    scope = "test.write"

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)

    def prepare(self, context: EffectContext, validated: str) -> Prepared:
        return Prepared(content=validated, target=f"{self.folder.name}/salida.md",
                        effect_ref=context.run_id)

    def apply(self, context: EffectContext, proposal) -> None:
        index = len(list(self.folder.iterdir()))
        (self.folder / f"{index}.md").write_bytes(proposal.content.encode("utf-8"))

    def reconcile(self, context: EffectContext, effect_ref, content_sha256: str):
        """`applied` if a file holds exactly that content; `conflict` if another file is there."""
        files = self.written()
        digests = {hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        if content_sha256 in digests:
            return "applied"
        return "conflict" if files else "absent"

    def written(self) -> list[Path]:
        return sorted(self.folder.iterdir())


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def copy_skills(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    shutil.copytree(FIXTURES, root)
    return root


def with_effect(root: Path, name: str, effect: str) -> None:
    """Point the approval step of a copied skill at another (test) effect."""
    path = root / name / "workflow.json"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('"effect": "none"', f'"effect": "{effect}"'), encoding="utf-8")


def build(conn: sqlite3.Connection, data_dir: Path, *, provider=None, root: Path | None = None,
          terminal=None, effects=None, clock=None, project_context=None, timeout_s: float = 5.0,
          **kwargs) -> tuple[SkillEngine, SessionService, ScriptedProvider]:
    provider = provider or ScriptedProvider()

    def factory(name: str):
        if name != "mock":
            raise UnknownProvider(name)
        return provider

    sessions = SessionService(conn, data_dir, factory, "mock", timeout_s)
    all_effects = {"none": NoEffect(), **(effects or {})}
    engine = SkillEngine(
        conn, data_dir, sessions, root or FIXTURES,
        default_timeout_s=timeout_s,
        effects=all_effects,
        terminal=terminal or FakeTerminal(interactive=False),
        clock=clock,
        context_builder=project_context,
        **kwargs,
    )
    return engine, sessions, provider


def all_text(conn_or_path) -> str:
    """Every TEXT and BLOB value of every table, joined: to look for content that must not be
    there. A BLOB is decoded as UTF-8 (invalid bytes replaced), so a text stored as bytes is
    found too; numbers and NULL are left out."""
    conn = sqlite3.connect(conn_or_path) if isinstance(conn_or_path, (str, Path)) else conn_or_path
    chunks = []
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
        for row in conn.execute(f"SELECT * FROM {table}"):  # noqa: S608 - table names from SQLite
            for value in row:
                if isinstance(value, str):
                    chunks.append(value)
                elif isinstance(value, bytes):
                    chunks.append(value.decode("utf-8", errors="replace"))
    return "\n".join(chunks)
