"""Short forms of the commands and the full command they stand for (command-completion D3).

`expand` turns a command typed short into the one it means, in the long form the parser has
always taken, and `format_command` writes it back as a line. The conversation shows that line
(`running: ...`) before it runs a command that was typed short, and the full screen shows it
under the input while the person types: what runs is always on the screen in full first.

The short forms, all of them decided by harness data only (a folder name, a skill's declared
inputs), never by what a file or a reply contains:

- `/new SLUG` is `/new --project SLUG` when SLUG is the name of a project folder of the vault.
- `/skill NAME PATH` is `/skill NAME --file INPUT=PATH` when the skill declares exactly one
  input and PATH is the only bare word (no `=`, not an option).
- A command's name may be cut to its start when only one command starts so (parser.py).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from harness.shell.parser import Command

RUNNING = "running: "  # the harness line that shows the full command before it runs


@dataclass(frozen=True)
class Known:
    """What the short forms may look up. The conversation answers from the vault and the
    skills folder; the full screen from the last snapshot the conversation gave it."""

    is_project: Callable[[str], bool]
    skill_inputs: Callable[[str], tuple[str, ...] | None]  # None: not a valid skill


NOTHING_KNOWN = Known(is_project=lambda _: False, skill_inputs=lambda _: None)


def expand(command: Command, known: Known) -> Command:
    """The long form of `command` (itself when it is not a short form)."""
    if command.name == "new":
        return _expand_new(command, known)
    if command.name == "skill":
        return _expand_skill(command, known)
    return command


def _expand_new(command: Command, known: Known) -> Command:
    args = command.args
    if args and not args[0].startswith("-") and _safe(known.is_project, args[0]):
        return Command("new", ("--project", *args))
    return command


def _expand_skill(command: Command, known: Known) -> Command:
    if len(command.args) < 2:
        return command
    name, rest = command.args[0], list(command.args[1:])
    bare: list[int] = []
    given: set[str] = set()
    index = 0
    while index < len(rest):
        word = rest[index]
        if word == "--file":
            if index + 1 < len(rest):
                given.add(rest[index + 1].partition("=")[0])
            index += 2
            continue
        if "=" in word:
            given.add(word.partition("=")[0])
        elif not word.startswith("-"):
            bare.append(index)
        index += 1
    if len(bare) != 1:
        return command
    inputs = _safe(known.skill_inputs, name)
    if not inputs or len(inputs) != 1 or inputs[0] in given:
        return command
    position = bare[0]
    rest[position: position + 1] = ["--file", f"{inputs[0]}={rest[position]}"]
    return Command("skill", (name, *rest))


def _safe(lookup: Callable, value: str):  # noqa: ANN202 - bool or a tuple
    """A lookup that fails is a lookup that found nothing: the long form then reports."""
    try:
        return lookup(value)
    except Exception:  # noqa: BLE001
        return None


def format_command(command: Command) -> str:
    """The command as a line the parser reads back into the same command."""
    words = [f"/{command.name}"]
    for word in command.args:
        if not word or any(char.isspace() for char in word):
            words.append(f'"{word}"')
        else:
            words.append(word)
    return " ".join(words)
