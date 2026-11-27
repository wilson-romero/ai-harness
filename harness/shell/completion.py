"""What can complete the word at the cursor of the conversation input (command-completion D2).

Pure, except `list_folder`, which lists one folder (names only, never contents). The full
screen draws the result as a list under the input; nothing here sends, runs or reads a file.

Every candidate comes from the harness's own table of commands (commands.py) or from a
snapshot of harness data the conversation hands over between actions (`CompletionData`:
project folder names, skills and their declared inputs, sessions), or from a folder the person
typed. Text from outside that ends up in the list (a folder or file name, a session's title)
is offered only when it shows as it is typed (`acceptable_path`) or is cleaned for the
terminal and cut to a bounded length (`shown`), and there are never more than MAX_ITEMS.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from harness.shell.commands import (
    BY_NAME,
    INPUT_PATH,
    PATH,
    PROJECT,
    PROJECT_OR_NAME,
    SESSION,
    SKILL,
    SKILL_INPUT,
    TABLE,
    CommandSpec,
    resolve_name,
)
from harness.shell.shortforms import Known
from harness.text.safe_text import terminal_safe

MAX_ITEMS = 50  # candidates offered at once
MAX_ITEM_CHARS = 120  # a longer name is not offered (cutting it would insert another name)
MAX_HELP_CHARS = 60  # the harness's words next to a candidate (a title is cut to this)
SCAN_MAX = 100_000  # entries of one folder looked at, at most (50 000 take 0.12 s, measured)
SCAN_S = 0.5  # and for at most this long
MAX_PROJECTS = 500
MAX_SKILLS = 100
MAX_SESSIONS = 100

COMMAND, OPTION, PROJECT_ITEM, SESSION_ITEM, SKILL_ITEM, INPUT_ITEM = (
    "command", "option", "project", "session", "skill", "input")
FOLDER, FILE, LINK = "folder", "file", "link"


def shown(text: str, limit: int = MAX_HELP_CHARS) -> str:
    """Harness-chosen words or a title, as one cleaned line of at most `limit` characters."""
    line = terminal_safe(text)
    return line if len(line) <= limit else line[: limit - 1] + "…"


def acceptable_path(text: str) -> bool:
    """A path offered by completion: no control, format or line separator character (they are
    not shown) and nothing the command line would split or quote (a space, a double quote)."""
    return bool(text) and terminal_safe(text) == text and " " not in text and '"' not in text


# -- the snapshot of harness data ---------------------------------------------------------------


@dataclass(frozen=True)
class SkillChoice:
    name: str
    help: str = ""
    inputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionChoice:
    session_id: str
    project: str
    title: str


@dataclass(frozen=True)
class CompletionData:
    """Harness data for completion, read by the conversation in its own thread between actions
    (the database connection lives there) and handed to the screen."""

    projects: tuple[str, ...] = ()
    skills: tuple[SkillChoice, ...] = ()
    sessions: tuple[SessionChoice, ...] = ()

    def skill(self, name: str) -> SkillChoice | None:
        return next((skill for skill in self.skills if skill.name == name), None)

    def known(self) -> Known:
        """The short forms as this snapshot answers them (the preview under the input)."""
        def inputs(name: str) -> tuple[str, ...] | None:
            skill = self.skill(name)
            return skill.inputs if skill is not None else None

        return Known(is_project=lambda slug: slug in self.projects, skill_inputs=inputs)


# -- what completes -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    insert: str  # replaces the word being completed
    help: str = ""  # the harness's words about it (a kind, a summary, a cleaned title)
    kind: str = ""


@dataclass(frozen=True)
class Suggestions:
    """Replace `word`, which starts at `start` in the line, with an item's `insert`. When
    `path` is not None, the caller lists that path's folder (`list_folder`) and offers what it
    finds after `items`, each behind `prefix` (the NAME= of `--file NAME=PATH`)."""

    start: int = 0
    word: str = ""
    items: tuple[Item, ...] = ()
    path: str | None = None
    prefix: str = ""

    def worth_showing(self, more: tuple[Item, ...] = ()) -> bool:
        """Whether the list has something to offer: not only the word already typed."""
        items = self.items + more
        return bool(items) and not (len(items) == 1 and items[0].insert.rstrip() == self.word)


NONE = Suggestions()


def rank(word: str, items: list[Item], key=lambda item: item.insert) -> list[Item]:  # noqa: ANN001
    """The items whose key starts with `word` (case ignored), in their order, then those that
    hold its letters in order (fuzzy), the tightest first; at most MAX_ITEMS."""
    needle = word.lower()
    first: list[Item] = []
    fuzzy: list[tuple[int, int, int, Item]] = []
    for position, item in enumerate(items):
        text = key(item).lower()
        if text.startswith(needle):
            first.append(item)
            if len(first) >= MAX_ITEMS:
                return first
            continue
        span = _subsequence(needle, text)
        if span is not None:
            fuzzy.append((span[1] - span[0], span[0], position, item))
    fuzzy.sort(key=lambda entry: entry[:3])
    return (first + [entry[3] for entry in fuzzy])[:MAX_ITEMS]


def _subsequence(needle: str, text: str) -> tuple[int, int] | None:
    """Where the letters of `needle` appear in order in `text` (first, last index), or None.
    One pass: linear in the length of `text`."""
    if not needle:
        return (0, 0)
    start = -1
    index = 0
    for position, char in enumerate(text):
        if char == needle[index]:
            if start < 0:
                start = position
            index += 1
            if index == len(needle):
                return (start, position)
    return None


def suggest(before_cursor: str, data: CompletionData) -> Suggestions:
    """What can complete the last word of the text before the cursor."""
    if not before_cursor.startswith("/") or before_cursor.startswith("//") \
            or '"' in before_cursor or "\n" in before_cursor:
        return NONE  # a question, or a quoted word: typed by hand
    head, blank, word = before_cursor.rpartition(" ")
    if not blank:  # the command's own name
        return Suggestions(0, word, tuple(rank(word[1:], _command_items(), _name_of)))
    words = head.split()
    name = resolve_name(words[0][1:]) if words and words[0].startswith("/") else None
    if name is None:
        return NONE
    spec = BY_NAME[name]
    if not spec.takes_arguments:
        return NONE
    start = len(head) + 1
    args = words[1:]
    takes = _position(spec, args)
    if word.startswith("-"):
        return Suggestions(start, word, tuple(rank(word, _option_items(spec))))
    return _for(takes, spec, start, word, args, data)


def _name_of(item: Item) -> str:
    return item.insert.strip()[1:]


def _command_items() -> list[Item]:
    return [Item(f"/{spec.name}" + (" " if spec.takes_arguments else ""), spec.summary, COMMAND)
            for spec in TABLE]


def _option_items(spec: CommandSpec) -> list[Item]:
    return [Item(f"{option.name} ", option.help, OPTION) for option in spec.options]


def _position(spec: CommandSpec, args: list[str]) -> str | None:
    """What the next word takes: an option's value right after the option, else the next
    positional."""
    options = {option.name: option.takes for option in spec.options}
    if args and args[-1] in options:
        return options[args[-1]]
    count = 0
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg in options:
            skip = True
        else:
            count += 1
    if not spec.positional:
        return None
    return spec.positional[min(count, len(spec.positional) - 1)]


def _for(takes: str | None, spec: CommandSpec, start: int, word: str, args: list[str],
         data: CompletionData) -> Suggestions:
    if takes in (PROJECT, PROJECT_OR_NAME):
        if takes == PROJECT_OR_NAME and any(not a.startswith("-") for a in args):
            return NONE  # after the project or the first word of a name: a name, typed
        if takes == PROJECT_OR_NAME and "--project" in args:
            return NONE
        items = [Item(f"{slug} ", "project", PROJECT_ITEM) for slug in data.projects]
        if takes == PROJECT_OR_NAME:
            items += _option_items(spec)
        return Suggestions(start, word, tuple(rank(word, items, lambda i: i.insert.strip())))
    if takes == SESSION:
        if word.isdigit():
            return NONE  # a number of the last /sessions list
        items = [Item(s.session_id, shown(f"{s.project}  {s.title}"), SESSION_ITEM)
                 for s in data.sessions]
        return Suggestions(start, word, tuple(rank(word, items, lambda i: f"{i.insert} {i.help}")))
    if takes == SKILL:
        items = [Item(f"{s.name} ", shown(s.help or "skill"), SKILL_ITEM) for s in data.skills]
        return Suggestions(start, word, tuple(rank(word, items, lambda i: i.insert.strip())))
    if takes in (SKILL_INPUT, INPUT_PATH):
        skill = data.skill(args[0]) if args else None
        inputs = skill.inputs if skill is not None else ()
        if "=" in word:
            if takes == INPUT_PATH:
                prefix = word.partition("=")[0] + "="
                return Suggestions(start, word, (), path=word[len(prefix):], prefix=prefix)
            return NONE  # NAME=VALUE: the value is typed
        items = [Item(f"{name}=", "input", INPUT_ITEM) for name in inputs]
        if takes == SKILL_INPUT:
            items += _option_items(spec)
        ranked = tuple(rank(word, items, lambda i: i.insert))
        one_input = takes == SKILL_INPUT and len(inputs) == 1
        return Suggestions(start, word, ranked, path=word if one_input else None)
    if takes == PATH:
        return Suggestions(start, word, (), path=word)
    return NONE


# -- paths ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Listing:
    items: tuple[Item, ...] = ()
    cut: bool = False  # the folder had more entries than were looked at
    entries: int = 0  # how many entries were looked at
    errors: list[str] = field(default_factory=list)  # kinds of errors met (never shown)


def _split_path(word: str) -> tuple[str, str]:
    """(the folder part as typed, with its separator; the start of the name)."""
    cut = max(word.rfind("/"), word.rfind(os.sep))
    return word[: cut + 1], word[cut + 1:]


def list_folder(word: str, *, prefix: str = "", cwd: Path | None = None,
                home: Path | None = None, limit: int = SCAN_MAX,
                budget_s: float = SCAN_S) -> Listing:
    """The entries of the folder `word` names that complete its last part, as items that
    replace the whole word (behind `prefix`). Names only: no file is opened or read, no
    entry is followed through a link (a link is offered as a name, never as a folder), at
    most `limit` entries for at most `budget_s` seconds. A folder that cannot be listed gives
    nothing, without an error. `~/` lists the home folder and stays `~/` in the text."""
    folder_text, start = _split_path(word)
    if word == "~":
        return Listing((Item(prefix + "~/", "home folder", FOLDER),))
    try:
        base = _base(folder_text, cwd, home)
    except (OSError, RuntimeError, ValueError):
        return Listing(errors=["home"])
    found: list[tuple[str, str]] = []  # (name, kind)
    entries = 0
    cut = False
    deadline = time.monotonic() + budget_s
    errors: list[str] = []
    try:
        with os.scandir(base) as scan:
            for entry in scan:
                entries += 1
                if entries > limit or time.monotonic() > deadline:
                    cut = True
                    break
                name = entry.name
                if name.startswith(".") and not start.startswith("."):
                    continue
                try:
                    if entry.is_symlink() or entry.is_junction():
                        kind = LINK
                    elif entry.is_dir(follow_symlinks=False):
                        kind = FOLDER
                    else:
                        kind = FILE
                except OSError:
                    continue
                found.append((name, kind))
    except (OSError, ValueError) as error:  # missing, not a folder, no permission, a NUL
        errors.append(type(error).__name__)
    items = []
    for name, kind in found:
        text = folder_text + name + ("/" if kind == FOLDER else "")
        if len(text) <= MAX_ITEM_CHARS and acceptable_path(text):
            help_text = "link, not followed" if kind == LINK else kind
            items.append(Item(prefix + text, help_text, kind))
    items.sort(key=lambda item: (item.kind != FOLDER, item.insert.lower()))
    ranked = rank(start, items,
                  key=lambda item: _split_path(item.insert[len(prefix):].rstrip("/"))[1])
    return Listing(tuple(ranked), cut, min(entries, limit), errors)


def _base(folder_text: str, cwd: Path | None, home: Path | None) -> Path:
    here = cwd if cwd is not None else Path.cwd()
    if folder_text.startswith(("~/", "~" + os.sep)):
        return (home if home is not None else Path.home()) / folder_text[2:]
    if not folder_text:
        return here
    path = Path(folder_text)
    return path if path.is_absolute() else here / path
