"""`main.py plan SESSION_ID QUESTION`: `/plan` outside the conversation (code-mode slice 2).

The same flow (`plan_flow.run_plan`), with the typed code as the only approval: it needs an
interactive terminal on stdin and stdout, and refuses before anything is sent otherwise (a
plan nobody can approve is never asked for). Harness lines go to stderr, as every command's;
the reply and the results, which are foreign text, go to stdout, cleaned as `ask` and
`mcp call` clean theirs and with every line after the bar (`prefixed`, as `mcp call` and
`chat --plain`), so no line of theirs can pass for one of the harness's; the approval notice
and its question go where the code is typed.
The session is held for the whole command, as a conversation holds it.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from harness.config import Settings
from harness.core.errors import UsageError
from harness.core.service import SessionService
from harness.mcp.commands import prefixed
from harness.mcp.config import load_config
from harness.mcp.loop_flow import IN_THIS_SESSION, holds_results
from harness.mcp.plan_flow import PlanRequest, PlanSetting, auto_read_setting, run_plan
from harness.mcp.plan_prompt import build_catalogue
from harness.providers.base import close_resources, open_resources
from harness.providers.registry import provider_factory
from harness.shell.render import FOREIGN_PREFIX
from harness.shell.terminal import TtyTerminal
from harness.skills.approvals import APPROVAL_RULE
from harness.skills.config import load_skill_settings
from harness.storage.database import open_database
from harness.text.safe_text import safe_foreign_text, safe_line

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130  # as `cli.main` after a Ctrl+C
MAX_QUESTION_CHARS = 16_000


def add_plan_parser(commands: argparse._SubParsersAction) -> None:
    plan = commands.add_parser(
        "plan", help="ask for a plan of reads from the MCP list, approve it, run it")
    plan.add_argument("session_id")
    plan.add_argument("question")


class _Stdio:
    """`plan_flow.PlanView` on the standard streams."""

    def __init__(self, terminal: TtyTerminal) -> None:
        self._terminal = terminal

    def say(self, text: str) -> None:
        print(safe_line(text).text, file=sys.stderr, flush=True)

    def reply(self, text: str) -> None:
        print(prefixed(safe_foreign_text(text).text), flush=True)

    def result(self, header: str, text: str) -> None:
        self.say(header)
        print(prefixed(safe_foreign_text(text).text), flush=True)

    def approval(self, header: list[str], content: list[str]) -> str:
        return "\n".join([*header, APPROVAL_RULE, *(FOREIGN_PREFIX + line for line in content),
                          APPROVAL_RULE])

    @asynccontextmanager
    async def waiting(self) -> AsyncIterator[None]:
        self.say("waiting for the provider (Ctrl+C interrupts; nothing is resent)")
        yield


def run_plan_command(args: argparse.Namespace, *, terminal: TtyTerminal | None = None) -> int:
    question = args.question
    if not question.strip():
        raise UsageError("the question is empty; nothing was sent")
    if len(question) > MAX_QUESTION_CHARS:
        raise UsageError(f"the question has {len(question)} characters; the limit is "
                         f"{MAX_QUESTION_CHARS}; nothing was sent")
    terminal = terminal if terminal is not None else TtyTerminal()
    if not terminal.is_interactive():
        raise UsageError("plan needs an interactive terminal to type the approval code; "
                         "nothing was sent")
    environ = os.environ
    auto_read = auto_read_setting(environ)
    build_catalogue(load_config(environ))  # no read tool, or no list: stop before anything
    settings = Settings.from_env(environ)
    skills = load_skill_settings(environ)
    conn = open_database(settings.data_dir)
    try:
        service = SessionService(conn, settings.data_dir, provider_factory(settings),
                                 settings.provider, settings.request_timeout_s)
        service.recover()
        session, lock = service.take_session(args.session_id)
        try:
            provider = service.provider_for(session)
            bounded = (IN_THIS_SESSION if holds_results(conn, session.session_id) else None)
            setting = PlanSetting(data_dir=settings.data_dir, environ=environ,
                                  load_config=lambda: load_config(environ),
                                  ttl_s=skills.approval_ttl_s, auto_read=auto_read,
                                  bounded_only=bounded)

            async def body():
                await open_resources(provider)
                try:
                    return await run_plan(PlanRequest(question, session.session_id, provider),
                                          service=service, conn=conn, view=_Stdio(terminal),
                                          terminal=terminal, setting=setting)
                finally:
                    await close_resources(provider)

            outcome = asyncio.run(body())
        finally:
            lock.release()
    finally:
        conn.close()
    if outcome.kind == "interrupted":
        return EXIT_INTERRUPTED
    return EXIT_OK if outcome.ok else EXIT_ERROR
