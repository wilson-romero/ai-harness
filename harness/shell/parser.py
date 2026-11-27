"""What a conversation line is (interactive-shell D3).

A line whose first non-blank character is `/` is a command (invisible format characters count
as blank): a name from a closed list and
arguments separated by blanks, with double quotes around an argument that holds blanks. `//`
at the start escapes the slash: the line is a question that starts with one `/`. Every other
line that is not blank is a question. An unknown or malformed command is an error of the
conversation, never a question: a mistyped command cannot reach the provider.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from harness.shell.commands import TABLE, names_starting, resolve_name
from harness.text.safe_text import terminal_safe

# name -> (minimum, maximum or None) number of arguments, from the one table (commands.py).
COMMANDS: dict[str, tuple[int, int | None]] = {spec.name: (spec.least, spec.most)
                                               for spec in TABLE}
_SHOWN_NAME_CHARS = 40


class LineError(Exception):
    """A command line that is not a valid command. The message is safe to print."""


@dataclass(frozen=True)
class Question:
    text: str


@dataclass(frozen=True)
class Command:
    name: str
    args: tuple[str, ...]


@dataclass(frozen=True)
class Empty:
    pass


def _blank(char: str) -> bool:
    """White space, or an invisible format character (a zero-width space, a BOM): before a
    `/` it must not turn a command into a question that would be sent (review 2026-11-25)."""
    return char.isspace() or unicodedata.category(char) == "Cf"


def parse_line(line: str) -> Question | Command | Empty:
    """A line as typed in full: a command's name must be whole."""
    return _parse(line, short=False)


def parse_short(line: str) -> Question | Command | Empty:
    """A line where a command's name may be shortened to its start when only one command starts
    so (command-completion D3): `/sk` is `/skill`. An ambiguous start is an error that names
    the commands it could be. Everything else is `parse_line`."""
    return _parse(line, short=True)


def _parse(line: str, *, short: bool) -> Question | Command | Empty:
    line = line.rstrip("\r\n")
    start = 0
    while start < len(line) and _blank(line[start]):
        start += 1
    stripped = line[start:].strip()
    if not stripped:
        return Empty()
    if stripped.startswith("//"):
        return Question(stripped[1:])
    if not stripped.startswith("/"):
        return Question(line)
    rest = stripped[1:]
    words = _split(rest)
    name = words[0] if words and not rest[:1].isspace() else ""
    if short and name not in COMMANDS and name:
        resolved = resolve_name(name)
        if resolved is None and len(names_starting(name)) > 1:
            shown = terminal_safe(name)[:_SHOWN_NAME_CHARS]
            raise LineError(f"/{shown} is the start of more than one command: "
                            + ", ".join(f"/{n}" for n in names_starting(name)))
        name = resolved or name
    if name not in COMMANDS:
        shown = terminal_safe(name)[:_SHOWN_NAME_CHARS]
        raise LineError(f"unknown command /{shown}; /help lists the commands")
    args = tuple(words[1:])
    least, most = COMMANDS[name]
    if len(args) < least or (most is not None and len(args) > most):
        if least == most:
            expected = str(least)
        elif most is None:
            expected = f"at least {least}"
        else:
            expected = f"{least} to {most}"
        raise LineError(f"/{name} takes {expected} argument(s), got {len(args)}; see /help")
    return Command(name, args)


def _split(text: str) -> list[str]:
    """Blank-separated words; `"…"` groups blanks into one word. One pass, no backtracking."""
    words: list[str] = []
    current: list[str] = []
    in_word = in_quotes = False
    for char in text:
        if in_quotes:
            if char == '"':
                in_quotes = False
            else:
                current.append(char)
        elif char == '"':
            in_quotes = in_word = True
        elif char.isspace():
            if in_word:
                words.append("".join(current))
                current, in_word = [], False
        else:
            current.append(char)
            in_word = True
    if in_quotes:
        raise LineError("a double quote is not closed")
    if in_word:
        words.append("".join(current))
    return words
