"""The styled conversation terminal, over prompt_toolkit (shell-appearance D1-D7).

The only module that imports prompt_toolkit. Input: line editing, an in-memory history of the
lines typed at the conversation prompt, Tab completion of /commands and a status line under
the prompt. Output: the conversation's rows in colour, through prompt_toolkit's output (which
also drives the legacy Windows console). The plain `ConsoleTerminal` stays the fallback.

What must hold as in the plain terminal (shell-appearance D7):

- Ctrl+C. While a prompt is open the terminal is in raw mode: Ctrl+C is a key, not a signal,
  and its default binding ends the prompt with KeyboardInterrupt, which is turned into what the
  plain terminal does (WaitInterrupted at the conversation prompt, an undecided None at the
  approval prompt). prompt_toolkit's own SIGINT handler is never installed
  (`handle_sigint=False`), so the conversation's handler (D6) stays in place; while no prompt is
  open (the provider works) the terminal is in cooked mode and Ctrl+C is the SIGINT that handler
  turns into the cancellation of the question, as before. A SIGINT that arrives while a prompt
  is open (sent by another process) ends the prompt like the key does (`interrupt_wait`).
- The approval prompt: a fresh prompt session each time, without history, completion or status
  line, so the code typed there is never kept or offered again. It runs in a helper thread
  (`in_thread=True`) because the engine asks synchronously from inside the event loop, which
  blocks like the plain prompt does.
- Nothing runs a command or opens an editor: system prompt, suspend and open-in-editor are off.
"""

from __future__ import annotations

import asyncio
import contextlib
import getpass
import sys
import time
from collections.abc import AsyncIterator, Iterable

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.completion import CompleteEvent, Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.input import Input, create_input
from prompt_toolkit.output import Output, create_output
from prompt_toolkit.shortcuts import print_formatted_text
from prompt_toolkit.styles import Style

from harness.shell.completion import PATH, acceptable_path, complete
from harness.shell.render import Row, rows_of_plain_text, wrap_rows
from harness.shell.terminal import ShellState, WaitInterrupted

STYLE = Style.from_dict({
    "gutter": "ansibrightblack",
    "foreign": "",
    "harness": "ansicyan",
    "harness.error": "ansired bold",
    "harness.warning": "ansiyellow",
    "status": "ansicyan bold",
    "working": "ansibrightblack italic",
    "prompt": "ansigreen bold",
    "md.heading": "bold underline",
    "md.bullet": "ansiyellow",
    "md.quote": "ansibrightblack",
    "md.rule": "ansibrightblack",
    "md.fence": "ansibrightblack",
    "md.code": "ansigreen",
    "md.strong": "bold",
    "md.em": "italic",
    "md.link": "underline",
})
TICK_S = 1.0


def _fragments(rows: list[Row]) -> FormattedText:
    fragments: list[tuple[str, str]] = []
    for index, row in enumerate(rows):
        if index:
            fragments.append(("", "\n"))
        fragments += [(f"class:{style}", text) for style, text in row]
    return FormattedText(fragments)


class ShellCompleter(Completer):
    """`complete` for prompt_toolkit; paths of /file from the disk, filtered."""

    def __init__(self, state: ShellState | None) -> None:
        self.state = state
        self._paths = PathCompleter(expanduser=False)

    def get_completions(self, document: Document,
                        complete_event: CompleteEvent) -> Iterable[Completion]:
        if self.state is None:
            return
        found = complete(document.text_before_cursor, self.state)
        if found.kind == PATH:
            word = Document(found.word, len(found.word))
            for item in self._paths.get_completions(word, complete_event):
                whole = found.word[:len(found.word) + item.start_position] + item.text
                if acceptable_path(whole):
                    yield Completion(item.text, item.start_position)
            return
        for candidate in found.candidates:
            yield Completion(candidate, -found.length)


class StyledConsoleTerminal:
    """The conversation terminal with colours, editing, history and completion."""

    def __init__(self, input: Input | None = None, output: Output | None = None) -> None:
        self._input = input if input is not None else create_input()
        self._output = output if output is not None else create_output()
        self._state: ShellState | None = None
        self._completer = ShellCompleter(None)
        self._session: PromptSession[str] = PromptSession(
            history=InMemoryHistory(),  # never a file: what a person types is not stored
            completer=self._completer,
            complete_while_typing=False,  # Tab asks for it
            bottom_toolbar=self._toolbar,
            **self._safe_options(),
        )
        self._active: Application | None = None  # the prompt open now, if any
        self._early_interrupt = False

    def _safe_options(self) -> dict:
        return dict(input=self._input, output=self._output, enable_system_prompt=False,
                    enable_suspend=False, enable_open_in_editor=False, mouse_support=False)

    # -- the approval interface -------------------------------------------------------------

    def is_interactive(self) -> bool:
        return sys.stdin.isatty() and sys.stdout.isatty()

    def identity(self) -> str:
        return getpass.getuser()

    def show(self, text: str) -> None:
        """Text already cut into rows and marked (the approval notice, the engine's lines)."""
        self.show_rows(rows_of_plain_text(text))

    def ask(self, question: str) -> str | None:
        """The approval prompt: None for Ctrl+C or end of input, both undecided (D7)."""
        session: PromptSession[str] = PromptSession(history=InMemoryHistory(),
                                                    **self._safe_options())
        self._open(session.app)
        try:
            return session.prompt(question, in_thread=True, handle_sigint=False,
                                  set_exception_handler=False,
                                  pre_run=self._interrupt_if_asked)
        except (KeyboardInterrupt, EOFError):
            return None
        finally:
            self._active = None

    # -- the conversation ------------------------------------------------------------------

    def bind(self, state: ShellState) -> None:
        self._state = state
        self._completer.state = state

    def _toolbar(self) -> FormattedText:
        status = self._state.status() if self._state is not None else "ai-harness"
        return FormattedText([("class:status", f" {status} ")])

    async def read_line(self, prompt: str) -> str | None:
        self._open(self._session.app)
        try:
            return await self._session.prompt_async(
                FormattedText([("class:prompt", prompt)]), handle_sigint=False,
                set_exception_handler=False, pre_run=self._interrupt_if_asked,
            )
        except KeyboardInterrupt:
            raise WaitInterrupted from None
        except EOFError:
            return None
        finally:
            self._active = None

    def _open(self, app: Application) -> None:
        self._early_interrupt = False
        self._active = app

    def _interrupt_if_asked(self) -> None:
        """A SIGINT that came before the prompt was running ends it as soon as it runs."""
        app = self._active
        if self._early_interrupt and app is not None:
            self._early_interrupt = False
            # `pre_run` runs before the application has its future: end it once it has one.
            asyncio.get_running_loop().call_soon(self._exit_when_running, app, 100)

    def _exit_when_running(self, app: Application, tries: int) -> None:
        if app.future is not None:
            self._exit(app)
        elif tries > 0:
            asyncio.get_running_loop().call_later(0.01, self._exit_when_running, app, tries - 1)

    def interrupt_wait(self) -> bool:
        """From the SIGINT handler (D6): end the open prompt as Ctrl+C would. Never raises."""
        app = self._active
        if app is None:
            return False
        loop = app.loop
        if loop is None or app.future is None:  # not running yet: ends it when it starts
            self._early_interrupt = True
            return True
        try:
            loop.call_soon_threadsafe(self._exit, app)
        except RuntimeError:  # its loop is closed: the prompt is over
            pass
        return True

    @staticmethod
    def _exit(app: Application) -> None:
        if app.future is not None and not app.future.done():
            app.exit(exception=KeyboardInterrupt())

    def show_rows(self, rows: list[Row]) -> None:
        print_formatted_text(_fragments(rows), style=STYLE, output=self._output,
                             include_default_pygments_style=False)

    @contextlib.asynccontextmanager
    async def working(self, label: str) -> AsyncIterator[None]:
        """`label … thinking (N s)` on one line while the provider works, erased after."""
        ticker = asyncio.ensure_future(self._tick(label))
        try:
            yield
        finally:
            ticker.cancel()
            self._output.write("\r")
            self._output.erase_end_of_line()
            self._output.flush()

    async def _tick(self, label: str) -> None:
        started = time.monotonic()
        while True:
            seconds = int(time.monotonic() - started)
            text = f"{label} … thinking ({seconds} s), Ctrl+C interrupts"
            columns = self._output.get_size().columns
            text = wrap_rows(text, columns)[0]  # one row: \r only returns to its start
            self._output.write("\r")
            print_formatted_text(FormattedText([("class:working", text)]), end="", style=STYLE,
                                 output=self._output, include_default_pygments_style=False)
            self._output.erase_end_of_line()
            self._output.flush()
            await asyncio.sleep(TICK_S)
