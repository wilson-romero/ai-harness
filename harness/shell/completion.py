"""Tab completion of the conversation's commands (shell-appearance D6). Pure: no terminal.

Only the conversation prompt completes; the approval prompt never does. Candidates come from
the harness alone: the closed list of commands, the numbers of the last /sessions list and the
names of the skill folders. `/file` completes paths, which the styled terminal reads from the
disk and filters (`acceptable_path`).
"""

from __future__ import annotations

from dataclasses import dataclass

from harness.shell.parser import COMMANDS
from harness.shell.terminal import ShellState
from harness.text.safe_text import terminal_safe

PATH = "path"  # the kind of a /file argument: completed by the terminal from the disk


@dataclass(frozen=True)
class Completions:
    """Replace the last `length` characters before the cursor with one of `candidates`; or,
    when `kind` is PATH, complete `word` as a path."""

    length: int = 0
    candidates: tuple[str, ...] = ()
    kind: str = ""
    word: str = ""


NONE = Completions()


def complete(before_cursor: str, state: ShellState) -> Completions:
    """What can complete the text before the cursor of the conversation prompt."""
    if not before_cursor.startswith("/") or before_cursor.startswith("//"):
        return NONE
    if not before_cursor[1:] or " " not in before_cursor:
        names = tuple(f"/{name}" for name in COMMANDS if f"/{name}".startswith(before_cursor))
        return Completions(len(before_cursor), names)
    command, _, rest = before_cursor.partition(" ")
    rest = rest.lstrip(" ")
    if " " in rest or '"' in rest:  # only the first argument; quoted words are typed by hand
        return NONE
    if command == "/resume":
        numbers = tuple(str(n) for n in range(1, state.resume_count() + 1)
                        if str(n).startswith(rest))
        return Completions(len(rest), numbers)
    if command == "/skill":
        names = tuple(name for name in state.skill_names() if name.startswith(rest))
        return Completions(len(rest), names)
    if command == "/file":
        return Completions(len(rest), kind=PATH, word=rest)
    return NONE


def acceptable_path(text: str) -> bool:
    """A path offered by completion: no control, format or line separator character (they are
    not shown) and nothing the command line would split or quote (a space, a double quote)."""
    return bool(text) and terminal_safe(text) == text and " " not in text and '"' not in text
