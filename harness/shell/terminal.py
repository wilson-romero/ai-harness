"""Where a person reads and types: one interface for the approval prompt and the conversation.

Tests inject a fake terminal; the real ones read with `input()`. A real terminal cannot be
driven portably from a test (there is no portable pseudo-terminal), so the real classes are kept
as thin as possible and everything else is tested through the interface.
"""

from __future__ import annotations

import getpass
import sys
from typing import Protocol


class Terminal(Protocol):
    """Where a person sees a proposal and answers. Tests inject a fake one."""

    def is_interactive(self) -> bool: ...

    def show(self, text: str) -> None: ...

    def ask(self, question: str) -> str | None:  # None: end of input
        ...

    def identity(self) -> str: ...


class TtyTerminal:
    """The only object that reads stdin to decide an approval."""

    def is_interactive(self) -> bool:
        return sys.stdin.isatty() and sys.stdout.isatty()

    def show(self, text: str) -> None:
        print(text, flush=True)

    def ask(self, question: str) -> str | None:
        try:
            return input(question)
        except EOFError:
            return None

    def identity(self) -> str:
        return getpass.getuser()
