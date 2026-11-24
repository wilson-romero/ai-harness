"""Command line interface. Results go to stdout; warnings and errors go to stderr."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from harness.config import Settings
from harness.core.contracts import RequestStatus
from harness.core.errors import HarnessError, InvalidInput
from harness.core.service import SessionService
from harness.memory.config import MemorySettings, bind_data_dir, load_memory_settings
from harness.memory.context import ProjectContext, build_context
from harness.memory.maintenance import maintenance_report
from harness.memory.paths import validate_project_slug
from harness.memory.search import (
    DEFAULT_LIMIT,
    parse_query,
    search_vault,
    terminal_safe,
    validate_limit,
)
from harness.providers.registry import provider_factory
from harness.storage.database import open_database

EXIT_OK = 0
EXIT_ERROR = 1
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except HarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED


def _run(args: argparse.Namespace) -> int:
    settings = Settings.from_env(os.environ)
    if args.command == "memory":
        return _memory(args, settings)
    memory: MemorySettings | None = None
    if args.command == "ask" and args.project is not None:
        # Same order as the memory commands: arguments, then configuration, then the vault.
        validate_project_slug(args.project)
        memory = load_memory_settings(os.environ, settings.data_dir)
    conn = open_database(settings.data_dir)
    try:
        service = SessionService(
            conn,
            settings.data_dir,
            provider_factory(settings),
            settings.provider,
            settings.request_timeout_s,
        )
        service.recover()
        if args.command == "session" and args.session_command == "create":
            session = service.create_session(args.name, args.project)
            print(session.session_id)
            return EXIT_OK
        if args.command == "session":
            return _list_sessions(service)
        if args.command == "ask" and memory is not None:
            bind_data_dir(conn, memory)
            service.check_project_question(args.session_id, args.prompt, args.project)
            context = build_context(memory.vault_root, args.project, memory.context_max_bytes)
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


def _memory(args: argparse.Namespace, settings: Settings) -> int:
    # Arguments are validated before the configuration, and both before the vault is read.
    if args.memory_command == "search":
        terms = parse_query(args.query)
        validate_limit(args.limit)
        if args.project is not None:
            validate_project_slug(args.project)
    elif args.memory_command == "context":
        validate_project_slug(args.project)
    elif not args.dry_run:
        raise InvalidInput("memory maintain only exists as --dry-run in this build")

    memory = load_memory_settings(os.environ, settings.data_dir)
    conn = open_database(settings.data_dir)
    try:
        bind_data_dir(conn, memory)
    finally:
        conn.close()

    if args.memory_command == "search":
        return _search(memory.vault_root, terms, args.project, args.limit)
    if args.memory_command == "context":
        context = build_context(memory.vault_root, args.project, memory.context_max_bytes)
        print(context.text)
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
        print(f"omitted: {terminal_safe(relative)}", file=sys.stderr)
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
