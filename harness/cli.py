"""Command line interface. Results go to stdout; warnings and errors go to stderr."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from harness.config import Settings
from harness.core.answer_style import with_notice
from harness.core.contracts import RequestStatus
from harness.core.errors import (
    HarnessError,
    MemoryNotConfigured,
    ProjectNotFound,
    UsageError,
)
from harness.core.service import SessionService
from harness.mcp.commands import add_mcp_parser, run_mcp_command
from harness.memory.config import (
    MemorySettings,
    ensure_data_dir_outside_vault,
    load_memory_settings,
)
from harness.memory.context import ProjectContext, build_context
from harness.memory.maintenance import maintenance_report
from harness.memory.paths import validate_project_slug
from harness.memory.search import (
    DEFAULT_LIMIT,
    parse_query,
    search_vault,
    validate_limit,
)
from harness.providers.registry import provider_factory
from harness.shell.app import add_chat_parser, run_chat, stdio_is_terminal
from harness.skills.commands import add_skill_parser, run_skill_command
from harness.skills.engine import recover_runs
from harness.storage.database import open_database

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="main.py", description="ai-harness")
    commands = parser.add_subparsers(dest="command", required=True)

    session = commands.add_parser("session", help="create and list sessions")
    session_commands = session.add_subparsers(dest="session_command", required=True)
    create = session_commands.add_parser("create", help="create a session")
    create.add_argument("name")
    create.add_argument("--project", default=None, help="optional project identifier")
    session_commands.add_parser("list", help="list sessions")

    ask = commands.add_parser("ask", help="ask a question in a session")
    ask.add_argument("session_id")
    ask.add_argument("prompt")
    ask.add_argument(
        "--project", default=None, help="send the memory of this project with the question"
    )

    history = commands.add_parser("history", help="show the history of a session")
    history.add_argument("session_id")

    memory = commands.add_parser("memory", help="read the local Markdown memory (read-only)")
    memory_commands = memory.add_subparsers(dest="memory_command", required=True)
    search = memory_commands.add_parser("search", help="find notes that contain every term")
    search.add_argument("query")
    search.add_argument("--project", default=None, help="only notes of this project")
    search.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"results to show (default {DEFAULT_LIMIT})",
    )
    context = memory_commands.add_parser(
        "context", help="print the context block that would be sent for a project"
    )
    context.add_argument("project")
    maintain = memory_commands.add_parser(
        "maintain", help="report what a maintenance pass would find, without changing anything"
    )
    maintain.add_argument("--dry-run", action="store_true", help="report only (required)")
    add_skill_parser(commands)
    add_mcp_parser(commands)
    add_chat_parser(commands)
    return parser


def _utf8_output() -> None:
    """Write UTF-8 whatever the console or the redirection is.

    A redirected stdout on Windows defaults to the ANSI code page (cp1252), which cannot
    encode many characters a note may hold; writing one would end the command with a
    traceback. Guarded by capability, not by platform.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: Sequence[str] | None = None) -> int:
    _utf8_output()
    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw and stdio_is_terminal():
        raw = ["chat"]  # at a console, the program alone opens the conversation (D1)
    args = build_parser().parse_args(raw)
    try:
        return _run(args)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except HarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED


def _run(args: argparse.Namespace) -> int:
    if args.command == "mcp":
        return run_mcp_command(args)
    if args.command == "chat":
        return run_chat(args)
    settings = Settings.from_env(os.environ)
    if args.command == "memory":
        return _memory(args)
    if args.command == "skill":
        return run_skill_command(args)
    memory: MemorySettings | None = None
    memory_error: MemoryNotConfigured | None = None
    with_project = args.command == "ask" and args.project is not None
    if with_project:
        try:
            memory = load_memory_settings(os.environ)
        except MemoryNotConfigured as exc:
            memory_error = exc  # refused below, once the refusal can be audited
        if memory is not None:
            # Before the database is opened: it would be created inside the vault.
            ensure_data_dir_outside_vault(settings.data_dir, memory.vault_root)
    conn = open_database(settings.data_dir)
    try:
        service = SessionService(
            conn,
            settings.data_dir,
            provider_factory(settings),
            settings.provider,
            settings.request_timeout_s,
            answer_notice=settings.answer_notice,
        )
        service.recover()
        recover_runs(conn, settings.data_dir)
        if args.command == "session" and args.session_command == "create":
            session = service.create_session(args.name, args.project)
            print(session.session_id)
            return EXIT_OK
        if args.command == "session":
            return _list_sessions(service)
        if with_project:
            # Every refusal from here on leaves a `memory.context denied` audit event (D7),
            # and no request and no content.
            service.check_project_question(args.session_id, args.prompt, args.project)
            try:
                if memory_error is not None:
                    raise memory_error
                assert memory is not None
                context = build_context(memory.vault_root, args.project, memory.context_max_bytes)
            except (MemoryNotConfigured, ProjectNotFound):
                service.deny_project_question(args.session_id)
                raise
            _context_summary(context)
            return _ask(service, args.session_id, args.prompt, context)
        if args.command == "ask":
            return _ask(service, args.session_id, args.prompt)
        return _history(service, args.session_id)
    finally:
        conn.close()


def _list_sessions(service: SessionService) -> int:
    sessions = service.list_sessions()
    if not sessions:
        print("No sessions.")
        return EXIT_OK
    for s in sessions:
        updated = s.updated_at.isoformat(timespec="seconds")
        print(f"{s.session_id}\t{s.status}\t{s.provider}\t{s.project_id or '-'}\t{updated}\t{s.name}")
    return EXIT_OK


def _ask(
    service: SessionService,
    session_id: str,
    prompt: str,
    context: ProjectContext | None = None,
) -> int:
    response = asyncio.run(service.ask(session_id, prompt, context))
    for warning in response.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if response.status is RequestStatus.COMPLETED:
        print(response.text)
        return EXIT_OK
    print(
        f"error: request {response.request_id} ended as {response.status}: {response.detail}",
        file=sys.stderr,
    )
    return EXIT_ERROR


def _history(service: SessionService, session_id: str) -> int:
    entries = service.history(session_id)
    if not entries:
        print("No messages.")
        return EXIT_OK
    for entry in entries:
        content = entry.content if entry.content is not None else "(content not stored)"
        print(f"[{entry.request_status}] {entry.role}: {content}")
    return EXIT_OK


# -- memory -------------------------------------------------------------------------------------


def _memory(args: argparse.Namespace) -> int:
    # Arguments are validated before the configuration, and both before the vault is read.
    if args.memory_command == "search":
        terms = parse_query(args.query)
        validate_limit(args.limit)
        if args.project is not None:
            validate_project_slug(args.project)
    elif args.memory_command == "context":
        validate_project_slug(args.project)
    elif not args.dry_run:
        raise UsageError("memory maintain only exists as --dry-run in this build")

    # The memory commands only read the vault: they open no database and write nothing.
    # They still refuse a data directory inside the vault, like `ask --project`, so that
    # such a configuration is caught by any memory command, before it can be used to write.
    memory = load_memory_settings(os.environ)
    settings = Settings.from_env(os.environ)
    ensure_data_dir_outside_vault(settings.data_dir, memory.vault_root)
    if args.memory_command == "search":
        return _search(memory.vault_root, terms, args.project, args.limit)
    if args.memory_command == "context":
        context = build_context(memory.vault_root, args.project, memory.context_max_bytes)
        # What `ask --project` sends before the question: the answer notice and the block.
        print(with_notice(settings.answer_notice, context.text))
        _context_summary(context)
        return EXIT_OK
    return _maintain(memory.vault_root)


def _search(root: Path, terms: tuple[str, ...], project: str | None, limit: int) -> int:
    result = search_vault(root, terms, project=project, limit=limit)
    if result.hits:
        for hit in result.hits:
            print(f"{hit.relative}\t{hit.updated or '-'}\t{hit.matches}\t{hit.snippet}")
    else:
        print("No results.")
    if result.omitted:
        print(f"warning: {result.omitted} more result(s) omitted; use --limit", file=sys.stderr)
    if result.truncated_walk:
        print("warning: the vault walk stopped at the file limit", file=sys.stderr)
    skipped = sum(result.skipped_counts.values())
    detail = ", ".join(f"{reason}: {count}" for reason, count in result.skipped_counts.items())
    print(
        f"search: {len(result.hits)} result(s), {result.omitted} omitted, "
        f"{skipped} entr{'y' if skipped == 1 else 'ies'} skipped"
        + (f" ({detail})" if detail else "")
        + f", {result.redactions} credential(s) redacted",
        file=sys.stderr,
    )
    return EXIT_OK


def _context_summary(context: ProjectContext) -> None:
    """What went into the block, on stderr: the block itself is the only thing on stdout."""
    for relative in context.omitted:
        print(f"omitted: {relative}", file=sys.stderr)  # already cleaned and redacted
    if context.truncated_walk:
        print("warning: the vault walk stopped at the file limit", file=sys.stderr)
    truncated = sum(1 for note in context.included if note.truncated)
    skipped = sum(context.skipped_counts.values())
    print(
        f"context: {context.project}, {len(context.included)} note(s) included, "
        f"{truncated} truncated, {len(context.omitted)} omitted, "
        f"{context.size} of {context.max_bytes} bytes, "
        f"{skipped} entr{'y' if skipped == 1 else 'ies'} skipped, "
        f"{context.redactions} credential(s) redacted",
        file=sys.stderr,
    )


def _maintain(root: Path) -> int:
    report = maintenance_report(root)
    print(report.text, end="")
    if report.truncated_walk:
        print("warning: the vault walk stopped at the file limit", file=sys.stderr)
    print("maintain: dry run, nothing in the vault was changed", file=sys.stderr)
    return EXIT_OK
