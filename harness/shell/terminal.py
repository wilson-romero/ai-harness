"""Where a person reads and types: one interface for the approval prompt and the conversation.

Tests inject a fake terminal; the real ones read with `input()`. A real terminal cannot be
driven portably from a test (there is no portable pseudo-terminal), so the real classes are kept
as thin as possible and everything else is tested through the interface.
"""

from __future__ import annotations

import asyncio
import contextlib
import getpass
import queue
import sys
import threading
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from harness.shell.render import Row


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


@dataclass(frozen=True)
class ShellState:
    """What a styled terminal may read from the conversation (shell-appearance D5, D6): each
    callable reads the harness's own state at the moment it is called, never foreign text."""

    status: Callable[[], str]  # the status line of the session held now
    resume_count: Callable[[], int]  # how many sessions the last /sessions listed
    skill_names: Callable[[], list[str]]  # folder names with the shape of a skill name
    # shell-tui D4: read in the conversation's own thread only (they query the database).
    panel: Callable[[], PanelState] | None = None  # the side panel of the session held now
    sessions: Callable[[], list[str]] | None = None  # what /sessions lists; sets /resume numbers


@dataclass(frozen=True)
class PanelState:
    """The side panel of the full-screen terminal (shell-tui D4): every field is harness state
    of the session held at the moment it is read, cleaned for a terminal; nothing foreign."""

    session_name: str
    session_id: str  # in full: the first 8 characters of a UUIDv7 are its time
    project: str
    provider: str
    notes: tuple[str, ...]  # memory notes included in the last question (shown names)
    sends: int  # requests of this session that went to the provider
    last_request: str  # status of the last request of this session, or "-"
    mode: str = "auto"  # the session's response mode, and the last confirmed one if it differs


@runtime_checkable
class ApprovalTerminal(Protocol):
    """A terminal that draws the approval notice itself (shell-tui D6). The conversation hands
    it the pieces of the notice it is about to show; the terminal recognises that exact text
    when the engine shows it and draws a box from the pieces instead."""

    def expect_approval(self, shown: str, header: list[str], content: list[str]) -> None: ...


@runtime_checkable
class StyledTerminal(Protocol):
    """A conversation terminal that shows styles, a working indicator and a status line
    (shell-appearance). The conversation uses these only when the terminal has them; any
    other terminal gets the same characters as plain text."""

    def show_rows(self, rows: list[Row]) -> None: ...

    def working(self, label: str) -> AbstractAsyncContextManager[None]: ...

    def bind(self, state: ShellState) -> None: ...


_INTERRUPT = ("interrupt", None)
_POLL_S = 0.1
EOF_GRACE_S = 0.25


class ConsoleTerminal(TtyTerminal):
    """The real terminal of a conversation, over `input()` (D6, measured in task 1.2).

    A line is read in a helper thread only when someone waits for one, and at most one read is
    alive: a read that an interruption leaves waiting stays the only one, and its line goes to
    whoever waits next. The program reads nothing ahead, but the terminal does: what a person
    types while nobody waits (while a skill runs, say) stays in the terminal's own buffer and
    is the next line read, whoever reads it, the approval prompt included. Such a line cannot
    approve (the code comes from a hash not yet shown when it was typed), but it can answer the
    prompt otherwise (design D9, limit of type-ahead, revised 2026-11-25). Emptying that buffer
    would need platform code, which the conversation does not have.

    The SIGINT handler only puts a mark in the queue (`SimpleQueue.put` is reentrant) and never
    raises. An end of input that reaches a read during which an interruption arrived is not
    taken as the end of input; nor is one followed by an interruption within EOF_GRACE_S, the
    order in which a console may deliver them (D6, Windows). A `KeyboardInterrupt` raised in
    the helper thread ends that read only: the next waiter reads again.

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
        """Always leaves one item, whatever ends the read: otherwise `_reading` would stay
        true and no read would ever start again (review 2026-11-25)."""
        item: tuple[str, str | None] = ("eof", None)
        try:
            item = ("line", input())
        except KeyboardInterrupt:
            item = ("again", None)  # the read was interrupted, not ended: read again
        except BaseException:  # noqa: BLE001 - end of input, or a stdin that cannot be read
            item = ("eof", None)
        finally:
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
        if kind == "again" or self._interrupted_read:
            return False  # see the class docstring: not the end of input
        return None

    async def _interrupt_follows(self) -> bool:
        """After an end of input: whether an interruption arrives within EOF_GRACE_S."""
        assert self._wake is not None
        self._wake.clear()
        if self._queue.empty():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), EOF_GRACE_S)
        interrupted = False
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return interrupted
            if item == _INTERRUPT:
                interrupted = True
            else:
                self._held.append(item)

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
                if settled is None and await self._interrupt_follows():
                    print(flush=True)
                    raise WaitInterrupted
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
