"""`main.py chat`: open a conversation (interactive-shell D1, D6)."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import sys
from collections.abc import Iterator

from harness.config import Settings
from harness.core.errors import UsageError
from harness.core.service import SessionService, parse_session_id
from harness.memory.config import (
    ensure_data_dir_outside_vault,
    load_memory_settings,
)
from harness.memory.paths import validate_project_slug
from harness.providers.base import LLMProvider
from harness.providers.registry import ProviderFactory, provider_factory
from harness.shell.conversation import Conversation, ConversationDeps
from harness.shell.terminal import ConsoleTerminal, ConversationTerminal
from harness.skills.config import load_skill_settings
from harness.skills.engine import recover_runs
from harness.storage.database import open_database

NO_TERMINAL = (
    "chat needs an interactive terminal (its input and output must be a console); "
    "scripts use the single commands: session, ask, history, memory, skill"
)


def stdio_is_terminal() -> bool:
    """Whether the program runs at a console: then `main.py` without arguments opens `chat`."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def add_chat_parser(commands: argparse._SubParsersAction) -> None:
    chat = commands.add_parser("chat", help="talk with the harness: questions and /commands")
    chat.add_argument("--session", default=None, help="continue this session")
    chat.add_argument("--project", default=None,
                      help="for a new session: send the memory of this project with each question")
    chat.add_argument("--name", default=None, help="the name of the new session")


def _one_instance_per_name(factory: ProviderFactory) -> ProviderFactory:
    """The conversation, its questions and its skills share one provider object (D5)."""
    built: dict[str, LLMProvider] = {}

    def build(name: str) -> LLMProvider:
        if name not in built:
            built[name] = factory(name)
        return built[name]

    return build


@contextlib.contextmanager
def interrupts_to(conversation: Conversation) -> Iterator[None]:
    """Ctrl+C goes to the conversation while it runs (D6). Installed before `asyncio.run`, so
    the runner keeps it instead of installing its own; the handler never raises."""
    previous = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, lambda _signum, _frame: conversation.interrupt())
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


def run_chat(args: argparse.Namespace, terminal: ConversationTerminal | None = None) -> int:
    terminal = terminal if terminal is not None else ConsoleTerminal()
    # First, before any configuration, database or session is touched.
    if not terminal.is_interactive():
        raise UsageError(NO_TERMINAL)
    if args.session is not None:
        parse_session_id(args.session)
        if args.project is not None or args.name is not None:
            raise UsageError("--project and --name are for a new session, not with --session")
    if args.project is not None:
        validate_project_slug(args.project)
    settings = Settings.from_env(os.environ)
    if args.project is not None:
        # Before the database is opened: it would be created inside the vault.
        ensure_data_dir_outside_vault(settings.data_dir, load_memory_settings(os.environ).vault_root)
    factory = _one_instance_per_name(provider_factory(settings))
    provider = factory(settings.provider)
    conn = open_database(settings.data_dir)
    try:
        service = SessionService(conn, settings.data_dir, factory, settings.provider,
                                 settings.request_timeout_s)
        service.recover()
        recover_runs(conn, settings.data_dir)
        conversation = Conversation(terminal, ConversationDeps(
            conn=conn,
            data_dir=settings.data_dir,
            service=service,
            provider=provider,
            provider_name=settings.provider,
            timeout_s=settings.request_timeout_s,
            memory=lambda: load_memory_settings(os.environ),
            skills=lambda: load_skill_settings(os.environ),
        ))
        with interrupts_to(conversation):
            return asyncio.run(conversation.run(args.session, args.project, args.name))
    finally:
        conn.close()
