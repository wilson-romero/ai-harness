"""A real `main.py chat` process whose terminal is a pipe (test only, never reachable from main.py).

`chat` refuses to run without a terminal, and a pseudo-terminal does not exist on every
platform, so this child runs the same `harness.cli.main(["chat", ...])` with the console
terminal replaced by one that reads lines from stdin. Every prompt is printed as `PROMPT` on its
own line, so the parent knows the conversation is waiting.

Usage: python tests/integration/chat_child.py [chat arguments...]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import harness.shell.app  # noqa: E402
from harness.cli import main  # noqa: E402


class PipeTerminal:
    def is_interactive(self) -> bool:
        return True

    def show(self, text: str) -> None:
        print(text, flush=True)

    def identity(self) -> str:
        return "persona-local"

    def ask(self, question: str) -> str | None:
        print("PROMPT", flush=True)
        line = sys.stdin.readline()
        return line.rstrip("\n") if line else None

    def interrupt_wait(self) -> bool:
        return False

    async def read_line(self, prompt: str) -> str | None:
        print("PROMPT", flush=True)
        line = await asyncio.to_thread(sys.stdin.readline)
        return line.rstrip("\n") if line else None


if __name__ == "__main__":
    harness.shell.app.ConsoleTerminal = PipeTerminal
    sys.exit(main(sys.argv[1:]))
