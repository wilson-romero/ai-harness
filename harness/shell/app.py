"""`main.py chat`: open a conversation (interactive-shell D1, D6; shell-tui D2, D7)."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import sys
from collections.abc import Callable, Coroutine, Iterator, Mapping
from typing import Any

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

PLAIN_VARIABLE = "HARNESS_PLAIN"
# Textual's debugging switches (shell-tui D7): any of them set and the conversation is plain
# text, because they would log the screen, save screenshots of it, press keys, import a
# driver module or let Ctrl+C kill the process. Kept here so that choosing the terminal never
# imports Textual; harness/shell/tui.py checks Textual's own reading of them once imported.
TEXTUAL_DEBUG_VARIABLES = (
    "TEXTUAL", "TEXTUAL_LOG", "TEXTUAL_DEBUG", "TEXTUAL_SCREENSHOT",
    "TEXTUAL_SCREENSHOT_LOCATION", "TEXTUAL_SCREENSHOT_FILENAME", "TEXTUAL_PRESS",
    "TEXTUAL_DRIVER", "TEXTUAL_DEVTOOLS_HOST", "TEXTUAL_DEVTOOLS_PORT", "TEXTUAL_ALLOW_SIGNALS",
    "TEXTUAL_SHOW_RETURN",
)
FULL_SCREEN_FAILED = "the full screen could not start on this console; going on in plain text"
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
    chat.add_argument("--plain", action="store_true",
                      help="plain text instead of the full screen "
                           f"(also {PLAIN_VARIABLE}=1, NO_COLOR or TERM=dumb)")


def plain_reason(environ: Mapping[str, str], plain_flag: bool, stdio_tty: bool) -> str | None:
    """Why the conversation uses the plain terminal, or None for the full screen (D7)."""
    if plain_flag:
        return "--plain"
    if environ.get(PLAIN_VARIABLE, "").strip() not in ("", "0"):
        return PLAIN_VARIABLE
    if environ.get("NO_COLOR", ""):  # https://no-color.org: set and not empty
        return "NO_COLOR"
    if environ.get("TERM", "").strip().lower() == "dumb":
        return "TERM=dumb"
    if not stdio_tty:
        return "no terminal"
    debugging = [name for name in TEXTUAL_DEBUG_VARIABLES if environ.get(name, "")]
    if debugging:
        return debugging[0]
    return None


def make_terminal(environ: Mapping[str, str], plain_flag: bool,
                  stdio_tty: bool) -> ConversationTerminal:
    """The full-screen terminal at a console, unless something asks for plain text or Textual
    cannot be loaded quietly; then the plain one, which is always there (shell-tui D7)."""
    if plain_reason(environ, plain_flag, stdio_tty) is not None:
        return ConsoleTerminal()
    try:
        from harness.shell.tui import TuiTerminal, textual_is_quiet  # noqa: PLC0415 - only here

        if not textual_is_quiet():
            return ConsoleTerminal()
        return TuiTerminal()
    except Exception:  # noqa: BLE001 - a console the library cannot drive gets plain text
        return ConsoleTerminal()


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


Runner = Callable[[Conversation, Coroutine[Any, Any, int]], int]


def run_chat(args: argparse.Namespace, terminal: ConversationTerminal | None = None) -> int:
    if terminal is None:
        terminal = make_terminal(os.environ, getattr(args, "plain", False), stdio_is_terminal())
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
    full_screen = getattr(terminal, "full_screen", None)
    if full_screen is not None:
        # The conversation runs in a thread of its own, with its own database connection and
        # event loop; the screen has the main thread (shell-tui D2).
        def in_thread(conversation: Conversation, run: Coroutine[Any, Any, int]) -> int:
            terminal.attach(conversation)  # type: ignore[union-attr]
            return asyncio.run(run)

        try:
            return full_screen(lambda: converse(args, settings, terminal, in_thread))
        except Exception as error:  # noqa: BLE001 - only FullScreenUnavailable is caught
            if type(error).__name__ != "FullScreenUnavailable":
                raise
            # Before anything was opened or asked: the plain conversation, said once.
            print(f"{FULL_SCREEN_FAILED} ({error})", file=sys.stderr, flush=True)
            terminal = ConsoleTerminal()

    def in_main(conversation: Conversation, run: Coroutine[Any, Any, int]) -> int:
        with interrupts_to(conversation):
            return asyncio.run(run)

    return converse(args, settings, terminal, in_main)


def converse(args: argparse.Namespace, settings: Settings, terminal: ConversationTerminal,
             runner: Runner) -> int:
    """Open the database, recover, build the conversation and run it with `runner`, all in
    the thread that calls this: the connection is used in that thread only."""
    factory = _one_instance_per_name(provider_factory(settings))
    provider = factory(settings.provider)
    conn = open_database(settings.data_dir)
    try:
        service = SessionService(conn, settings.data_dir, factory, settings.provider,
                                 settings.request_timeout_s,
                                 answer_notice=settings.answer_notice,
                                 deep_timeout_s=settings.deep_request_timeout_s)
        service.recover()
        recover_runs(conn, settings.data_dir)
        width = getattr(terminal, "pane_columns", None)  # the full screen's conversation pane
        conversation = Conversation(terminal, ConversationDeps(
            conn=conn,
            data_dir=settings.data_dir,
            service=service,
            provider=provider,
            provider_name=settings.provider,
            timeout_s=settings.request_timeout_s,
            memory=lambda: load_memory_settings(os.environ),
            skills=lambda: load_skill_settings(os.environ),
            **({"columns": width} if width is not None else {}),
        ))
        return runner(conversation, conversation.run(args.session, args.project, args.name))
    finally:
        conn.close()
