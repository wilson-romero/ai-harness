"""Test doubles for the conversation: a scripted terminal and providers that count and interrupt.

The terminal is injected (interactive-shell D2): these doubles drive the same loop a person
drives at a console. The order of events is fixed by the script, never by a clock.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path

from harness.core.errors import MemoryNotConfigured, UnknownProvider
from harness.core.service import SessionService
from harness.memory.config import CONTEXT_DEFAULT_BYTES, MemorySettings
from harness.providers.base import ProviderError
from harness.shell.conversation import FOREIGN_PREFIX, Conversation, ConversationDeps
from harness.shell.terminal import WaitInterrupted
from harness.skills.config import SkillSettings
from tests.skill_support import FIXTURES

INTERRUPT = object()  # Ctrl+C while the conversation waits for a line, or at the approval prompt
CODE = object()  # at the approval prompt: type the first 8 characters of the hash just shown


class Action:
    """Something the test does while the conversation waits for its next line."""

    def __init__(self, run: Callable[[ScriptedTerminal], object]) -> None:
        self.run = run


class ScriptedTerminal:
    """An interactive terminal whose lines and approval answers are given in advance.

    `lines`: str (a line), None (end of input), INTERRUPT, or Action. When the script runs out,
    the input ends. `approvals`: answers to the approval prompt: str, None, INTERRUPT or CODE.
    """

    def __init__(self, lines: list | None = None, approvals: list | None = None, *,
                 interactive: bool = True) -> None:
        self.lines = list(lines or [])
        self.approvals = list(approvals or [])
        self.interactive = interactive
        self.shown: list[str] = []
        self.questions: list[str] = []
        self.reads = 0

    def is_interactive(self) -> bool:
        return self.interactive

    def show(self, text: str) -> None:
        self.shown.extend(text.split("\n"))

    def identity(self) -> str:
        return "persona-local"

    def ask(self, question: str) -> str | None:
        self.questions.append(question)
        answer = self.approvals.pop(0) if self.approvals else None
        if answer is INTERRUPT:  # what ConsoleTerminal does with Ctrl+C at this prompt
            return None
        if answer is CODE:
            return self.last_code()
        return answer

    def last_code(self) -> str:
        line = next(l for l in reversed(self.shown) if l.strip().startswith("hash:"))
        return line.split()[-1][:8]

    def interrupt_wait(self) -> bool:
        return False  # a scripted wait never blocks: Ctrl+C there is the INTERRUPT item

    async def read_line(self, prompt: str) -> str | None:
        while True:
            self.reads += 1
            item = self.lines.pop(0) if self.lines else None
            if isinstance(item, Action):
                result = item.run(self)
                if asyncio.iscoroutine(result):
                    await result
                continue
            if item is INTERRUPT:
                raise WaitInterrupted
            self.shown.append(f"{prompt}{item if item is not None else '<end of input>'}")
            return item

    @property
    def text(self) -> str:
        return "\n".join(self.shown)

    def foreign(self) -> list[str]:
        return [line for line in self.shown if line.startswith(FOREIGN_PREFIX)]


class CountingProvider:
    """A synthetic provider that counts calls, opens and closes, and can fail or interrupt."""

    name = "mock"

    def __init__(self, *, synthetic: bool = True, fail: bool = False,
                 answer: str = "respuesta sintética") -> None:
        self.synthetic_content = synthetic
        self.fail = fail
        self.answer = answer
        self.prompts: list[str] = []
        self.opens = 0
        self.closes = 0
        # Set by a test: called inside `ask` (before or after `on_sent`), e.g. Ctrl+C.
        self.before_send: Callable[[], None] | None = None
        self.after_send: Callable[[], None] | None = None
        self.hang = False

    @property
    def calls(self) -> int:
        return len(self.prompts)

    async def open_resources(self) -> None:
        self.opens += 1

    async def close_resources(self) -> None:
        self.closes += 1

    async def ask(self, request, on_sent) -> str:
        self.prompts.append(request.prompt)
        if self.before_send is not None:
            hook, self.before_send = self.before_send, None
            hook()
            await asyncio.sleep(3600)
        on_sent()
        if self.after_send is not None:
            hook, self.after_send = self.after_send, None
            hook()
            await asyncio.sleep(3600)
        if self.hang:
            await asyncio.sleep(3600)
        if self.fail:
            raise ProviderError("the test provider was told to fail")
        return self.answer


def make_conversation(
    conn: sqlite3.Connection,
    data_dir: Path,
    terminal: ScriptedTerminal,
    provider=None,
    *,
    vault: Path | None = None,
    skills_dir: Path | None = None,
    effects: Mapping | None = None,
    timeout_s: float = 5.0,
    context_max_bytes: int = CONTEXT_DEFAULT_BYTES,
    engine_options: Mapping | None = None,
    columns: int = 10_000,  # a terminal this wide never cuts a line; the cut is tested apart
    answer_notice: str | None = None,  # `chat` passes CONCISE_NOTICE unless switched off
) -> tuple[Conversation, SessionService, object]:
    provider = provider if provider is not None else CountingProvider()

    def factory(name: str):
        if name != "mock":
            raise UnknownProvider(name)
        return provider

    service = SessionService(conn, data_dir, factory, "mock", timeout_s,
                             answer_notice=answer_notice)

    def memory() -> MemorySettings:
        if vault is None:
            raise MemoryNotConfigured("HARNESS_VAULT_ROOT is not set; point it at the vault folder")
        return MemorySettings(vault_root=vault.resolve(), context_max_bytes=context_max_bytes)

    conversation = Conversation(terminal, ConversationDeps(
        conn=conn,
        data_dir=data_dir,
        service=service,
        provider=provider,
        provider_name="mock",
        timeout_s=timeout_s,
        memory=memory,
        skills=lambda: SkillSettings(skills_dir=skills_dir or FIXTURES, approval_ttl_s=900),
        effects=effects,
        engine_options=engine_options,
        columns=lambda: columns,
    ))
    return conversation, service, provider


def statuses(conn: sqlite3.Connection) -> list[str]:
    return [row[0] for row in conn.execute("SELECT status FROM requests ORDER BY rowid")]
