"""Command line interface. Results go to stdout; warnings and errors go to stderr."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence

from harness.config import Settings
from harness.core.contracts import RequestStatus
from harness.core.errors import HarnessError
from harness.core.service import SessionService
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

    history = commands.add_parser("history", help="show the history of a session")
    history.add_argument("session_id")

    copilot = commands.add_parser("copilot", help="Copilot Web: manual login")
    copilot_commands = copilot.add_subparsers(dest="copilot_command", required=True)
    copilot_commands.add_parser("login", help="open the dedicated Edge profile to sign in by hand")
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
    if args.command == "copilot":
        return _copilot_login(settings)
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


def _copilot_login(settings: Settings) -> int:
    from harness.browser.login import manual_login  # Playwright loads only for this command

    print("Sign in to Copilot in the Edge window; it closes by itself when Copilot is ready.",
          file=sys.stderr)
    asyncio.run(manual_login(settings))
    print("Copilot is ready in the dedicated profile.")
    return EXIT_OK
