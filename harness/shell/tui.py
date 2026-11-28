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
import sys
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
from textual.events import Blur, Click, Key, Paste
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from harness.shell.blocks import (
    ALERT,
    HeightOf,
    body_text,
    CONTEXT,
    KEEP_OPEN_TURNS,
    NOTICE,
    REPLY,
    RESULT,
    SKILL,
    Fold,
    category,
    default_fold,
    expanded_footer,
    first_line,
    folds_by_default,
    hidden_footer,
    is_not_shown_notice,
    one_line,
    outline,
    plural,
    preview_lines,
    rows_in_preview,
    turn_has_alert,
    turn_state,
    turn_who,
)
from harness.shell.blocks import FOREIGN as FOREIGN_KIND
from harness.shell.commands import resolve_name
from harness.shell.completion import (
    NONE,
    CompletionData,
    Item,
    Listing,
    Suggestions,
    acceptable_path,
    list_folder,
    suggest,
)
from harness.shell.parser import Command, LineError, parse_line, parse_short
from harness.shell.shortforms import RUNNING, expand, format_command
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
    MD_TABLE,
    MIN_COLUMNS,
    STATUS,
    Row,
    harness_rows,
    row_text,
    rows_of_plain_text,
)
from harness.shell import spacing
from harness.shell.palette import ROLES
from harness.shell.palette import css_variables as palette_css
from harness.shell.terminal import PanelState, ShellState, WaitInterrupted
from harness.skills.approvals import ButtonPress
from harness.text.safe_text import terminal_safe

APP_TITLE = "ai-harness"
OFF = "off in the conversation"
CRASHED = ("ai-harness: the full screen stopped on an internal error; nothing of the "
           "conversation is shown here. The session was released; `chat --plain` works "
           "without the full screen.")
READY_HINT = "Type a question, or / for a command"
BUSY_HINT = "working: ctrl+c interrupts"
BROWSE_HINT = "browsing the blocks: esc or any letter goes back to typing"
# The keys that matter most first: a narrow terminal cuts the end of the line.
FOOTER = ("ctrl+p commands  ctrl+c interrupts  ctrl+q leaves  ctrl+n new  esc blocks  "
          "ctrl+o open/close")
BROWSE_FOOTER = "up/down move  enter open/close  +/- all  end latest  esc back to typing"


def below_hint(rows: int) -> str:
    """The start of the footer while the pane has rows below what it shows (reply-rendering
    D6): harness words and a count, never foreign text."""
    return f"↓ {rows} more {'row' if rows == 1 else 'rows'} below  "
ARM_S = 0.5  # the approval buttons stay disabled this long after the box opens
HISTORY_MAX = 200  # lines typed at the conversation input, kept in memory only
TICK_S = 1.0
# Refreshes a reply just mounted may wait for its layout before the pane decides where to show
# it (reply-rendering D6); past them it is shown from its end, as before.
LAYOUT_WAIT_REFRESHES = 20
PANEL_NOTES = 12
UNCUT = 10_000  # columns the core is told: it cuts no row (D3)
FOREIGN_FRAME = 2 + 2 * spacing.BLOCK_INSET  # a foreign block's border and padding, in columns
FILE_PICKER_MAX = 500
SUGGESTIONS_TITLE = "tab completes · ↑↓ choose · enter takes the chosen · esc closes"
PREVIEW_MAX = 300  # characters of the full command shown under the input
MAX_SHOWN_SUGGESTIONS = 50
TYPED_PENDING_MAX = 1000  # edits whose `Changed` is still on its way, at most
# Folder listings run in daemon threads of their own, at most this many alive: one may be stuck
# on a dead folder while another serves the text typed since. A request that finds them all busy
# waits in one slot, where a newer request replaces it (independent review, 2026-11-27).
MAX_LISTERS = 2
SUGGESTION_COLUMN = 40  # where the harness's words start in a row of the list, at most
FOREIGN_TITLE = "text from outside the harness"
APPROVAL_TITLE = "Approval requested"

# Style names of the rows (render.py) to Textual styles. Theme variables only, through the
# roles of palette.py (tui-spacing D1): no style here names a link or an action, and no text is
# ever parsed for a style. Foreign text never gets a status colour, a fill or reverse.
STYLES: dict[str, str] = {
    GUTTER: "dim",
    FOREIGN: "",
    HARNESS: "",
    HARNESS_ERROR: f"bold {ROLES['error-text']}",
    HARNESS_WARNING: ROLES["warning-text"],
    STATUS: "bold",
    MD_HEADING: f"bold {ROLES['heading-text']}",
    MD_BULLET: ROLES["bullet-text"],
    MD_QUOTE: "italic dim",
    MD_RULE: "dim",
    MD_FENCE: "dim",
    MD_TABLE: "dim",  # the rules of a table or a code block: harness-drawn, no colour, no fill
    # A theme colour no harness status uses: inline code written by the model, such as
    # `warning: ...`, must not look like the harness's own warning (approval-buttons D8).
    MD_CODE: ROLES["code-text"],
    MD_STRONG: "bold",
    MD_EM: "italic",
    MD_LINK: "underline",
}

# The chrome of a folded block (its collapsed line and the footer of a harness block): the one
# style with a background. No style of STYLES has one, and foreign text only ever gets a style
# of STYLES, so no foreign text can look like it (collapsible-blocks D4).
CHROME = f"bold {ROLES['fold-text']} on {ROLES['fold-fill']}"
EXCERPT_STYLE = "italic"
TYPED_MARK = "› "  # before an excerpt of what the person typed
CLOSED = "▸"

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
    "bind_completion", "bind_state", "close_approval", "exit", "open_approval",
    "open_session_picker",
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
        self._answers: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()
        self._waiting: str | None = None  # "line" or "ask": what the core waits for now
        # Taking a line or an answer and closing the wait are one step (review 2026-11-26):
        # the screen handles every key of a fast paste before the core's thread runs again,
        # so the wait must close in the screen's thread when it takes the first line.
        self._state_lock = threading.Lock()
        self._closing = False
        self.hung_up = False  # SIGHUP: the terminal is gone, its streams with it
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

    columns = UNCUT

    def pane_columns(self) -> int:
        """The width the core cuts its rows to: none here (D3). The cut keeps a scrolling
        terminal's own wrapping from starting a row with foreign text; on this screen every
        block is its own region and Textual wraps inside it, so the rows stay whole."""
        return UNCUT

    def layout_columns(self) -> int | None:
        """The text width inside a foreign block now (reply-rendering D1): what a reply's
        tables and code blocks are laid out in. Kept by the screen on every resize; read here
        as one int, so the core never measures a widget."""
        app = self.app
        return app.foreign_width if app is not None else None

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
        # The provider's name titles the foreign text that follows its answer; a harness
        # line in between (a warning of the request) does not use it up (collapsible-blocks).
        label = self._label
        if any(_is_foreign(row) for row in rows):
            self._label = None
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

    def _refresh_completion(self) -> None:
        """The harness data the list under the input offers (command-completion D2), read
        here in the conversation's thread, where the database connection lives."""
        state = self._state
        if state is None or state.completion is None:
            return
        try:
            data = state.completion()
        except Exception:  # noqa: BLE001 - completion never stops the conversation
            return
        self._post("bind_completion", data)

    def _drop_stale(self, items: queue.SimpleQueue[tuple[str, str | None]], *,
                    everything: bool = False) -> list:
        """Interruptions that arrived before this wait began were meant for something else;
        with `everything`, any item is (an answer queued before its box was shown)."""
        kept = []
        while True:
            try:
                item = items.get_nowait()
            except queue.Empty:
                break
            if item != _INTERRUPT and not everything:
                kept.append(item)
        for item in kept:
            items.put(item)
        return kept

    def _arm(self, waiting: str) -> None:
        with self._state_lock:
            self._waiting = waiting

    def _disarm(self, waiting: str) -> None:
        with self._state_lock:
            if self._waiting == waiting:
                self._waiting = None

    def _take(self, waiting: str) -> bool:
        """In the screen's thread: whether the core waits for `waiting`; if so, the wait is
        closed in the same step, so a second line or answer is refused until it reopens."""
        with self._state_lock:
            if self._waiting != waiting:
                return False
            self._waiting = None
            return True

    async def read_line(self, prompt: str) -> str | None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._approval = None
        self._label = None  # a reply's title never outlives its action
        self._drop_stale(self._lines)
        if self._closing:
            return None
        self._refresh_panel()
        self._refresh_completion()
        self._arm("line")
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
            self._disarm("line")
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

    def ask(self, question: str) -> str | None:  # noqa: ARG002
        """No typed answer on the full screen: the approval is asked with buttons
        (`ask_buttons`, approval-buttons D4). Anything that still asks gets None: undecided."""
        return None

    def ask_buttons(self, question: str, approval_hash: str) -> ButtonPress | None:
        """The approval box (shell-tui D6, approval-buttons D1). It blocks the core's thread,
        as every approval prompt does, and never the screen. Only a press of this box, for
        this hash, comes back; Ctrl+C or leaving answer None: undecided."""
        self._drop_stale(self._answers, everything=True)  # no press before its box
        if self._closing:
            return None
        approval = self._approval
        if approval is None or approval_hash not in approval[0]:
            return None  # the box shows the engine's notice for this hash, or nothing opens
        self._arm("ask")
        self._post("open_approval", approval[1], approval[2], approval_hash, question)
        try:
            kind, value = self._answers.get()
        finally:
            self._disarm("ask")
            self._post("close_approval")
        if kind == "press" and isinstance(value, ButtonPress) and \
                value.approval_hash == approval_hash:
            return value
        return None

    # -- the screen's side (main thread) ----------------------------------------------------

    def _notify(self) -> None:
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(wake.set)

    def waiting_for_line(self) -> bool:
        return self._waiting == "line"

    def submit_line(self, line: str) -> bool:
        """A line for the core: one, and only while it waits for one (no type-ahead, D6)."""
        if not self._take("line"):
            return False
        self._lines.put(("line", line))
        self._notify()
        return True

    def request_sessions(self) -> bool:
        """The session list for the picker; the core keeps waiting for a line after it."""
        with self._state_lock:
            if self._waiting != "line":
                return False
            self._lines.put(_SESSIONS)
        self._notify()
        return True

    def press(self, press: ButtonPress) -> bool:
        """One press per box (review 2026-11-26): the wait closes as the press is taken."""
        if not self._take("ask"):
            return False
        self._answers.put(("press", press))  # type: ignore[arg-type]
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


def chrome_line(glyph: str, words: str, excerpt: str, *, foreign: bool,
                typed: bool = False) -> Content:
    """A collapsed line (collapsible-blocks D4): the harness's words in CHROME, a style no
    foreign text can get, then a bounded single-line excerpt behind its mark (`| ` for text
    from outside, `› ` for what the person typed), never in CHROME."""
    parts: list[tuple[str, str]] = [(terminal_safe(f"{glyph} {words} "), CHROME)]
    if excerpt:
        mark = FOREIGN_PREFIX if foreign else TYPED_MARK if typed else ""
        parts.append((" ", ""))
        if mark:
            parts.append((mark, STYLES[GUTTER]))
        parts.append((one_line(excerpt), EXCERPT_STYLE))
    return Content.assemble(*parts)


class FoldBlock(Block):
    """A block of a turn that folds (collapsible-blocks D1-D3): its rows (already cleaned,
    redacted and styled by the core), how they are shown now and whether the person chose
    that. Only the shown part is turned into Content: a collapsed block costs one line."""

    foreign = False

    def __init__(self, rows: list[Row], *, kind: str, who: str, preview: int,
                 classes: str, height_of: HeightOf | None = None) -> None:
        self.rows = rows
        self.kind = kind
        self.who = who
        self.preview = preview
        self.height_of: HeightOf = height_of or (lambda row: 1)
        self.manual = False
        self.truncated = False
        self.renders = 0  # how many times its content was built (the tests count them)
        self.long = folds_by_default(rows, preview, self.height_of)
        self.fold = default_fold(kind, rows, preview, self.height_of)
        super().__init__(Content(""), classes=f"{classes} block")
        self._show()

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def toggleable(self) -> bool:
        return self.foreign or self.total > 1

    @property
    def widget(self) -> FoldBlock:
        return self

    def shown_rows(self) -> int:
        if self.fold is Fold.EXPANDED:
            return self.total
        if self.fold is Fold.PREVIEW:
            return rows_in_preview(self.rows, self.preview, self.height_of)
        return 0

    def hidden_rows(self) -> int:
        """How many rows are not on the screen now: what the footer or the line says."""
        return self.total - self.shown_rows()

    def set_fold(self, fold: Fold, *, manual: bool) -> None:
        if manual:
            self.manual = True
        if fold is not self.fold:
            self.fold = fold
            self._show()

    def toggle(self) -> None:
        """Open shows every row; closed is one line. A folded block opens."""
        self.set_fold(Fold.COLLAPSED if self.fold is Fold.EXPANDED else Fold.EXPANDED,
                      manual=True)

    def add_rows(self, rows: list[Row]) -> None:
        self.rows = self.rows + rows
        self.long = folds_by_default(self.rows, self.preview, self.height_of)
        if not self.manual:
            self.fold = default_fold(self.kind, self.rows, self.preview, self.height_of)
        self._show()

    def mark_truncated(self) -> None:
        self.truncated = True
        self._show()

    def _words(self) -> str:
        words = f"{self.who} · {plural(self.total, 'line')}"
        return words + (" · truncated" if self.truncated else "")

    def summary(self) -> Content:
        raise NotImplementedError

    def body(self, count: int) -> Content:
        raise NotImplementedError

    def _show(self) -> None:
        self.renders += 1
        collapsed = self.fold is Fold.COLLAPSED
        self.set_class(collapsed, "-collapsed")
        self.update(self.summary() if collapsed else self.body(self.shown_rows()))

    def on_click(self, event: Click) -> None:
        """A click on the block's header (its first row) or its footer (its last row)
        toggles it; anywhere else, nothing. It never takes the focus or sends anything."""
        event.stop()
        last = self.outer_size.height - 1
        if self.fold is Fold.COLLAPSED or event.y in (0, last) or not self.foreign:
            self.app.toggle_item(self)  # type: ignore[attr-defined]


class ForeignBlock(FoldBlock):
    """Text from outside the harness, inside its border (D3); the title is the harness's,
    and so is the footer in the bottom border that says how many rows are hidden
    (collapsible-blocks D4): neither border can hold foreign text."""

    foreign = True

    def __init__(self, rows: list[Row], title: str, *, kind: str = FOREIGN_KIND,
                 preview: int = UNCUT, height_of: HeightOf | None = None) -> None:
        super().__init__(rows, kind=kind, who=title, preview=preview, classes="foreign",
                         height_of=height_of)

    def summary(self) -> Content:
        return chrome_line(CLOSED, self._words(), outline(self.rows), foreign=True)

    def body(self, count: int) -> Content:
        return rows_content(self.rows[:count], strip_gutter=True)

    def _show(self) -> None:
        super()._show()
        if self.fold is Fold.COLLAPSED:
            self.border_title = self.border_subtitle = None
            return
        foldable = self.long
        title = self._words() if foldable or self.truncated else self.who
        self.border_title = plain(title)
        hidden = self.hidden_rows()
        footer = (hidden_footer(hidden) if hidden else
                  expanded_footer(self.total) if foldable else None)
        self.border_subtitle = plain(footer) if footer else None


NOTICE_WHO = {CONTEXT: "context", SKILL: "skill steps"}


class NoticeBlock(FoldBlock):
    """Rows of the harness. Folded, its footer is a line of chrome after the rows."""

    def __init__(self, rows: list[Row], *, kind: str, preview: int,
                 height_of: HeightOf | None = None) -> None:
        super().__init__(rows, kind=kind, who=NOTICE_WHO.get(kind, "harness"),
                         preview=preview, classes="harness", height_of=height_of)

    def summary(self) -> Content:
        rows = self.rows
        if self.kind == CONTEXT:  # its own summary line says the most
            rows = [r for r in rows if row_text(r).startswith("context:")] or rows
        elif self.kind == SKILL:  # the newest step says where the run is
            rows = rows[::-1]
        return chrome_line(CLOSED, self._words(), first_line(rows), foreign=False)

    def body(self, count: int) -> Content:
        content = rows_content(self.rows[:count])
        hidden = self.total - count
        if not hidden:
            return content
        return Content.assemble(content, "\n", (hidden_footer(hidden), CHROME))


class Turn(Vertical):
    """A turn of the conversation (collapsible-blocks D2): the line the person sent (none for
    what was shown before the first one) and the blocks shown after it. Closed, the turn is
    its one-line summary."""

    can_focus = False

    def __init__(self, line: str | None) -> None:
        super().__init__(classes="turn")
        self.line = line
        self.closed = False
        self.manual = False
        self.summary_line = Block(Content(""), classes="turn-summary")
        self.you = Block(plain(line), classes="you") if line is not None else None
        self.items: list[FoldBlock] = []

    def mount_header(self) -> None:
        """Mounted right after the turn, before any block: mounts keep their call order,
        whereas `compose` would run later than a block mounted at once."""
        self.mount(self.summary_line, *([self.you] if self.you is not None else []))

    @property
    def toggleable(self) -> bool:
        return self.you is not None or self.closed

    @property
    def widget(self) -> Static:
        return self.summary_line if self.closed or self.you is None else self.you

    def add(self, block: FoldBlock) -> None:
        if self.you is None and not self.items and self.parent is not None \
                and self.parent.children and self.parent.children[0] is self:
            # The first block of a pane starts at its top: the gap is between blocks
            # (tui-spacing D5), never above the first one.
            block.add_class("-lead")
        self.items.append(block)
        self.mount(block)
        if self.closed:
            self.refresh_summary()

    def last(self) -> FoldBlock | None:
        return self.items[-1] if self.items else None

    def total(self) -> int:
        return sum(block.total for block in self.items) + (1 if self.you is not None else 0)

    def _state_lines(self) -> list[str]:
        """The lines a turn's state is read from: the harness's own alerts and skill steps,
        never a block that can carry a vault path or a listing (review 2026-11-27)."""
        return [row_text(row) for block in self.items
                if not block.foreign and block.kind in (ALERT, SKILL, RESULT)
                for row in block.rows]

    @property
    def has_alert(self) -> bool:
        return turn_has_alert(self._state_lines())

    def refresh_summary(self) -> None:
        harness = self._state_lines()
        replies = [block for block in self.items if block.kind == REPLY]
        state = turn_state(harness, bool(replies), any(b.truncated for b in self.items))
        who = turn_who(self.line, replies[-1].who if replies else None)
        words = f"{who} · {plural(self.total(), 'line')} · {state}"
        if self.line is not None:
            excerpt, foreign = self.line, False
        else:
            excerpt = first_line([row for block in self.items for row in block.rows[:1]])
            foreign = bool(self.items) and self.items[0].foreign
        self.summary_line.update(chrome_line(CLOSED, words, excerpt, foreign=foreign,
                                             typed=self.line is not None))

    def set_closed(self, closed: bool, *, manual: bool) -> None:
        if manual:
            self.manual = True
        if closed and not self.items and self.you is None:
            return  # nothing to close
        if closed:
            self.refresh_summary()
        self.closed = closed
        self.set_class(closed, "-closed")

    def toggle(self) -> None:
        self.set_closed(not self.closed, manual=True)

    def on_click(self, event: Click) -> None:
        """A click on the turn's line or its summary opens or closes the turn."""
        if event.widget in (self.summary_line, self.you):
            event.stop()
            self.app.toggle_item(self)  # type: ignore[attr-defined]


class SessionLog(Vertical):
    """The turns of one session, in memory only (collapsible-blocks D5)."""

    can_focus = False

    def __init__(self) -> None:
        super().__init__(classes="session-log")
        self.turns: list[Turn] = []


class ConversationPane(VerticalScroll):
    """The pane of the conversation: on every change of its size the screen measures again
    the width a reply's tables are laid out in (reply-rendering D1)."""

    def on_resize(self) -> None:
        self.app.call_after_refresh(self.app._measure)  # type: ignore[attr-defined]


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
            entry("Mode", panel.mode)
            entry("Sends", str(panel.sends))
            entry("Last request", self.working or panel.last_request)
            entry("Memory", f"{len(panel.notes)} note(s) in the last question")
            for note in panel.notes[:PANEL_NOTES]:
                lines.extend([(f"  {note}", "dim"), "\n"])
            if len(panel.notes) > PANEL_NOTES:
                lines.extend([(f"  ... {len(panel.notes) - PANEL_NOTES} more", "dim"), "\n"])
        self.update(Content.assemble(*lines))


class SuggestionList(OptionList, can_focus=False):
    """The list under the conversation input (command-completion D2). Never focusable: the
    keys stay at the input, which moves the highlight; no row is highlighted until the person
    moves to one, so Enter sends what is typed unless a row was chosen. Rows are Content, never
    markup; each one is a candidate as it would be typed and the harness's words about it."""

    # Its style is in the app's CSS (`#suggestions`), on the spacing scale and the colour roles
    # (tui-spacing D1), which a widget's own DEFAULT_CSS cannot name.

    def __init__(self) -> None:
        super().__init__(id="suggestions", markup=False)
        self.items: list[Item] = []

    def show_items(self, items: list[Item]) -> None:
        self.items = items
        self.clear_options()
        width = min(SUGGESTION_COLUMN, max(len(item.insert.rstrip()) for item in items))
        self.add_options([Option(Content.assemble(
            (item.insert.rstrip(), ""),
            (" " * max(2, width + 2 - len(item.insert.rstrip())) + item.help, "dim")))
            for item in items])
        self.highlighted = None
        self.border_title = plain(SUGGESTIONS_TITLE)
        self.display = True

    def close(self) -> None:
        if not self.items and not self.display:
            return
        self.items = []
        self.clear_options()
        self.display = False

    @property
    def showing(self) -> bool:
        return bool(self.display) and bool(self.items)

    def move(self, step: int) -> None:
        if not self.items:
            return
        if self.highlighted is None:
            self.highlighted = 0 if step > 0 else len(self.items) - 1
        else:
            self.highlighted = (self.highlighted + step) % len(self.items)

    def chosen(self) -> Item | None:
        index = self.highlighted
        return self.items[index] if index is not None and 0 <= index < len(self.items) else None


class FolderLister:
    """Folder listings off the screen's thread, in daemon threads of its own: never in the
    event loop's default executor, which `asyncio.run` waits for at exit (a listing stuck on a
    dead network folder held the exit; independent review, 2026-11-27). At most MAX_LISTERS
    threads are alive; a request that finds them busy waits in one slot, replaced by any newer
    one, and is listed by the first thread that frees. `deliver` is called from those threads
    and must be thread-safe."""

    def __init__(self, deliver: Callable[[int, Listing], None]) -> None:
        self._deliver = deliver
        self._lock = threading.Lock()
        self._live = 0
        self._waiting: tuple[int, str, str] | None = None

    @property
    def live(self) -> int:
        with self._lock:
            return self._live

    def ask(self, generation: int, path: str, prefix: str) -> None:
        request = (generation, path, prefix)
        with self._lock:
            if self._live >= MAX_LISTERS:
                self._waiting = request
                return
            self._live += 1
        threading.Thread(target=self._run, args=(request,), name="completion-listing",
                         daemon=True).start()

    def _run(self, request: tuple[int, str, str] | None) -> None:
        while request is not None:
            generation, path, prefix = request
            try:
                listing = list_folder(path, prefix=prefix)
            except Exception:  # noqa: BLE001 - a listing that fails offers nothing
                listing = Listing()
            with contextlib.suppress(Exception):  # the screen is gone
                self._deliver(generation, listing)
            with self._lock:
                request, self._waiting = self._waiting, None
                if request is None:
                    self._live -= 1


class PromptInput(Input):
    """The conversation input: an in-memory history, the list of completions under it and the
    full command a short form stands for, shown on its lower border (shell-appearance D6,
    command-completion D2-D4). Nothing typed here is written anywhere but the core's queue."""

    BINDINGS: ClassVar = [
        Binding("up", "history(-1)", show=False),
        Binding("down", "history(1)", show=False),
        # Not a priority binding: those run as the app receives the key, before the keys
        # typed just ahead of it reach the input. `_on_key` takes tab first (task 4.8).
        Binding("tab", "complete", show=False),
        Binding("ctrl+d", "end_of_input", show=False),
        # The blocks, from the input (collapsible-blocks D3): the focus never leaves it.
        Binding("alt+up,ctrl+up", "blocks('select', -1)", show=False),
        Binding("alt+down,ctrl+down", "blocks('select', 1)", show=False),
        Binding("ctrl+o", "blocks('toggle')", show=False),
    ]

    # Browsing (Escape): these keys act on the blocks; any other key ends browsing and does
    # what it does at the input, so typing is never lost (collapsible-blocks D3).
    BROWSE_KEYS: ClassVar[dict[str, tuple[str, ...]]] = {
        "up": ("select", -1), "down": ("select", 1),
        "alt+up": ("select", -1), "alt+down": ("select", 1),
        "ctrl+up": ("select", -1), "ctrl+down": ("select", 1),
        "home": ("edge", 0), "end": ("edge", 1),
        "pageup": ("page", -1), "pagedown": ("page", 1),
        "enter": ("toggle",), "space": ("toggle",), "ctrl+o": ("toggle",),
        "plus": ("all", 1), "minus": ("all", 0),
    }

    class Listed(Message):
        """A folder listing, posted from a listing thread (`post_message` is thread-safe and
        never waits, so a thread never blocks on a screen that has gone)."""

        def __init__(self, generation: int, listing: Listing) -> None:
            super().__init__()
            self.generation = generation
            self.listing = listing

    def __init__(self) -> None:
        super().__init__(placeholder=BUSY_HINT, id="prompt")
        self.lister = FolderLister(lambda generation, listing: self.post_message(
            self.Listed(generation, listing)))
        self.history: list[str] = []
        self._position = 0
        self.state: ShellState | None = None
        self.browsing = False
        self._hint = BUSY_HINT
        self.data = CompletionData()
        self.found: Suggestions = NONE
        self.preview = ""  # the full command the line stands for, when it is a short form
        # Values made by a key, a paste or a completion whose `Changed` has not been handled
        # yet: keys written in one go (a fast typist, a terminal) are all applied before the
        # first `Changed` is handled, so a single flag would lose them (found at a real
        # terminal, task 4.8). A value not in here was set by the program.
        self._typed: list[str] = []
        self._editing = False  # inside an edit: its cursor move does not close the list
        self._found_for: str | None = None  # the text before the cursor the list is for
        self._generation = 0  # which request a folder listing answers
        self._tab_waits: int | None = None  # a Tab that waits for a listing to complete
        self.listings = 0  # folder listings started (the tests count them)

    # -- completion (command-completion D2) ------------------------------------------------------

    @property
    def suggestions(self) -> SuggestionList:
        return self.app.query_one(SuggestionList)

    def replace(self, text: str, start: int, end: int) -> None:
        """Every edit of a key or a paste comes through here (Input 8.2.8): only those open
        the list; a value set by the program (the history, the palette, a test) does not."""
        self._edit(lambda: super(PromptInput, self).replace(text, start, end))

    def _edit(self, change: Callable[[], None]) -> bool:
        before = self.value
        self._editing = True
        try:
            change()
        finally:
            self._editing = False
        if self.value == before:
            return False
        self._typed.append(self.value)
        del self._typed[:-TYPED_PENDING_MAX]
        return True

    def watch_selection(self) -> None:
        """The cursor moved without an edit: the list no longer fits it."""
        if not self._editing:
            self.close_suggestions()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._show_preview()
        if event.value in self._typed:
            del self._typed[: self._typed.index(event.value) + 1]
            # The last of a burst: the list follows it, unless a Tab already asked for this
            # very text (its listing may still be on its way).
            if event.value == self.value and \
                    self._found_for != self.value[: self.cursor_position]:
                self.refresh_suggestions()
            return
        self._typed.clear()
        self.close_suggestions()

    def close_suggestions(self) -> None:
        self._generation += 1  # a listing still on its way is not shown
        self._tab_waits = None
        self._found_for = None
        self.found = NONE
        with contextlib.suppress(Exception):  # not mounted yet, or the screen is leaving
            self.suggestions.close()

    def _covered(self) -> bool:
        """Another screen (the approval box, the palette, a picker) is over the input."""
        return self.app.screen is not self.screen

    def refresh_suggestions(self, *, tab: bool = False) -> None:
        """Compute the list for the text before the cursor; list a folder in a thread."""
        self.close_suggestions()
        if self._covered() or self.browsing:
            return
        self._found_for = self.value[: self.cursor_position]
        found = suggest(self._found_for, self.data)
        self.found = found
        if found.path is None:
            self._offer(list(found.items), tab=tab)
            return
        if found.worth_showing():
            self._offer(list(found.items), tab=False)
        generation = self._generation
        self._tab_waits = generation if tab else None
        self.listings += 1
        self.lister.ask(generation, found.path, found.prefix)

    def on_prompt_input_listed(self, message: Listed) -> None:
        message.stop()
        self._listed(message.generation, message.listing)

    def _listed(self, generation: int, listing: Listing) -> None:
        if generation != self._generation or self._covered() or self.browsing:
            return  # the text changed, the list closed or a box is open since it was asked
        tab = self._tab_waits == generation
        self._tab_waits = None
        self._offer(list(self.found.items) + list(listing.items), tab=tab)

    def _offer(self, items: list[Item], *, tab: bool) -> None:
        found = self.found
        if not Suggestions(found.start, found.word, tuple(items)).worth_showing():
            self.suggestions.close()
            return
        if tab:  # Tab takes the top candidate, open list or not (Claude Code does the same)
            self.accept(items[0])
            return
        self.suggestions.show_items(items[:MAX_SHOWN_SUGGESTIONS])

    def accept(self, item: Item) -> None:
        """Put the candidate in place of the word being completed, exactly as it is; nothing
        is sent. The list then follows the new text (a command's arguments, a folder's
        entries)."""
        if not self._put(self.found.start, item.insert):
            self.refresh_suggestions()

    def _put(self, start: int, text: str) -> bool:
        """Replace the text from `start` to the cursor. True if the value changed: its
        `Changed` then follows the new text, as after a key."""
        end = self.cursor_position
        value = self.value[:start] + text + self.value[end:]

        def change() -> None:
            self.value = value
            self.cursor_position = start + len(text)

        return self._edit(change)

    def _show_preview(self) -> None:
        """Under the input, the full command a short form stands for (command-completion D3):
        what Enter would run is on the screen before it is pressed."""
        self.preview = preview_of(self.value, self.data)
        shown = plain(self.preview) if self.preview else None
        # On a short screen the input has only its top rule (tui-spacing D5): the preview goes
        # there, as its title; otherwise on its lower border.
        short = self.screen.has_class("-short")
        self.border_subtitle = None if short else shown
        self.border_title = shown if short else None

    def set_hint(self, hint: str) -> None:
        self._hint = hint
        if not self.browsing:
            self.placeholder = hint

    def set_browsing(self, browsing: bool) -> None:
        if browsing == self.browsing:
            return
        self.browsing = browsing
        self.set_class(browsing, "-browsing")
        self.placeholder = BROWSE_HINT if browsing else self._hint
        self.app.browsing_changed(browsing)  # type: ignore[attr-defined]

    def action_blocks(self, what: str, *args: int) -> None:
        self.app.blocks_action(what, *args)  # type: ignore[attr-defined]

    async def _on_key(self, event: Key) -> None:
        if event.key == "tab" and not self.browsing:
            # Here, in the order of the keys, not as a binding: a binding of a key that came
            # in one write with the keys before it ran late or not at all at a real terminal
            # (task 4.8).
            event.stop()
            event.prevent_default()
            self.action_complete()
            return
        listing = self.suggestions
        if listing.showing and event.key in ("escape", "up", "down", "enter"):
            # The list first (command-completion D4): esc closes it, the arrows move in it,
            # enter takes the chosen row; with no row chosen, enter sends as typed.
            if event.key == "enter":
                chosen = listing.chosen()
                if self._found_for != self.value[: self.cursor_position]:
                    # The list is for older text: keys written in one go with this Enter
                    # have not reached it. Taking its row would drop them; send as typed.
                    chosen = None
                if chosen is not None and chosen.insert.rstrip() != self.found.word:
                    event.stop()
                    event.prevent_default()
                    self.accept(chosen)
                    return
                self.close_suggestions()
                return  # Input's own enter: submit
            event.stop()
            event.prevent_default()
            if event.key == "escape":
                self.close_suggestions()
            else:
                listing.move(-1 if event.key == "up" else 1)
            return
        if not self.browsing:
            if event.key == "escape":
                event.stop()
                event.prevent_default()
                self.set_browsing(True)
                self.app.blocks_action("start")  # type: ignore[attr-defined]
            return
        action = self.BROWSE_KEYS.get(event.key)
        if event.key == "escape" or action is not None:
            event.stop()
            event.prevent_default()
            if event.key == "escape":
                self.set_browsing(False)
            else:
                self.app.blocks_action(*action)  # type: ignore[attr-defined]
            return
        self.set_browsing(False)  # any other key: back to typing, and the key types

    def _on_blur(self, event: Blur) -> None:
        self.set_browsing(False)  # the focus moved to another widget of the screen

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
        """Tab: the chosen row, else the top one; with the list closed, the top candidate of
        the text before the cursor (once a folder is listed, for a path)."""
        if self.browsing or self._covered():
            return
        listing = self.suggestions
        if listing.showing and self._found_for == self.value[: self.cursor_position]:
            self.accept(listing.chosen() or listing.items[0])
            return
        # Closed, or made for text typed since (keys written in one go): computed again now.
        self.refresh_suggestions(tab=True)


def preview_of(value: str, data: CompletionData) -> str:
    """`running: <full command>` when the line is a short form (a cut name, a project's name
    for /new, a path for a skill's only input), as the conversation will expand it with the
    data it had at its last prompt; else empty. Cleaned and bounded: it is harness chrome."""
    if not value.lstrip().startswith("/"):
        return ""
    try:
        parsed = parse_short(value)
        typed = parse_line(value)
    except LineError:
        typed = None
        try:
            parsed = parse_short(value)
        except LineError:
            return ""
    if not isinstance(parsed, Command):
        return ""
    full = expand(parsed, data.known())
    if full == typed:
        return ""
    text = terminal_safe(RUNNING + format_command(full))
    return text if len(text) <= PREVIEW_MAX else text[: PREVIEW_MAX - 1] + "…"


APPROVE_LABEL = "Approve"
REJECT_LABEL = "Reject"
SHOWN_ALL = "The whole proposal has been shown."
NOT_ALL = "{left} more line(s) below: Approve is enabled once the end has been shown."
CONFIRM_REJECT = "Reject this proposal? The run is cancelled and nothing is written."
CONFIRM_YES = "Yes, reject"
CONFIRM_BACK = "Back"
NO_ROOM = ("The window is too small to show the proposal: enlarge it, or use "
           "`chat --plain`. Approve stays disabled.")


class ProposalArea(VerticalScroll):
    """The proposal, inside the approval box: where the focus starts (approval-buttons D2).
    It scrolls and does nothing else: Enter, Space or a click on it never decide."""

    can_focus = True

    def check_message_enabled(self, message: Message) -> bool:
        return (ApprovalScreen.admits(self, message)
                and super().check_message_enabled(message))


class ApprovalButton(Button):
    """A button of the box (approval-buttons D2): it acts only on a press of its own, and only
    once the box is armed. Pasted text goes nowhere. A click counts only if its mouse button
    went down on this button after the arming (approval-buttons D9): the application makes the
    Click itself, with a new stamp, when it handles the MouseUp, even after a MouseDown the box
    dropped."""

    _fresh_down = False

    def check_message_enabled(self, message: Message) -> bool:
        admitted = ApprovalScreen.admits(self, message)  # first: it restarts the silence
        if not (admitted and super().check_message_enabled(message)):
            return False
        if ApprovalScreen.mouse_down(message):
            self._fresh_down = True
        elif isinstance(message, Click):
            fresh, self._fresh_down = self._fresh_down, False
            return fresh
        return True

    def _on_paste(self, event: Paste) -> None:
        event.stop()
        event.prevent_default()


class ApprovalScreen(ModalScreen[None]):
    """The approval box: harness chrome (the engine's header, the state of the reading, the
    buttons) around the proposal content in a foreign area (shell-tui D6, approval-buttons D2).

    The focus starts on the proposal, never on a button. Both buttons stay disabled until the
    box has been painted and then ARM_S has passed with no key, paste or mouse button read
    from the terminal; each one restarts that silence from the moment it was read. An input
    read before the arming never acts, however late the event loop handles it, and disarms the
    box: the silence the arming counted on was not one (approval-buttons D9). The question of
    Reject arms the same way. Approve stays
    disabled until the end of the proposal has been on the screen. Reject asks for a
    confirmation inside the box. Escape does nothing; ctrl+c and ctrl+q leave the approval
    pending."""

    # Blank rows between the parts of the box only where the rows allow (approval-buttons D7).
    VERTICAL_BREAKPOINTS: ClassVar = [(0, "-tight"), (spacing.SNUG_ROWS, "-snug"),
                                      (spacing.ROOMY_ROWS, "-roomy")]
    BINDINGS: ClassVar = [
        Binding("escape", "escape", show=False),
        Binding("pagedown", "scroll_proposal('page_down')", show=False, priority=True),
        Binding("pageup", "scroll_proposal('page_up')", show=False, priority=True),
        Binding("end", "scroll_proposal('end')", show=False, priority=True),
        Binding("home", "scroll_proposal('home')", show=False, priority=True),
    ]

    def __init__(self, header: list[str], content: list[str], approval_hash: str,
                 question: str) -> None:
        super().__init__(id="approval")
        self._header = header
        self._content = content
        self._question = question
        self.approval_hash = approval_hash
        self.opened = self.clock()
        self.armed = False
        self.pressed = False
        self.shown = False  # what it shows now (the box, or Reject's question) is painted
        self.armed_at: float | None = None  # `clock()` when it armed
        self._quiet_from = 0.0  # the silence counts from here: a paint, or an input's read time
        self._arm_timer: Any = None

    @staticmethod
    def clock() -> float:
        """The clock Textual stamps each input event with when its driver reads it
        (`Message.time`). Textual is pinned exactly; a test compares the two."""
        from textual import _time
        return _time.get_time()

    @staticmethod
    def mouse_down(message: Message) -> bool:
        from textual.events import MouseDown
        return isinstance(message, MouseDown)

    @staticmethod
    def _deciding(message: Message) -> bool:
        """An input that can press a button: a key, a paste, a mouse button."""
        from textual.events import MouseDown, MouseUp
        return isinstance(message, (Key, Paste, MouseDown, MouseUp, Click))

    @staticmethod
    def admits(widget: Any, message: Message) -> bool:
        """Whether the box lets an input reach `widget` of it (approval-buttons D9). Before the
        arming every input passes, since no deciding button is enabled, and restarts the
        silence from its read time. After it, an input read before the arming is dropped where
        it is posted, so it reaches no binding and bubbles nowhere, and the box disarms."""
        box = widget if isinstance(widget, ApprovalScreen) else next(
            (node for node in widget.ancestors if isinstance(node, ApprovalScreen)), None)
        if box is None or not ApprovalScreen._deciding(message):
            return True
        if box.armed and box.armed_at is not None and message.time < box.armed_at:
            box._disarm(message.time)
            return False
        if not box.armed:
            box._restart_silence(message.time)
        return True

    def check_message_enabled(self, message: Message) -> bool:
        return super().check_message_enabled(message) and ApprovalScreen.admits(self, message)

    def _forward_event(self, event: Any) -> None:
        # Textual rebuilds a mouse event for the widget under the pointer (`_apply_offset`),
        # with a new stamp: its read stamp is judged here, on the event the driver made.
        if not event.is_forwarded and not ApprovalScreen.admits(self, event):
            return
        super()._forward_event(event)

    @property
    def _key(self) -> tuple[str, ...]:
        return tuple(self._content)

    @property
    def seen_end(self) -> bool:
        return self._key in self.app.seen_proposals  # type: ignore[attr-defined]

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-box") as box:
            box.border_title = plain(APPROVAL_TITLE)
            yield Static(rows_content(harness_rows(self._header, None)), markup=False,
                         id="approval-header")
            with ProposalArea(id="approval-content") as area:
                area.border_title = plain("proposed content (from outside the harness)")
                yield Static(rows_content(rows_of_plain_text("\n".join(self._content)),
                                          strip_gutter=True), markup=False)
            yield Static(plain(""), markup=False, id="approval-more")
            yield Static(plain(self._question, "bold"), markup=False, id="approval-question")
            with Horizontal(id="approval-buttons"):
                yield ApprovalButton(plain(APPROVE_LABEL), id="approve", variant="success",
                                     disabled=True)
                yield ApprovalButton(plain(REJECT_LABEL), id="reject", variant="error",
                                     disabled=True)
            # The confirmation takes the place of the question: its text above, its buttons
            # below, so both buttons stay inside the box at any width (approval-buttons D7).
            with Vertical(id="approval-confirm"):
                yield Static(plain(CONFIRM_REJECT, "bold"), markup=False,
                             id="approval-confirm-text")
                with Horizontal(id="approval-confirm-buttons"):
                    yield ApprovalButton(plain(CONFIRM_BACK), id="reject-back", disabled=True)
                    yield ApprovalButton(plain(CONFIRM_YES), id="reject-yes", variant="error",
                                         disabled=True)

    def on_mount(self) -> None:
        self.query_one("#approval-confirm").display = False
        self.query_one(ProposalArea).focus()
        self.call_after_refresh(self._shown)
        self.set_interval(0.1, self._watch_scroll)
        self.call_after_refresh(self._watch_scroll)

    def _shown(self) -> None:
        """What the box shows has been painted: the silence counts from now (D9)."""
        self.shown = True
        self._restart_silence()
        self._arm_if_quiet()

    def _restart_silence(self, read: float | None = None) -> None:
        self._quiet_from = max(self._quiet_from, self.clock() if read is None else read)

    def _left(self) -> float:
        return self.app.arm_s - (self.clock() - self._quiet_from)  # type: ignore[attr-defined]

    def _arm_later(self, seconds: float) -> None:
        if self._arm_timer is not None:
            self._arm_timer.stop()
            self._arm_timer = None
        if seconds <= 0:  # a Textual timer cannot have a zero interval
            self.call_later(self._arm_if_quiet)
            return
        self._arm_timer = self.set_timer(seconds, self._arm_if_quiet)

    def _arm_if_quiet(self) -> None:
        """Arm once ARM_S has passed since the paint and since the last input was read;
        otherwise look again when it would have passed. One timer at a time."""
        if self.armed or not self.shown:
            return
        left = self._left()
        if left > 0:
            self._arm_later(left)
            return
        self._arm()

    def _arm(self) -> None:
        self.armed = True
        self.armed_at = self.clock()
        self.query_one("#reject", Button).disabled = False
        if self.query_one("#approval-confirm").display:
            self.query_one("#reject-yes", Button).disabled = self.pressed
        self._watch_scroll()

    def _disarm(self, read: float | None = None) -> None:
        """Back to unarmed: the deciding buttons off, the silence counted again from `read`
        (an input's read time) or from now. The next look is by timer, so input already
        queued is handled, unarmed, before it."""
        self.armed = False
        self.armed_at = None
        for name in ("#approve", "#reject", "#reject-yes"):
            self.query_one(name, Button).disabled = True
        self._restart_silence(read)
        self._arm_later(self._left())

    def action_escape(self) -> None:
        """Escape never decides: in the confirmation it is Back, otherwise nothing."""
        if self.query_one("#approval-confirm").display:
            self._confirming(False)

    def action_scroll_proposal(self, how: str) -> None:
        if not self.armed:
            self._restart_silence()  # a key too, though its binding comes before the box
        area = self.query_one(ProposalArea)
        getattr(area, f"scroll_{how}")(animate=False)

    def _watch_scroll(self) -> None:
        """Mark the end as shown once it is on the screen (by keys, the wheel or the bar),
        say how much is left, and enable Approve once armed and shown."""
        area = self.query_one(ProposalArea)
        approve = self.query_one("#approve", Button)
        if not area.size.height:
            # Not laid out yet, or no rows left for it (a small window): nothing is shown.
            if area.is_mounted and self.armed:
                self.query_one("#approval-more", Static).update(plain(NO_ROOM, "bold"))
            approve.disabled = True
            return
        # What is drawn: Textual draws at the rounded position (`scroll_offset`), so a
        # position 0.7 short of the end still hides the last row (review 2026-11-27).
        left = area.max_scroll_y - area.scroll_offset.y
        if left <= 0:
            self.app.seen_proposals.add(self._key)  # type: ignore[attr-defined]
        seen = self.seen_end
        self.query_one("#approval-more", Static).update(
            plain(SHOWN_ALL if seen else NOT_ALL.format(left=left), "bold"))
        approve.disabled = not (self.armed and seen) or self.pressed

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        which = event.button.id
        if which == "reject-back" and not self.pressed:
            self._confirming(False)  # Back never decides: it acts armed or not
            return
        if not self.armed or self.pressed or self.clock() - self.opened < self.app.arm_s:  # type: ignore[attr-defined]
            return
        if which == "approve" and self.seen_end:
            self._send("approve")
        elif which == "reject":
            self._confirming(True)
        elif which == "reject-yes":
            # Armed again since the question appeared: not a second click or a held key of
            # the Reject that opened it, nor input read just after it (D3, D9).
            self._send("reject")

    def _confirming(self, on: bool) -> None:
        """Reject asks once more, inside the box; the focus goes to Back (approval-buttons D3).
        Each change of view disarms the box, which arms again by the same rule once the new
        view is painted (D9)."""
        self.query_one("#approval-buttons").display = not on
        self.query_one("#approval-question").display = not on
        self.query_one("#approval-confirm").display = on
        self.query_one("#reject-back", Button).disabled = not on
        self.shown = False
        self._disarm()
        if on:
            self.query_one("#reject-back", Button).focus()
        else:
            self.query_one(ProposalArea).focus()
        self.call_after_refresh(self._shown)

    def _send(self, choice: str) -> None:
        self.pressed = True
        for button in self.query(Button):
            button.disabled = True
        self.app.terminal.press(  # type: ignore[attr-defined]
            ButtonPress(choice, self.approval_hash))  # type: ignore[arg-type]


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
    ("Browse blocks", "move between the blocks with the arrows (esc)", "browse"),
    ("Open or close the block", "the selected block, or the newest reply (ctrl+o)", "toggle"),
    ("Expand all blocks", "every turn and block of this session open (+ when browsing)",
     "expand_all"),
    ("Collapse all blocks", "every turn of this session as one line (- when browsing)",
     "collapse_all"),
    ("Jump to latest", "the end of the conversation (end when browsing)", "latest"),
    ("Interrupt", "stop the question in progress (ctrl+c)", "interrupt"),
    ("Leave", "close the provider and leave (ctrl+q)", "quit"),
)


BLOCK_ENTRIES: dict[str, tuple[str, ...]] = {
    "toggle": ("toggle",), "expand_all": ("all", 1), "collapse_all": ("all", 0),
    "latest": ("latest",),
}


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
    # The input's bottom margin is the footer's row (both dock at the bottom), not a gap.
    # Two classes on every screen by its size (tui-spacing D2, D5): the side panel only where
    # it fits, and blank rows only where the rows allow.
    HORIZONTAL_BREAKPOINTS: ClassVar = [(0, "-narrow"), (spacing.WIDE_COLUMNS, "-wide")]
    VERTICAL_BREAKPOINTS: ClassVar = [(0, "-short"), (spacing.SNUG_ROWS, "-tall")]
    # The spacing scale and the colour roles first (approval-buttons D7, tui-spacing D1): the
    # rules below name them, never a bare number or a colour of their own.
    CSS = spacing.css_variables() + "\n" + palette_css() + """
    Screen { layout: vertical; }
    #main { height: 1fr; }
    #log { width: 1fr; padding: 0 $edge; scrollbar-size-vertical: 1; }
    #side { width: $side-w; padding: 0 $space-2; border-left: solid $rule; }
    Screen.-narrow #side { display: none; }
    #prompt { dock: bottom; margin: 0 $edge 1 $edge; padding: 0 $inset;
              border-subtitle-color: $chrome-muted; }
    Screen.-short #prompt { height: 2; border: none;
                            border-top: hkey $rule; padding: 0 $space-2; }
    #footer { dock: bottom; height: 1; background: $chrome-fill; color: $chrome-muted;
              padding: 0 $edge; }
    #working { height: auto; color: $chrome-muted; display: none; padding: 0 $space-2; }
    #conversation { height: auto; min-height: 100%; }
    .you { margin: $row 0 0 0; padding: 0 $inset; border-left: thick $you-bar;
           background: $you-fill; }
    .harness { color: $chrome-muted; margin: $row 0 0 0; padding: 0 $space-2; }
    Screen.-short .harness, .harness.-lead { margin: 0; }
    .foreign { margin: $row 0 0 0; padding: 0 $inset; border: round $foreign-frame;
               border-title-color: $foreign-frame; border-title-style: bold;
               border-subtitle-color: $fold-text; border-subtitle-background: $fold-fill;
               border-subtitle-style: bold; }
    .session-log { height: auto; }
    .turn { height: auto; }
    .turn-summary { display: none; margin: $row 0 0 0; padding: 0 $space-2; }
    .turn:first-child > .turn-summary { margin: 0; }
    .turn.-closed > .turn-summary { display: block; }
    .turn.-closed > .you, .turn.-closed > .block { display: none; }
    .turn-summary, .block.-collapsed { height: 1; text-wrap: nowrap; text-overflow: ellipsis; }
    .-selected { background: $select-fill; }
    .foreign.-selected { border: round $select-frame; }
    .foreign.-collapsed, .foreign.-collapsed.-selected { border: none; margin: $row 0 0 0;
                                                         padding: 0 $space-2; }
    #prompt.-browsing { border: tall $browse-frame; }
    /* The completion list (command-completion D2), right above the input and as wide: its
       bottom margin is the rows the input takes under it (3 rows and the footer's row; 2 and
       1 on a short screen), not a gap of the scale. 8 rows of candidates (Codex's popup). */
    #suggestions { dock: bottom; margin: 0 $edge 4 $edge; width: 100%;
                   height: auto; max-height: 10; display: none; border: round $picker-frame; background: $box-fill;
                   border-title-color: $chrome-muted; padding: 0 $inset; }
    Screen.-short #suggestions { margin: 0 $edge 3 $edge; }
    Screen.-short #prompt.-browsing { border: none; border-top: hkey $browse-frame; }
    #approval { align: center middle; }
    #approval-box { width: 90%; height: 90%; border: heavy $approval-frame;
                    padding: 0 $box-x;
                    border-title-color: $approval-frame; border-title-style: bold;
                    background: $box-fill; }
    #approval-header { height: auto; }
    #approval-content { height: 1fr; border: round $foreign-frame; }
    #approval-more { height: auto; }
    #approval-question { height: auto; margin: 0 0 $row 0; }
    #approval-message { height: auto; }
    #approval-buttons, #approval-confirm { dock: bottom; height: auto;
                                           background: $approval-fill; }
    #approval-buttons, #approval-confirm-buttons { height: $button-rows; align: center middle; }
    #approval-confirm-text { width: 1fr; height: auto; text-align: center;
                             margin: 0 0 $row 0; }
    #approval Button { width: $button-w; min-width: $button-w; height: $button-rows;
                       margin: 0; text-style: bold; }
    #approval #reject, #approval #reject-yes { margin: 0 0 0 $button-gap; }
    #approval Button:focus { text-style: bold reverse; }
    #approval Button:disabled { text-style: strike; }
    #approval.-tight #approval-question, #approval.-tight #approval-confirm-text { margin: 0; }
    #approval.-roomy #approval-box { padding: $row $box-x; }
    #approval.-roomy #approval-content { margin: $row 0; }
    .picker { align: center middle; }
    #picker-box { width: 80%; height: 70%; border: round $picker-frame; background: $box-fill;
                  padding: $row $space-2; }
    Screen.-short #picker-box { padding: 0 $space-1; }
    """

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
        self.seen_proposals: set[tuple[str, ...]] = set()  # whose end has been shown
        # The blocks (collapsible-blocks D5): one log per session, in memory only.
        self.session_logs: dict[str, SessionLog] = {}
        self._session_key: str | None = None
        self._session_log: SessionLog | None = None
        self.selected: Turn | FoldBlock | None = None
        self._arriving: FoldBlock | None = None  # the newest reply the pane is placing (D6)
        # The text width inside a foreign block (reply-rendering D1), measured on every resize;
        # until the first, that of an 80-column terminal.
        self.foreign_width = 80 - 2 * spacing.EDGE - FOREIGN_FRAME
        terminal.app = self

    # -- layout -----------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            yield ConversationPane(id="log", can_focus=False)
            yield SidePanel()
        yield Static(plain(FOOTER), markup=False, id="footer")
        yield SuggestionList()
        yield PromptInput()

    def get_system_commands(self, screen: Any) -> Iterator[Any]:
        """No system command (theme, screenshot, keys, quit): only the harness's (D7)."""
        return iter(())

    # Every App method of Textual 8.2.8 that writes a file, opens a URL, reaches the
    # terminal's clipboard or leaves the screen for the shell (app.py:1770, 1844-1950,
    # 4770-4960; review 2026-11-26): none of them may run in the conversation (D7).

    def save_screenshot(self, *args: object, **kwargs: object) -> str:  # noqa: ARG002
        """Never: a screenshot would put the conversation in a file (D7)."""
        raise RuntimeError(OFF)

    def action_screenshot(self, *args: object, **kwargs: object) -> None:  # noqa: ARG002
        self._refused("screenshots")

    def deliver_screenshot(self, *args: object, **kwargs: object) -> None:  # noqa: ARG002
        self._refused("screenshots")

    def deliver_text(self, *args: object, **kwargs: object) -> None:  # noqa: ARG002
        self._refused("saving files")

    def deliver_binary(self, *args: object, **kwargs: object) -> None:  # noqa: ARG002
        self._refused("saving files")

    def open_url(self, *args: object, **kwargs: object) -> None:  # noqa: ARG002
        self._refused("opening links")

    def action_suspend_process(self) -> None:
        self._refused("suspending")

    def copy_to_clipboard(self, text: str) -> None:
        """Inside the screen only: never to the terminal's clipboard (OSC 52)."""
        self._clipboard = text

    def _refused(self, what: str) -> None:
        self.notify(plain(f"{what.capitalize()} is off in the conversation"),  # type: ignore[arg-type]
                    severity="warning", timeout=3)

    # A crash prints a fixed line, never Textual's traceback with local variables, which
    # can hold the text the screen was showing (app.py:3285-3296; review 2026-11-26).

    def _fatal_error(self) -> None:
        self._crash()

    def panic(self, *renderables: object) -> None:  # noqa: ARG002
        self._crash()

    def _crash(self) -> None:
        self._return_code = 1
        self._exit_renderables.append(CRASHED)
        self._close_messages_no_wait()

    def on_mount(self) -> None:
        self.ui_loop = asyncio.get_running_loop()
        log = self.query_one("#log", VerticalScroll)
        # At least as tall as the pane: the anchored pane then never scrolls above its top
        # (Textual sets a negative scroll when the content is shorter than the pane).
        conversation = Vertical(id="conversation")
        log.mount(conversation)
        self._session_log = SessionLog()
        conversation.mount(self._session_log)
        conversation.mount(Static(plain(""), markup=False, id="working"))
        log.anchor()  # the end stays in view as blocks arrive (collapsible-blocks D3)
        self.call_after_refresh(self._measure)
        # The footer says how much is below whenever the pane moves (reply-rendering D6).
        self.watch(log, "scroll_y", lambda: self._show_below(), init=False)
        self.watch(log, "max_scroll_y", lambda: self._show_below(), init=False)
        self.query_one(PromptInput).focus()
        self.set_interval(TICK_S, self._tick)
        self.core = threading.Thread(target=self._run_core, name="conversation", daemon=True)
        self.core.start()

    def _measure(self) -> None:
        """The text width inside a foreign block, for the tables of the next reply."""
        width = self._log().scrollable_content_region.width
        if width:
            self.foreign_width = max(MIN_COLUMNS, width - FOREIGN_FRAME)

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

    def bind_completion(self, data: CompletionData) -> None:
        prompt = self.query_one(PromptInput)
        prompt.data = data
        prompt._show_preview()

    def bind_state(self, state: ShellState) -> None:
        self.state = state
        self.query_one(PromptInput).state = state

    def _log(self) -> VerticalScroll:
        return self.query_one("#log", VerticalScroll)

    def _follow(self, *, force: bool = False) -> None:
        """New output keeps the end of the pane in view (the pane is anchored to its bottom
        while the blocks are laid out), unless the person is browsing the blocks or scrolled
        up to read; sending a line or switching session always goes to the end."""
        log = self._log()
        if force:  # checked first: a line sent while browsing goes to the end too
            self._arriving = None  # a reply not placed yet no longer moves the pane
            log.anchor()
            return
        if self._following():
            log.anchor()

    def _following(self) -> bool:
        """Whether new output may move the pane: the person is not browsing the blocks and
        has not scrolled up to read."""
        log = self._log()
        return not self.query_one(PromptInput).browsing and log.scroll_y >= log.max_scroll_y - 1

    def _show_start(self, block: FoldBlock, waited: int = 0) -> None:
        """A reply just laid out: whole in the pane, the end in view as before; taller than
        the pane, its first line at the top and the footer says how much is below.

        Only the newest reply is placed: one that a newer reply followed before the screen
        refreshed leaves the pane to it. A block not laid out yet measures 0 rows and would
        look as if it fit, so the decision waits for its layout (review 2026-11-27: the first
        refresh can come before it)."""
        log = self._log()
        if not block.is_attached or block is not self._arriving:
            return
        if block.outer_size.height == 0 and waited < LAYOUT_WAIT_REFRESHES:
            self.call_after_refresh(self._show_start, block, waited + 1)
            return
        self._arriving = None
        if block.outer_size.height + spacing.ROW <= log.size.height:
            log.anchor()
            log.scroll_end(animate=False, immediate=True)
        else:
            log.scroll_to_widget(block, animate=False, top=True, immediate=True)
        self._show_below()

    def _show_below(self, browsing: bool | None = None) -> None:
        """The footer, with how many rows of the pane are below what it shows."""
        log = self._log()
        below = max(0, round(log.max_scroll_y - log.scroll_y))
        if browsing is None:
            browsing = self.query_one(PromptInput).browsing
        words = BROWSE_FOOTER if browsing else FOOTER
        self.query_one("#footer", Static).update(plain((below_hint(below) if below else "") + words))

    @property
    def session_log(self) -> SessionLog:
        assert self._session_log is not None
        return self._session_log

    def _turn(self) -> Turn:
        """The turn output goes to: the newest of the session shown (one without a line, for
        what comes before the first line)."""
        log = self.session_log
        if not log.turns:
            self._mount_turn(Turn(None))
        return log.turns[-1]

    def _mount_turn(self, turn: Turn) -> None:
        log = self.session_log
        log.turns.append(turn)
        log.mount(turn)
        turn.mount_header()

    def _preview(self) -> int:
        return preview_lines(self._log().size.height or self.size.height or 24)

    def _height_of(self, foreign: bool) -> HeightOf:
        """The screen rows a row takes in a block of the pane as wide as it is now (a foreign
        block loses its border and padding): Textual's own wrapping of the row's text."""
        width = max(MIN_COLUMNS, (self._log().scrollable_content_region.width
                                  or self.size.width or 80) - (FOREIGN_FRAME if foreign else 0))

        def height_of(row: Row) -> int:
            return max(1, len(Content(body_text(row)).wrap(width)))

        return height_of

    def start_turn(self, line: str) -> None:
        """The person sent `line`: a new turn. Older turns fold to their summary line by
        themselves (D2), except the one before it, one the person opened or closed, the one
        holding the selection and one with an error, a warning or an interruption."""
        turns = self.session_log.turns
        selected_turn = self._turn_of(self.selected)
        for turn in turns[: max(0, len(turns) - (KEEP_OPEN_TURNS - 1))]:
            if not turn.manual and not turn.closed and turn is not selected_turn and \
                    not any(block.manual for block in turn.items) and not turn.has_alert:
                turn.set_closed(True, manual=False)
        self._mount_turn(Turn(line))
        self._follow(force=True)

    def _add_rows(self, rows: list[Row], foreign: bool, label: str | None) -> None:
        turn = self._turn()
        last = turn.last()
        if foreign:
            command = _command_word(turn.line)
            kind = category("", foreign=True, label=label, command=command)
            block = ForeignBlock(rows, label or FOREIGN_TITLE, kind=kind,
                                 preview=self._preview(), height_of=self._height_of(True))
            following = self._following()
            turn.add(block)
            if kind == REPLY and following:
                # The pane stops following the end until the reply is laid out: a reply taller
                # than the pane is shown from its start (reply-rendering D6).
                self._log().release_anchor()
                self._arriving = block
                self.call_after_refresh(self._show_start, block)
                return
        else:
            first = row_text(rows[0]) if rows else ""
            kind = category(first, foreign=False, label=None)
            if is_not_shown_notice(first) and isinstance(last, ForeignBlock):
                last.mark_truncated()
            if isinstance(last, NoticeBlock) and last.kind == kind and kind != ALERT:
                last.add_rows(rows)  # one block for a run of lines of one kind
                if turn.closed:
                    turn.refresh_summary()
            else:
                turn.add(NoticeBlock(rows, kind=kind, preview=self._preview(),
                                     height_of=self._height_of(False)))
        self._follow()

    def show_rows(self, rows: list[Row], label: str | None) -> None:
        """Consecutive rows of one kind make one block: harness rows a plain block, foreign
        rows a bordered one (D3). Each block folds as collapsible-blocks D1 says."""
        group: list[Row] = []
        foreign = False
        for row in [*rows, None]:
            # A row that continues the one above (CONTINUATION_PREFIX) is of its kind.
            if row is not None and group and (_continues(row) or _is_foreign(row) == foreign):
                group.append(row)
                continue
            if group:
                self._add_rows(group, foreign, label)
            if row is not None:
                group, foreign = [row], _is_foreign(row)

    def show_approval_header(self, header: list[str]) -> None:
        self._add_rows(harness_rows(header, None), False, None)

    def show_panel(self, panel: PanelState) -> None:
        side = self.query_one(SidePanel)
        side.panel = panel
        side.show()
        self._follow_session(panel)

    def _follow_session(self, panel: PanelState) -> None:
        """Show the blocks of the session held now (D5): the first panel names the session
        of what was shown so far; another session gets its own log, kept in memory."""
        key = panel.session_id
        if self._session_key is None:
            self._session_key = key
            self.session_logs[key] = self.session_log
            return
        if key == self._session_key:
            return
        self.session_log.display = False
        self._select(None)
        self.query_one(PromptInput).set_browsing(False)
        log = self.session_logs.get(key)
        self._session_key = key
        if log is None:
            log = SessionLog()
            self.session_logs[key] = log
            self._session_log = log
            conversation = self.query_one("#conversation", Vertical)
            conversation.mount(log, before=conversation.query_one("#working"))
            self._add_rows(harness_rows([
                f"session {panel.session_name} ({panel.session_id[:8]}): this pane shows "
                "what happened in it since the conversation opened; /history lists its "
                "stored messages"], None), False, None)
        else:
            self._session_log = log
            log.display = True
        self._follow(force=True)

    # -- the blocks: selection, browsing, folding (collapsible-blocks D3) -----------------------

    def _turn_of(self, item: Turn | FoldBlock | None) -> Turn | None:
        if item is None or isinstance(item, Turn):
            return item
        parent = item.parent
        return parent if isinstance(parent, Turn) else None

    def items(self) -> list[Turn | FoldBlock]:
        """What the selection moves over, in order: the turns and, inside an open turn, its
        blocks that can fold."""
        found: list[Turn | FoldBlock] = []
        for turn in self.session_log.turns:
            if turn.toggleable:
                found.append(turn)
            if not turn.closed:
                found.extend(block for block in turn.items if block.toggleable)
        return found

    @staticmethod
    def _widgets_of(item: Turn | FoldBlock) -> list[Static]:
        if isinstance(item, Turn):
            return [item.summary_line, *([item.you] if item.you is not None else [])]
        return [item]

    def _mark(self) -> None:
        """The highlight on the selection's header, wherever the header is now."""
        item = self.selected
        if item is not None:
            for widget in self._widgets_of(item):
                widget.set_class(widget is item.widget, "-selected")

    def _select(self, item: Turn | FoldBlock | None, *, scroll: bool = True) -> None:
        previous, self.selected = self.selected, item
        if previous is not None:
            for widget in self._widgets_of(previous):
                widget.remove_class("-selected")
        if item is not None:
            self._mark()
            if scroll:
                item.widget.scroll_visible(animate=False)

    def _latest_block(self) -> FoldBlock | None:
        for turn in reversed(self.session_log.turns):
            for block in reversed(turn.items):
                if block.foreign:
                    return block
        return None

    def toggle_item(self, item: Turn | FoldBlock) -> None:
        """Open or close one turn or block: a pure change of the screen. The item's header
        stays where it was on the screen (D3)."""
        if not item.toggleable:
            return
        self._select(item, scroll=False)
        self._keep_in_place(item, item.toggle)
        self._mark()

    def _keep_in_place(self, item: Turn | FoldBlock, change: Callable[[], None]) -> None:
        """Run `change` and scroll so that `item`'s header is where it was in the pane (at
        its top when it was above it)."""
        log = self._log()
        try:
            before = item.widget.region.y - log.region.y
        except Exception:  # noqa: BLE001 - not laid out yet: nothing to keep in place
            change()
            return
        before = max(0, min(before, max(0, log.size.height - 1)))
        change()

        def restore() -> None:
            try:
                after = item.widget.region.y - log.region.y
            except Exception:  # noqa: BLE001 - gone from the screen
                return
            if after != before:
                log.scroll_to(y=max(0, log.scroll_y + after - before), animate=False,
                              immediate=True)

        self.call_after_refresh(restore)

    def _anchor(self) -> Turn | FoldBlock | None:
        """The item the person is reading: the selection, else the first one whose header is
        in the pane."""
        if self.selected is not None:
            return self._turn_of(self.selected) if isinstance(self.selected, FoldBlock) \
                else self.selected
        log = self._log()
        for turn in self.session_log.turns:
            try:
                if turn.widget.region.y >= log.region.y or turn.region.bottom > log.region.y:
                    return turn
            except Exception:  # noqa: BLE001
                continue
        return None

    def set_all(self, opened: bool) -> None:
        """Expand all: every turn open and every block whole. Collapse all: every turn as its
        line. Both are the person's choice, so they stick."""
        def change() -> None:
            for turn in self.session_log.turns:
                if opened:
                    for block in turn.items:
                        block.set_fold(Fold.EXPANDED, manual=True)
                turn.set_closed(not opened, manual=True)

        anchor = self._anchor()
        if isinstance(self.selected, FoldBlock) and not opened:
            self._select(self._turn_of(self.selected))
        if anchor is None:
            change()
        else:
            self._keep_in_place(anchor, change)

    def blocks_action(self, what: str, *args: int) -> None:
        """The keys and palette entries of the blocks. None sends anything or moves the focus."""
        items = self.items()
        if what == "start":
            self._log().release_anchor()  # what arrives now does not move the pane
            if self.selected is None and items:
                self._select(items[-1])
        elif what == "select" and items:
            step = args[0]
            if self.selected not in items:
                self._select(items[-1] if step < 0 else items[0])
            else:
                index = items.index(self.selected) + step
                self._select(items[max(0, min(len(items) - 1, index))])
        elif what == "edge" and items:
            self._select(items[-1] if args[0] else items[0])
            if args[0]:
                self._log().scroll_end(animate=False)
        elif what == "edge":
            self._log().scroll_end(animate=False)
        elif what == "latest":
            if self.query_one(PromptInput).browsing and items:
                self._select(items[-1], scroll=False)
            self._log().anchor()  # and it follows what arrives again
        elif what == "page":
            log = self._log()
            (log.scroll_page_down if args[0] > 0 else log.scroll_page_up)(animate=False)
        elif what == "toggle":
            item = self.selected if self.selected in items else self._latest_block()
            if item is not None:
                self.toggle_item(item)
        elif what == "all":
            self.set_all(bool(args[0]))

    def browsing_changed(self, browsing: bool) -> None:
        if browsing:
            self._arriving = None  # browsing starts: nothing the screen shows moves the pane
        self._show_below(browsing)
        if not browsing:
            self._select(None)

    def set_ready(self, ready: bool) -> None:
        self.ready = ready
        self.query_one(PromptInput).set_hint(READY_HINT if ready else BUSY_HINT)

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

    def push_screen(self, *args, **kwargs):  # type: ignore[override]
        """Any screen over the conversation (the approval box, the palette, a picker) ends
        browsing: Textual sends no Blur to the input it covers (review 2026-11-27)."""
        for prompt in self.query(PromptInput):
            prompt.set_browsing(False)
            prompt.close_suggestions()  # never over a box: the list is the input's
        return super().push_screen(*args, **kwargs)

    def open_approval(self, header: list[str], content: list[str], approval_hash: str,
                      question: str) -> None:
        screen = ApprovalScreen(header, content, approval_hash, question)
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
            self.start_turn(line)
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
            prompt.call_after_refresh(prompt.refresh_suggestions)
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
        elif what == "browse":
            prompt = self.query_one(PromptInput)
            prompt.focus()
            prompt.set_browsing(True)
            self.blocks_action("start")
        elif what in BLOCK_ENTRIES:
            self.blocks_action(*BLOCK_ENTRIES[what])

    def _skill_chosen(self, name: str | None) -> None:
        if name is not None:
            self.run_entry(f"insert:/skill {name} ")

    def _file_chosen(self, path: str | None) -> None:
        if path is not None:
            self._submit(f"/file {path}")


def _command_word(line: str | None) -> str | None:
    """The command of a turn's line, with a cut name read whole (`/con` is `/context`), so
    what `/context` shows is always whole however it was typed (collapsible-blocks D1)."""
    words = line.split() if line else []
    if not words:
        return None
    word = words[0]
    if word.startswith("/") and not word.startswith("//"):
        name = resolve_name(word[1:])
        if name is not None:
            return f"/{name}"
    return word


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
    def hang_up(*_: object) -> None:
        terminal.hung_up = True
        terminal.close_input()

    wanted = [(signal.SIGINT, lambda *_: terminal.interrupt()),
              (signal.SIGTERM, lambda *_: terminal.close_input())]
    number = getattr(signal, "SIGHUP", None)  # SIGHUP does not exist everywhere
    if number is not None:
        wanted.append((number, hang_up))
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


def _streams_to_nowhere() -> None:
    """After a hang-up the terminal is gone: what is still buffered for it, and any message
    on the way out, goes to the null device, so leaving does not fail on a dead stream (the
    exit code 120 of a failed flush; review 2026-11-26)."""
    with contextlib.suppress(OSError, ValueError):
        null = os.open(os.devnull, os.O_WRONLY)
        for stream in (sys.stdout, sys.stderr):
            with contextlib.suppress(OSError, ValueError, AttributeError):
                os.dup2(null, stream.fileno())
        os.close(null)


class FullScreenUnavailable(Exception):
    """Textual loaded but could not drive this console; nothing of the conversation ran."""


def run_full_screen(terminal: TuiTerminal, body: Callable[[], int]) -> int:
    """Show the screen until the conversation ends; then restore the terminal, close the
    conversation if the screen ended first, and return its exit code."""
    app = HarnessApp(terminal, body)
    with _signals_to(terminal):
        try:
            result = app.run()
        except Exception as error:  # noqa: BLE001 - the console driver could not start
            if app.core is None:
                raise FullScreenUnavailable(type(error).__name__) from None
            raise
        if app.core is None:  # the screen never came up: nothing of the conversation ran
            raise FullScreenUnavailable("the screen did not start")
        if app.core.is_alive():
            terminal.close_input()
            app.core.join(CORE_JOIN_S)
    if terminal.hung_up:
        _streams_to_nowhere()
    if app.error is not None:
        raise app.error
    if result is None:
        return app.return_code or 1
    return result
