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
from harness.core.errors import HarnessError, InvalidInput, NotImplementedInThisBuild
from harness.core.service import SessionService
from harness.memory.config import bind_data_dir, load_memory_settings
from harness.memory.paths import resolve_project, validate_project_slug
from harness.memory.search import DEFAULT_LIMIT, parse_query, search_vault, validate_limit
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
    if args.command == "ask" and args.project is not None:
        # TODO(project-memory 5.4): replace with the real `ask --project`.
        raise NotImplementedInThisBuild("ask --project is not implemented in this build")
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


def _ask(service: SessionService, session_id: str, prompt: str) -> int:
    response = asyncio.run(service.ask(session_id, prompt))
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
        resolve_project(memory.vault_root, args.project)
        # TODO(project-memory 5.3): replace with the real `memory context`.
        raise NotImplementedInThisBuild("memory context is not implemented in this build")
    # TODO(project-memory 6.1): replace with the real `memory maintain --dry-run`.
    raise NotImplementedInThisBuild("memory maintain is not implemented in this build")


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
