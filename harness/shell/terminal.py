"""Where a person reads and types: one interface for the approval prompt and the conversation.

Tests inject a fake terminal; the real ones read with `input()`. A real terminal cannot be
driven portably from a test (there is no portable pseudo-terminal), so the real classes are kept
as thin as possible and everything else is tested through the interface.
"""

from __future__ import annotations

import asyncio
import getpass
import queue
import sys
import threading
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


class WaitInterrupted(Exception):
    """Ctrl+C arrived while the conversation was waiting for a line (D6, D7)."""


class ConversationTerminal(Terminal, Protocol):
    """The terminal of a conversation: the approval interface plus a line wait that does not
    block the event loop, and the entry point of Ctrl+C."""

    async def read_line(self, prompt: str) -> str | None:
        """The next line without its end; None at end of input; raises WaitInterrupted."""
        ...

    def interrupt_wait(self) -> bool:
        """Called from the SIGINT handler: True if a line wait (the conversation's or an
        approval prompt's) was waiting and took the interruption."""
        ...


_INTERRUPT = ("interrupt", None)
_POLL_S = 0.1


class ConsoleTerminal(TtyTerminal):
    """The real terminal of a conversation, over `input()` (D6, measured in task 1.2).

    A line is read in a helper thread only when someone waits for one, and at most one read is
    alive: a read that an interruption leaves waiting stays the only one, and its line goes to
    whoever waits next. Nothing reads ahead, so a line typed while a skill runs cannot answer
    the approval prompt that comes after it. The SIGINT handler only puts a mark in the queue
    (`SimpleQueue.put` is reentrant) and never raises. An end of input that reaches a read
    during which an interruption arrived is not taken as the end of input (D6, Windows).

    Not testable portably (it needs a real terminal): covered by the end-to-end test on a
    pseudo-terminal where one exists and by the manual demo (task 7.6).
    """

    def __init__(self) -> None:
        self._queue: queue.SimpleQueue[tuple[str, str | None]] = queue.SimpleQueue()
        self._held: list[tuple[str, str | None]] = []  # taken from the queue, not used yet
        self._reading = False  # a helper thread is blocked reading; main thread only
        self._interrupted_read = False
        self._waiting = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None

    # -- the helper thread ------------------------------------------------------------------

    def _start_read(self) -> None:
        if self._reading:
            return
        self._reading = True
        self._interrupted_read = False
        threading.Thread(target=self._read, name="conversation-line", daemon=True).start()

    def _read(self) -> None:
        try:
            item: tuple[str, str | None] = ("line", input())
        except Exception:  # noqa: BLE001 - end of input, or a stdin that cannot be read
            item = ("eof", None)
        self._queue.put(item)
        self._notify()

    def _notify(self) -> None:
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:  # the loop is closed: nobody waits any more
                pass

    # -- the main thread ----------------------------------------------------------------------

    def interrupt_wait(self) -> bool:
        if not self._waiting:
            return False
        if self._reading:
            self._interrupted_read = True
        self._queue.put(_INTERRUPT)
        self._notify()
        return True

    def _drop_stale_interrupts(self) -> None:
        """Interruptions that arrived before this wait began were meant for something else."""
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item != _INTERRUPT:
                self._held.append(item)
        self._held = [item for item in self._held if item != _INTERRUPT]

    def _take(self, timeout: float | None) -> tuple[str, str | None] | None:
        if self._held:
            return self._held.pop(0)
        try:
            if timeout is None:
                return self._queue.get_nowait()
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _settle(self, item: tuple[str, str | None]) -> str | None | bool:
        """A line, None for the end of input, or False to keep waiting (a read to restart)."""
        kind, text = item
        self._reading = False
        if kind == "line":
            return text
        if self._interrupted_read:
            return False  # see the class docstring: not the end of input
        return None

    async def read_line(self, prompt: str) -> str | None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._drop_stale_interrupts()
        print(prompt, end="", flush=True)
        self._waiting = True
        try:
            while True:
                item = self._take(None)
                if item is None:
                    self._start_read()
                    self._wake.clear()
                    if self._queue.empty():
                        await self._wake.wait()
                    continue
                if item == _INTERRUPT:
                    print(flush=True)
                    raise WaitInterrupted
                settled = self._settle(item)
                if settled is not False:
                    return settled  # type: ignore[return-value]
        finally:
            self._waiting = False

    def ask(self, question: str) -> str | None:
        """The approval prompt. It blocks the event loop like `skill run` does; Ctrl+C here is
        an undecided answer (D7): nothing is approved and the conversation goes on."""
        self._drop_stale_interrupts()
        print(question, end="", flush=True)
        self._waiting = True
        try:
            while True:
                self._start_read()
                item = self._take(_POLL_S)
                if item is None:
                    continue
                if item == _INTERRUPT:
                    print(flush=True)
                    return None
                settled = self._settle(item)
                if settled is not False:
                    return settled  # type: ignore[return-value]
        finally:
            self._waiting = False
