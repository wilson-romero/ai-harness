"""Command line interface. Results go to stdout; warnings and errors go to stderr."""

from __future__ import annotations

import argparse
import asyncio
import gc
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from harness.config import Settings
from harness.core.answer_style import with_notice
from harness.core.contracts import RequestStatus, Session
from harness.core.response_mode import ResponseMode, describe_mode
from harness.core.errors import (
    HarnessError,
    MemoryNotConfigured,
    ProjectNotFound,
    UsageError,
)
from harness.core.service import SessionService
from harness.core.watchdog import Watchdog
from harness.mcp.commands import add_mcp_parser, run_mcp_command
from harness.mcp.plan_cli import add_plan_parser, run_plan_command
from harness.memory.config import (
    MemorySettings,
    ensure_data_dir_outside_vault,
    load_memory_settings,
)
from harness.memory.context import ProjectContext, build_context
from harness.memory.maintenance import MAX_NAME_COMPARISONS, maintenance_report
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
from harness.text.safe_text import safe_foreign_text

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130
# harness/browser/edge.py SHUTDOWN_S, copied so that the CLI does not import Playwright.
BROWSER_SHUTDOWN_S = 25.0
WATCHDOG_MARGIN_S = 15.0


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
    ask.add_argument(
        "--mode", default=None, choices=[mode.value for mode in ResponseMode],
        help="set the session's response mode (kept for its next questions) and ask",
    )

    history = commands.add_parser("history", help="show the history of a session")
    history.add_argument("session_id")
    history.add_argument("--timings", action="store_true",
                         help="also the time of each phase of every question (Copilot Web)")

    copilot = commands.add_parser("copilot", help="Copilot Web: manual login")
    copilot_commands = copilot.add_subparsers(dest="copilot_command", required=True)
    copilot_commands.add_parser("login", help="open the dedicated Edge profile to sign in by hand")

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
    add_plan_parser(commands)  # code-mode slice 2
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
    if args.command == "plan":  # code-mode slice 2
        return run_plan_command(args)
    if args.command == "chat":
        return run_chat(args)
    settings = Settings.from_env(os.environ)
    if args.command == "copilot":
        return _copilot_login(settings)
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
            deep_timeout_s=settings.deep_request_timeout_s,
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
            return _ask(service, args.session_id, args.prompt, context, mode=args.mode)
        if args.command == "ask":
            return _ask(service, args.session_id, args.prompt, mode=args.mode)
        return _history(service, args.session_id,
                        timings=settings.data_dir if args.timings else None)
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
    *,
    mode: str | None = None,
) -> int:
    # Last-resort bound on the whole question: the deadline (that of `deep`, the longest),
    # then the browser's own cleanup time, then a margin. It fires even if the event loop is
    # blocked (harness/core/watchdog.py).
    limit_s = service.longest_timeout_s + BROWSER_SHUTDOWN_S + WATCHDOG_MARGIN_S
    with Watchdog(limit_s, "the question"):
        try:
            response = asyncio.run(_ask_quietly(service, session_id, prompt, context, mode))
        finally:
            gc.collect()  # unreferenced browser futures report now, to the quiet handler
    for warning in response.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if response.status is RequestStatus.COMPLETED:
        # Provider text is foreign: no escape sequence, control or invisible character reaches
        # the terminal, and known credentials are masked (security review 2026-11-27, F-03).
        print(safe_foreign_text(response.text).text)
        return EXIT_OK
    print(
        f"error: request {response.request_id} ended as {response.status}: {response.detail}",
        file=sys.stderr,
    )
    return EXIT_ERROR


async def _ask_quietly(
    service: SessionService,
    session_id: str,
    prompt: str,
    context: ProjectContext | None,
    mode: str | None = None,
):
    """`service.ask` with the browser runner's handler: an error Playwright leaves behind after
    the browser went away is not printed after the result (harness/browser/runner.py)."""
    from harness.browser.runner import quiet_handler

    asyncio.get_running_loop().set_exception_handler(quiet_handler)
    return await service.ask(session_id, prompt, context, mode=mode)


def _history(service: SessionService, session_id: str, *, timings: Path | None = None) -> int:
    session = service.require_session(session_id)
    if not service.provider_for(session).synthetic_content:
        return _history_without_content(service, session, timings=timings)
    if timings is not None:
        print(f"no timings are recorded for provider {session.provider}", file=sys.stderr)
    entries = service.history(session_id)
    if not entries:
        print("No messages.")
        return EXIT_OK
    for entry in entries:
        if entry.content is None:
            content = "(content not stored)"
        else:
            content = safe_foreign_text(entry.content).text  # as `ask` prints it (F-03)
        mode = describe_mode(entry.requested_mode, entry.confirmed_mode)
        state = entry.request_status if mode is None else f"{entry.request_status}, {mode}"
        print(f"[{state}] {entry.role}: {content}")
    return EXIT_OK


def _history_without_content(service: SessionService, session: Session, *,
                              timings: Path | None = None) -> int:
    """A provider with real content stores none (D11): the remote conversation and, per
    request, its state and time; with `timings` (the data directory), the time of each phase
    of each question (change copilot-turn-speed, D1), durations only."""
    print(f"session {session.session_id} ({session.provider}, {session.status})")
    print(f"remote conversation: {session.remote_ref or '(none yet)'}")
    requests = service.requests(session)
    modes = service.request_modes(session)
    if not requests:
        print("No requests.")
    phases = {}
    if timings is not None:
        from harness.providers.copilot_timings import read_for

        phases = read_for(timings, [str(request_id) for request_id, _, _ in requests])
    for request_id, status, started_at in requests:
        mode = describe_mode(*modes.get(request_id, (None, None)))
        print(f"[{status}] {request_id} {started_at}" + (f" {mode}" if mode else ""))
        if timings is not None:
            found = phases.get(str(request_id))
            print(f"  {found.line() if found else 'timings: none recorded'}")
    return EXIT_OK


def _copilot_login(settings: Settings) -> int:
    from harness.browser.login import manual_login  # Playwright loads only for this command
    from harness.browser.runner import run_browser

    print("Sign in to Copilot in the Edge window; it closes by itself when Copilot is ready.",
          file=sys.stderr)
    run_browser(manual_login(settings))
    print("Copilot is ready in the dedicated profile.")
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
    if report.truncated_comparisons:
        print(
            f"warning: name comparisons stopped at {MAX_NAME_COMPARISONS} pairs; "
            "duplicate_candidates or the fixes of broken_links are incomplete",
            file=sys.stderr,
        )
    print("maintain: dry run, nothing in the vault was changed", file=sys.stderr)
    return EXIT_OK
