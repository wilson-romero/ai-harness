"""The full-screen conversation, over Textual (shell-tui D1-D9).

The only module that imports Textual. It draws; it decides nothing. The conversation core
(`Conversation`) runs unchanged in a thread of its own with its own event loop (D2): Textual
owns the main thread and its loop, and the core keeps the blocking approval prompt it has in
every terminal. The two meet in `TuiTerminal`, the core's terminal: the core calls it in its
own thread; the screen calls it in the main thread. Lines, approval answers and Ctrl+C cross
over through queues; what the core shows crosses over as calls posted to the screen's loop.

Containment is the mark of foreign text here (D3): a provider reply, a memory note, a skill
output or an approval content lives only in a bordered block whose title is the harness's own.
Every block is built from the core's rows, which are already cleaned and redacted, as Textual
`Content` objects: their text is never parsed as markup, so `[bold]`, `[link=...]` or
`[@click=...]` in a reply are characters, not styles, links or actions. No widget is focusable
but the inputs, so arriving text never takes the focus.
"""

from __future__ import annotations

import asyncio
import contextlib
import getpass
import os
import queue
import signal
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any, ClassVar

from textual import constants as textual_constants
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.events import Paste
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from harness.shell.completion import PATH, acceptable_path, complete
from harness.shell.render import (
    CONTINUATION_PREFIX,
    FOREIGN,
    FOREIGN_PREFIX,
    GUTTER,
    HARNESS,
    HARNESS_ERROR,
    HARNESS_WARNING,
    MD_BULLET,
    MD_CODE,
    MD_EM,
    MD_FENCE,
    MD_HEADING,
    MD_LINK,
    MD_QUOTE,
    MD_RULE,
    MD_STRONG,
    MIN_COLUMNS,
    STATUS,
    Row,
    harness_rows,
    rows_of_plain_text,
)
from harness.shell.terminal import PanelState, ShellState, WaitInterrupted
from harness.text.safe_text import terminal_safe

APP_TITLE = "ai-harness"
READY_HINT = "Type a question, or / for a command"
BUSY_HINT = "working: ctrl+c interrupts"
FOOTER = "ctrl+p commands  ctrl+c interrupts  ctrl+n new session  ctrl+q leaves"
ARM_S = 0.5  # an approval answer submitted sooner than this after the box opened is refused
HISTORY_MAX = 200  # lines typed at the conversation input, kept in memory only
TICK_S = 1.0
SIDE_COLUMNS = 30
FILE_PICKER_MAX = 500
FOREIGN_TITLE = "text from outside the harness"
APPROVAL_TITLE = "Approval requested"

# Style names of the rows (render.py) to Textual styles. Plain colours only: no style here
# names a link or an action, and no text is ever parsed for a style.
STYLES: dict[str, str] = {
    GUTTER: "dim",
    FOREIGN: "",
    HARNESS: "",
    HARNESS_ERROR: "bold #e06c75",
    HARNESS_WARNING: "#e5c07b",
    STATUS: "bold",
    MD_HEADING: "bold #61afef",
    MD_BULLET: "#c678dd",
    MD_QUOTE: "italic #98c379",
    MD_RULE: "dim",
    MD_FENCE: "dim",
    MD_CODE: "#e5c07b",
    MD_STRONG: "bold",
    MD_EM: "italic",
    MD_LINK: "underline #56b6c2",
}

_INTERRUPT = ("interrupt", None)
_EOF = ("eof", None)
_SESSIONS = ("sessions", None)


def textual_is_quiet() -> bool:
    """Whether Textual, as it read the environment when imported, logs nothing, saves no
    screenshot, presses no key and loads no driver of the environment's (D7)."""
    return (textual_constants.LOG_FILE is None and not textual_constants.DEBUG
            and textual_constants.SCREENSHOT_DELAY < 0 and not textual_constants.PRESS
            and textual_constants.DRIVER is None and not textual_constants.SHOW_RETURN
            and not os.environ.get("TEXTUAL") and not os.environ.get("TEXTUAL_ALLOW_SIGNALS"))


def rows_content(rows: list[Row], *, strip_gutter: bool = False) -> Content:
    """Rows as one Content, line by line. The text is taken as it is: nothing in it is a
    style, a link or an action. `strip_gutter` drops the `| ` of foreign rows, whose mark in
    this terminal is the block that holds them (D3)."""
    parts: list[str | tuple[str, str]] = []
    for number, row in enumerate(rows):
        if number:
            parts.append("\n")
        for style, text in row:
            if strip_gutter and style == GUTTER:
                continue
            parts.append((text, STYLES.get(style, "")))
    return Content.assemble(*parts)


def _is_foreign(row: Row) -> bool:
    return bool(row) and row[0] == (GUTTER, FOREIGN_PREFIX)


def _continues(row: Row) -> bool:
    return bool(row) and row[0] == (GUTTER, CONTINUATION_PREFIX)


def plain(text: str, style: str = "") -> Content:
    """Harness text as Content: never parsed as markup."""
    return Content.assemble((terminal_safe(text), style))


# -- the core's side ---------------------------------------------------------------------------


CORE_CALLS = frozenset({
    "bind_state", "close_approval", "exit", "open_approval", "open_session_picker",
    "set_ready", "set_working", "show_approval_header", "show_panel", "show_rows",
})


class CoreCall(Message):
    """Something the core asks the screen to show; handled in the screen's thread."""

    def __init__(self, method: str, args: tuple[object, ...]) -> None:
        super().__init__()
        self.method = method
        self.args = args


class TuiTerminal:
    """The terminal of a conversation shown full screen (D2). The core calls `read_line`,
    `ask`, `show`, `show_rows`, `working`, `bind` and `expect_approval` in its own thread;
    the screen calls `submit_line`, `answer`, `request_sessions`, `close_input` and
    `interrupt_wait` in the main thread. Nothing is written to disk."""

    def __init__(self) -> None:
        self.app: HarnessApp | None = None
        self._lines: queue.SimpleQueue[tuple[str, str | None]] = queue.SimpleQueue()
        self._answers: queue.SimpleQueue[tuple[str, str | None]] = queue.SimpleQueue()
        self._waiting: str | None = None  # "line" or "ask": what the core waits for now
        self._closing = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._state: ShellState | None = None
        self._approval: tuple[str, list[str], list[str]] | None = None
        self._label: str | None = None  # the provider just asked: the title of its reply
        self._conversation: Any = None

    # -- set up -----------------------------------------------------------------------------

    def full_screen(self, body: Callable[[], int]) -> int:
        """Run `body` (the conversation) behind the screen; see `run_full_screen`."""
        return run_full_screen(self, body)

    @property
    def columns(self) -> int:
        """The width the core cuts its rows to: the conversation pane's, read when the core
        shows something (the screen's size is a value the main thread replaces whole)."""
        app = self.app
        width = app.size.width if app is not None and app.is_running else 80
        return max(MIN_COLUMNS, width - SIDE_COLUMNS - 6)  # the panel, the padding, a border

    def pane_columns(self) -> int:
        return self.columns

    def attach(self, conversation: Any) -> None:
        """The conversation whose `interrupt` Ctrl+C calls (D8)."""
        self._conversation = conversation

    def interrupt(self) -> None:
        """Ctrl+C, from the screen or from a SIGINT handler: never raises."""
        conversation = self._conversation
        if conversation is not None:
            conversation.interrupt()

    def _post(self, method: str, *args: object) -> None:
        """Run `app.<method>(*args)` in the screen, in order, without waiting for it: as a
        message, which Textual takes from any thread and handles in the app's own context.
        Dropped when the screen is gone (the core goes on and ends)."""
        app = self.app
        if app is not None and app.ui_loop is not None:
            with contextlib.suppress(RuntimeError):  # the screen's loop is closed
                app.post_message(CoreCall(method, args))

    # -- the Terminal protocol (the core's thread) ------------------------------------------

    def is_interactive(self) -> bool:
        return True

    def identity(self) -> str:
        return getpass.getuser()

    def show(self, text: str) -> None:
        approval = self._approval
        if approval is not None and text == approval[0]:
            self._post("show_approval_header", approval[1])
            return
        self.show_rows(rows_of_plain_text(text))

    def show_rows(self, rows: list[Row]) -> None:
        label, self._label = self._label, None
        self._post("show_rows", rows, label)

    def bind(self, state: ShellState) -> None:
        self._state = state
        self._post("bind_state", state)

    def expect_approval(self, shown: str, header: list[str], content: list[str]) -> None:
        self._approval = (shown, header, content)

    @contextlib.asynccontextmanager
    async def working(self, label: str) -> AsyncIterator[None]:
        self._post("set_working", terminal_safe(label))
        try:
            yield
            self._label = terminal_safe(label)  # the reply that follows is this provider's
        finally:
            self._post("set_working", None)

    def _refresh_panel(self) -> None:
        state = self._state
        if state is None or state.panel is None:
            return
        try:
            panel = state.panel()
        except Exception:  # noqa: BLE001 - the panel never stops the conversation
            return
        self._post("show_panel", panel)

    def _drop_stale(self, items: queue.SimpleQueue[tuple[str, str | None]]) -> list:
        """Interruptions that arrived before this wait began were meant for something else."""
        kept = []
        while True:
            try:
                item = items.get_nowait()
            except queue.Empty:
                break
            if item != _INTERRUPT:
                kept.append(item)
        for item in kept:
            items.put(item)
        return kept

    async def read_line(self, prompt: str) -> str | None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._approval = None
        self._drop_stale(self._lines)
        if self._closing:
            return None
        self._refresh_panel()
        self._waiting = "line"
        self._post("set_ready", True)
        try:
            while True:
                try:
                    kind, text = self._lines.get_nowait()
                except queue.Empty:
                    self._wake.clear()
                    if self._lines.empty():
                        await self._wake.wait()
                    continue
                if kind == "interrupt":
                    raise WaitInterrupted
                if kind == "eof":
                    return None
                if kind == "sessions":
                    self._offer_sessions()
                    continue
                return text
        finally:
            self._waiting = None
            self._post("set_ready", False)

    def _offer_sessions(self) -> None:
        state = self._state
        if state is None or state.sessions is None:
            return
        try:
            choices = state.sessions()
        except Exception:  # noqa: BLE001 - a picker that cannot list shows nothing
            choices = []
        self._post("open_session_picker", choices)

    def ask(self, question: str) -> str | None:
        """The approval prompt (D6): it blocks the core's thread, as in every terminal, and
        never the screen. Ctrl+C or leaving answers None: undecided."""
        self._drop_stale(self._answers)
        if self._closing:
            return None
        approval = self._approval
        self._waiting = "ask"
        self._post("open_approval", approval[1] if approval else [],
                   approval[2] if approval else [], question)
        try:
            kind, text = self._answers.get()
        finally:
            self._waiting = None
            self._post("close_approval")
        return text if kind == "answer" else None

    # -- the screen's side (main thread) ----------------------------------------------------

    def _notify(self) -> None:
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(wake.set)

    def waiting_for_line(self) -> bool:
        return self._waiting == "line"

    def submit_line(self, line: str) -> bool:
        """A line for the core: taken only while it waits for one (no type-ahead, D6)."""
        if self._waiting != "line":
            return False
        self._lines.put(("line", line))
        self._notify()
        return True

    def request_sessions(self) -> bool:
        if self._waiting != "line":
            return False
        self._lines.put(_SESSIONS)
        self._notify()
        return True

    def answer(self, text: str) -> bool:
        if self._waiting != "ask":
            return False
        self._answers.put(("answer", text))
        return True

    def interrupt_wait(self) -> bool:
        """Called by `Conversation.interrupt`: True if a wait took the interruption. Only puts
        a mark in a queue (reentrant), so a SIGINT handler may call it too."""
        waiting = self._waiting
        if waiting == "line":
            self._lines.put(_INTERRUPT)
            self._notify()
            return True
        if waiting == "ask":
            self._answers.put(_INTERRUPT)
            return True
        return False

    def close_input(self) -> None:
        """Leaving (Ctrl+Q, a signal, the screen gone): every wait now ends as the end of
        input, and a running action is interrupted, so the core closes what it opened."""
        self._closing = True
        busy = self._waiting is None
        self._lines.put(_EOF)
        self._answers.put(_EOF)
        self._notify()
        if busy:
            self.interrupt()


# -- the screen --------------------------------------------------------------------------------


class Block(Static):
    """A block of the conversation: never focusable, never parsed for markup."""

    can_focus = False

    def __init__(self, content: Content, *, classes: str) -> None:
        super().__init__(content, markup=False, classes=classes)


class ForeignBlock(Block):
    """Text from outside the harness, inside its border (D3); the title is the harness's."""

    def __init__(self, rows: list[Row], title: str) -> None:
        super().__init__(rows_content(rows, strip_gutter=True), classes="foreign")
        self.border_title = plain(title)


class SidePanel(Static):
    can_focus = False

    def __init__(self) -> None:
        super().__init__(Content(""), markup=False, id="side")
        self.panel: PanelState | None = None
        self.working: str | None = None

    def show(self) -> None:
        panel = self.panel
        lines: list[str | tuple[str, str]] = []

        def entry(title: str, value: str) -> None:
            lines.extend([(title, "bold"), "\n", (f" {value}", ""), "\n"])

        if panel is None:
            entry("Session", "-")
        else:
            entry("Session", panel.session_name)
            lines.extend([(f" {panel.session_id}", "dim"), "\n"])
            entry("Project", panel.project)
            entry("Provider", panel.provider)
            entry("Memory", f"{len(panel.notes)} note(s) in the last question")
            for note in panel.notes[:20]:
                lines.extend([(f"  {note}", "dim"), "\n"])
            if len(panel.notes) > 20:
                lines.extend([(f"  ... {len(panel.notes) - 20} more", "dim"), "\n"])
            entry("Sends", str(panel.sends))
            entry("Last request", self.working or panel.last_request)
        self.update(Content.assemble(*lines))


class PromptInput(Input):
    """The conversation input: an in-memory history and Tab completion (shell-appearance D6).
    Nothing typed here is written anywhere but the core's queue."""

    BINDINGS: ClassVar = [
        Binding("up", "history(-1)", show=False),
        Binding("down", "history(1)", show=False),
        Binding("tab", "complete", show=False, priority=True),
        Binding("ctrl+d", "end_of_input", show=False),
    ]

    def __init__(self) -> None:
        super().__init__(placeholder=BUSY_HINT, id="prompt")
        self.history: list[str] = []
        self._position = 0
        self.state: ShellState | None = None

    def remember(self, line: str) -> None:
        if line and (not self.history or self.history[-1] != line):
            self.history.append(line)
            del self.history[:-HISTORY_MAX]
        self._position = len(self.history)

    def action_end_of_input(self) -> None:
        """Ctrl+D at an empty input leaves, as at a console; otherwise it deletes."""
        if self.value:
            self.action_delete_right()
        else:
            self.app.action_leave()  # type: ignore[attr-defined]

    def action_history(self, step: int) -> None:
        if not self.history:
            return
        self._position = max(0, min(len(self.history), self._position + step))
        self.value = self.history[self._position] if self._position < len(self.history) else ""
        self.cursor_position = len(self.value)

    def action_complete(self) -> None:
        if self.state is None:
            return
        before = self.value[: self.cursor_position]
        found = complete(before, self.state)
        candidates = list(found.candidates)
        if found.kind == PATH:
            candidates = _path_candidates(found.word)
        if not candidates:
            return
        common = os.path.commonprefix(candidates)
        if len(candidates) == 1 or len(common) > found.length:
            start = len(before) - found.length
            completed = candidates[0] if len(candidates) == 1 else common
            self.value = before[:start] + completed + self.value[self.cursor_position:]
            self.cursor_position = start + len(completed)
        if len(candidates) > 1:
            self.app.notify(plain("  ".join(candidates[:20])), timeout=4)  # type: ignore[arg-type]


def _path_candidates(word: str) -> list[str]:
    folder, _, start = word.rpartition("/")
    base = Path(folder or ".")
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name)[:FILE_PICKER_MAX]
    except OSError:
        return []
    found = []
    for entry in entries:
        if not entry.name.startswith(start):
            continue
        text = (f"{folder}/" if folder else "") + entry.name + ("/" if entry.is_dir() else "")
        if acceptable_path(text):
            found.append(text)
    return found


class CodeInput(Input):
    """The approval answer (D6): its own input, never in the history, never pasted into."""

    def _on_paste(self, event: Paste) -> None:
        event.stop()
        event.prevent_default()
        self.app.notify(plain("Paste is ignored here: type the answer"),  # type: ignore[arg-type]
                        severity="warning", timeout=3)


class ApprovalScreen(ModalScreen[None]):
    """The approval box: harness chrome (title, header from the engine, question) around the
    proposal content in a foreign area. The content rows are the ones the core hashed and
    showed, unchanged (they are never parsed)."""

    BINDINGS: ClassVar = [Binding("escape", "nothing", show=False)]

    def __init__(self, header: list[str], content: list[str], question: str) -> None:
        super().__init__(id="approval")
        self._header = header
        self._content = content
        self._question = question
        self.opened = time.monotonic()

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-box") as box:
            box.border_title = plain(APPROVAL_TITLE)
            yield Static(rows_content(harness_rows(self._header, None)), markup=False,
                         id="approval-header")
            with VerticalScroll(id="approval-content") as area:
                area.border_title = plain("proposed content (from outside the harness)")
                area.can_focus = False
                yield Static(rows_content(rows_of_plain_text("\n".join(self._content)),
                                          strip_gutter=True), markup=False)
            yield Static(plain(self._question, "bold"), markup=False, id="approval-question")
            yield Static(Content(""), markup=False, id="approval-message")
            yield CodeInput(id="approval-input")

    def on_mount(self) -> None:
        self.query_one(CodeInput).focus()

    def action_nothing(self) -> None:
        return

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if time.monotonic() - self.opened < self.app.arm_s:  # type: ignore[attr-defined]
            event.input.value = ""
            self.query_one("#approval-message", Static).update(
                plain("Too soon: read the proposal, then type the answer", STYLES[HARNESS_WARNING]))
            return
        value = event.value
        event.input.value = ""
        self.app.terminal.answer(value)  # type: ignore[attr-defined]


class PickerScreen(ModalScreen[str | None]):
    """A filterable list of harness choices; dismisses with the chosen one (or None)."""

    BINDINGS: ClassVar = [Binding("escape", "cancel", show=False)]

    def __init__(self, title: str, choices: list[str]) -> None:
        super().__init__(classes="picker")
        self._title = title
        self._choices = choices

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box") as box:
            box.border_title = plain(self._title)
            yield Input(placeholder="filter", id="picker-filter")
            yield OptionList(*self._options(""), id="picker-list")

    def _options(self, needle: str) -> list[Option]:
        return [Option(plain(choice), id=str(number))
                for number, choice in enumerate(self._choices)
                if needle.lower() in choice.lower()]

    def on_mount(self) -> None:
        self.query_one("#picker-filter", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        options = self.query_one(OptionList)
        options.clear_options()
        options.add_options(self._options(event.value))
        if options.option_count:
            options.highlighted = 0

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        options = self.query_one(OptionList)
        if options.highlighted is not None and options.option_count:
            self._choose(options.get_option_at_index(options.highlighted))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._choose(event.option)

    def _choose(self, option: Option) -> None:
        assert option.id is not None
        self.dismiss(self._choices[int(option.id)])

    def action_cancel(self) -> None:
        self.dismiss(None)


COMMAND_ENTRIES: tuple[tuple[str, str, str], ...] = (
    # (title, help, what it does: "line:<text>", "insert:<text>" or "<app action>")
    ("Help", "list the commands (/help)", "line:/help"),
    ("Status", "the session held now (/status)", "line:/status"),
    ("New session", "start a new session and leave this one (/new)", "line:/new"),
    ("Switch session...", "pick a session to resume", "pick_session"),
    ("Sessions", "list the sessions (/sessions)", "line:/sessions"),
    ("History", "the messages of this session (/history)", "line:/history"),
    ("Context", "the memory sent with each question (/context)", "line:/context"),
    ("Choose a skill...", "pick a skill to run", "pick_skill"),
    ("Attach a file...", "pick a text file for the next question (/file)", "pick_file"),
    ("Search memory", "search the vault (/memory TERMS)", "insert:/memory "),
    ("Interrupt", "stop the question in progress (ctrl+c)", "interrupt"),
    ("Leave", "close the provider and leave (ctrl+q)", "quit"),
)


class HarnessCommands(Provider):
    """The command palette: the harness's own closed list of commands, nothing else."""

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for title, help_text, what in COMMAND_ENTRIES:
            score = matcher.match(title)
            if score > 0:
                yield Hit(score, matcher.highlight(title), self._run(what), text=title,
                          help=help_text)

    async def discover(self) -> Hits:
        for title, help_text, what in COMMAND_ENTRIES:
            yield DiscoveryHit(plain(title), self._run(what), text=title, help=help_text)

    def _run(self, what: str) -> Callable[[], None]:
        return lambda: self.app.run_entry(what)  # type: ignore[attr-defined]


class HarnessApp(App[int]):
    """The screen (D1). `body` runs the conversation in its own thread and returns its exit
    code; the screen leaves when it returns."""

    TITLE = APP_TITLE
    ENABLE_COMMAND_PALETTE = True
    COMMANDS: ClassVar = {HarnessCommands}
    COMMAND_PALETTE_BINDING = "ctrl+p"
    BINDINGS: ClassVar = [
        Binding("ctrl+c", "interrupt", show=False, priority=True),
        Binding("ctrl+q", "leave", show=False, priority=True),
        Binding("ctrl+n", "new_session", show=False, priority=True),
    ]
    CSS = """
    Screen { layout: vertical; }
    #main { height: 1fr; }
    #log { width: 1fr; padding: 0 1; scrollbar-size-vertical: 1; }
    #side { width: %d; padding: 0 1; border-left: solid $panel-lighten-2; }
    #prompt { dock: bottom; margin: 0 0 1 0; }
    #footer { dock: bottom; height: 1; background: $panel; color: $text-muted; padding: 0 1; }
    #working { height: auto; color: $text-muted; display: none; }
    .you { margin: 1 0 0 0; padding: 0 1; border-left: thick $accent; }
    .harness { color: $text-muted; }
    .foreign { margin: 1 0 0 0; padding: 0 1; border: round $secondary;
               border-title-color: $secondary; border-title-style: bold; }
    #approval { align: center middle; }
    #approval-box { width: 90%%; height: 90%%; border: heavy $warning; padding: 0 1;
                    border-title-color: $warning; border-title-style: bold;
                    background: $surface; }
    #approval-header { height: auto; }
    #approval-content { height: 1fr; border: round $secondary; }
    #approval-question { height: auto; margin: 1 0 0 0; }
    #approval-message { height: auto; }
    .picker { align: center middle; }
    #picker-box { width: 80%%; height: 70%%; border: round $accent; background: $surface; }
    """ % SIDE_COLUMNS

    def __init__(self, terminal: TuiTerminal, body: Callable[[], int], *,
                 arm_s: float = ARM_S) -> None:
        if not textual_is_quiet():
            raise RuntimeError("a Textual debugging switch is set; the conversation is plain")
        super().__init__()
        self.terminal = terminal
        self.arm_s = arm_s
        self._body = body
        self.ui_loop: asyncio.AbstractEventLoop | None = None
        self.state: ShellState | None = None
        self.code: int | None = None
        self.error: BaseException | None = None
        self.core: threading.Thread | None = None
        self.ready = False
        self._working: str | None = None
        self._started = 0.0
        self._leaving = False
        self._approval: ApprovalScreen | None = None
        terminal.app = self

    # -- layout -----------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            yield VerticalScroll(id="log", can_focus=False)
            yield SidePanel()
        yield Static(plain(FOOTER), markup=False, id="footer")
        yield PromptInput()

    def get_system_commands(self, screen: Any) -> Iterator[Any]:
        """No system command (theme, screenshot, keys, quit): only the harness's (D7)."""
        return iter(())

    def save_screenshot(self, *args: object, **kwargs: object) -> str:  # noqa: ARG002
        """Never: a screenshot would put the conversation in a file (D7)."""
        raise RuntimeError("screenshots are disabled in the conversation")

    def on_mount(self) -> None:
        self.ui_loop = asyncio.get_running_loop()
        log = self.query_one("#log", VerticalScroll)
        log.mount(Static(plain(""), markup=False, id="working"))
        self.query_one(PromptInput).focus()
        self.set_interval(TICK_S, self._tick)
        self.core = threading.Thread(target=self._run_core, name="conversation", daemon=True)
        self.core.start()

    def _run_core(self) -> None:
        code = 1
        try:
            code = self._body()
        except BaseException as error:  # noqa: BLE001 - shown after the screen is restored
            self.error = error
        finally:
            self.code = code
            with contextlib.suppress(RuntimeError):
                self.post_message(CoreCall("exit", (code,)))

    def on_core_call(self, message: CoreCall) -> None:
        """Only the methods below, by name: the core never reaches a widget directly."""
        if message.method in CORE_CALLS:
            getattr(self, message.method)(*message.args)

    # -- what the core posts ------------------------------------------------------------------

    def bind_state(self, state: ShellState) -> None:
        self.state = state
        self.query_one(PromptInput).state = state

    def _log(self) -> VerticalScroll:
        return self.query_one("#log", VerticalScroll)

    def _append(self, widget: Static) -> None:
        log = self._log()
        log.mount(widget, before=log.query_one("#working"))
        log.scroll_end(animate=False)

    def show_rows(self, rows: list[Row], label: str | None) -> None:
        """Consecutive rows of one kind make one block: harness rows a plain block, foreign
        rows a bordered one (D3)."""
        group: list[Row] = []
        foreign = False
        for row in [*rows, None]:
            # A row that continues the one above (CONTINUATION_PREFIX) is of its kind.
            if row is not None and group and (_continues(row) or _is_foreign(row) == foreign):
                group.append(row)
                continue
            if group:
                if foreign:
                    self._append(ForeignBlock(group, label or FOREIGN_TITLE))
                else:
                    self._append(Block(rows_content(group), classes="harness"))
            if row is not None:
                group, foreign = [row], _is_foreign(row)

    def show_approval_header(self, header: list[str]) -> None:
        self._append(Block(rows_content(harness_rows(header, None)), classes="harness"))

    def show_panel(self, panel: PanelState) -> None:
        side = self.query_one(SidePanel)
        side.panel = panel
        side.show()

    def set_ready(self, ready: bool) -> None:
        self.ready = ready
        self.query_one(PromptInput).placeholder = READY_HINT if ready else BUSY_HINT

    def set_working(self, label: str | None) -> None:
        self._working = label
        self._started = time.monotonic()
        side = self.query_one(SidePanel)
        side.working = "running" if label else None
        side.show()
        self._tick()

    def _tick(self) -> None:
        working = self.query_one("#working", Static)
        if self._working is None:
            working.display = False
            return
        seconds = int(time.monotonic() - self._started)
        working.update(plain(f"{self._working}: thinking ({seconds} s), ctrl+c interrupts"))
        working.display = True

    def open_approval(self, header: list[str], content: list[str], question: str) -> None:
        screen = ApprovalScreen(header, content, question)
        self._approval = screen
        self.push_screen(screen)

    def close_approval(self) -> None:
        screen, self._approval = self._approval, None
        if screen is not None and screen.is_attached:
            screen.dismiss()

    def open_session_picker(self, choices: list[str]) -> None:
        if not choices:
            self.notify(plain("No sessions."), timeout=3)  # type: ignore[arg-type]
            return

        def chosen(choice: str | None) -> None:
            if choice is not None:
                number = choice[1:4].strip()
                self._submit(f"/resume {number}")

        self.push_screen(PickerScreen("Switch session", choices), chosen)

    # -- what the person does ---------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not isinstance(event.input, PromptInput):
            return
        event.stop()
        line = event.value
        if self._submit(line):
            event.input.remember(line)
            event.input.value = ""

    def _submit(self, line: str) -> bool:
        if self._leaving:
            return False
        if not self.terminal.submit_line(line):
            self.notify(plain("Busy: wait for the answer, or ctrl+c to interrupt"),  # type: ignore[arg-type]
                        severity="warning", timeout=3)
            return False
        if line.strip():
            self._append(Block(plain(line), classes="you"))
        return True

    def action_interrupt(self) -> None:
        self.terminal.interrupt()

    def action_leave(self) -> None:
        if self._leaving:
            self.exit(self.code if self.code is not None else 1)  # a second ctrl+q: now
            return
        self._leaving = True
        self.notify(plain("Leaving: closing the provider"), timeout=5)  # type: ignore[arg-type]
        self.terminal.close_input()

    def action_new_session(self) -> None:
        self._submit("/new")

    def action_command_palette(self) -> None:
        if self._approval is not None:
            return  # never over the approval box
        super().action_command_palette()

    def run_entry(self, what: str) -> None:
        if what.startswith("line:"):
            self._submit(what[len("line:"):])
        elif what.startswith("insert:"):
            prompt = self.query_one(PromptInput)
            prompt.value = what[len("insert:"):]
            prompt.cursor_position = len(prompt.value)
            prompt.focus()
        elif what == "pick_session":
            if not self.terminal.request_sessions():
                self.notify(plain("Busy: wait for the answer"), timeout=3)  # type: ignore[arg-type]
        elif what == "pick_skill":
            names = self.state.skill_names() if self.state is not None else []
            self.push_screen(PickerScreen("Choose a skill", names), self._skill_chosen)
        elif what == "pick_file":
            self.push_screen(PickerScreen("Attach a file", _file_choices()), self._file_chosen)
        elif what == "interrupt":
            self.action_interrupt()
        elif what == "quit":
            self.action_leave()

    def _skill_chosen(self, name: str | None) -> None:
        if name is not None:
            self.run_entry(f"insert:/skill {name} ")

    def _file_chosen(self, path: str | None) -> None:
        if path is not None:
            self._submit(f"/file {path}")


def _file_choices(root: Path | None = None) -> list[str]:
    """Text files under the working folder, as /file takes them; only names completion
    would offer (shown and typed as they are)."""
    root = root or Path()
    found: list[str] = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            path = os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/")
            if not name.startswith(".") and acceptable_path(path):
                found.append(path)
            if len(found) >= FILE_PICKER_MAX:
                return found
    return found


@contextlib.contextmanager
def _signals_to(terminal: TuiTerminal) -> Iterator[None]:
    """SIGINT interrupts like Ctrl+C (D8); SIGTERM and SIGHUP leave like Ctrl+Q, so the
    screen is restored and the provider closed. Handlers never raise."""
    wanted = [(signal.SIGINT, lambda *_: terminal.interrupt())]
    for name in ("SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)  # SIGHUP does not exist everywhere
        if number is not None:
            wanted.append((number, lambda *_: terminal.close_input()))
    previous = []
    for number, handler in wanted:
        with contextlib.suppress(ValueError, OSError):
            previous.append((number, signal.signal(number, handler)))
    try:
        yield
    finally:
        for number, handler in previous:
            signal.signal(number, handler)


CORE_JOIN_S = 30.0  # after the screen is gone: how long the core may take to close


def run_full_screen(terminal: TuiTerminal, body: Callable[[], int]) -> int:
    """Show the screen until the conversation ends; then restore the terminal, close the
    conversation if the screen ended first, and return its exit code."""
    app = HarnessApp(terminal, body)
    with _signals_to(terminal):
        result = app.run()
        if app.core is not None and app.core.is_alive():
            terminal.close_input()
            app.core.join(CORE_JOIN_S)
    if app.error is not None:
        raise app.error
    if result is None:
        return app.return_code or 1
    return result
