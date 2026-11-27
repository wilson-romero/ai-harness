"""The one table of the conversation's commands (command-completion D1).

The parser takes the names and the number of arguments from here, `/help` is written from
here, and completion reads here what each position of a command takes. Adding a command, an
option or a short form means editing this table only: there is no second list to keep in sync.
Pure data and pure functions: no terminal, no disk.
"""

from __future__ import annotations

from dataclasses import dataclass

from harness.core.response_mode import ResponseMode

# What an argument position takes, for completion (completion.py) and the short forms
# (shortforms.py). Values that are typed freely complete nothing.
PROJECT = "project"  # a folder under projects/ of the vault
PROJECT_OR_NAME = "project-or-name"  # /new: a project's name, else the session's name
SESSION = "session"  # a session of the database
SKILL = "skill"  # a skill folder
SKILL_INPUT = "skill-input"  # NAME=VALUE, or a path when the skill declares one input
INPUT_PATH = "input-path"  # NAME=PATH of --file
PATH = "path"  # a path on the disk, relative to the working folder
TEXT = "text"  # free text
MODE = "mode"  # a response mode (response-mode): one of MODES
MODES: tuple[str, ...] = tuple(mode.value for mode in ResponseMode)


@dataclass(frozen=True)
class Option:
    name: str
    takes: str  # what its value is
    help: str


@dataclass(frozen=True)
class CommandSpec:
    name: str
    least: int
    most: int | None  # None: any number
    usage: str
    summary: str
    positional: tuple[str, ...] = ()  # what each positional takes; the last one repeats
    options: tuple[Option, ...] = ()
    short: str = ""  # the short form, for /help

    @property
    def takes_arguments(self) -> bool:
        return self.most is None or self.most > 0


TABLE: tuple[CommandSpec, ...] = (
    CommandSpec("help", 0, 0, "/help", "this list"),
    CommandSpec("status", 0, 0, "/status", "session, project, provider and last request"),
    CommandSpec("new", 0, None, "/new [--project SLUG] [NAME]", "switch to a new session",
                positional=(PROJECT_OR_NAME, TEXT),
                options=(Option("--project", PROJECT, "the project whose memory is sent"),),
                short="/new SLUG: a project's name stands for --project SLUG"),
    CommandSpec("sessions", 0, 0, "/sessions", "numbered list of sessions"),
    CommandSpec("resume", 1, 1, "/resume N|ID",
                "switch to session N of the last /sessions list, or to session ID",
                positional=(SESSION,)),
    CommandSpec("history", 0, 0, "/history", "the history of this session"),
    CommandSpec("memory", 1, None, "/memory TERMS",
                "search the memory (of the session's project, if it has one)",
                positional=(TEXT,)),
    CommandSpec("context", 0, 0, "/context",
                "the memory block sent with each question of this session"),
    CommandSpec("skill", 1, None, "/skill NAME [NAME=VALUE ...] [--file NAME=PATH ...]",
                "run a skill in this session",
                positional=(SKILL, SKILL_INPUT),
                options=(Option("--file", INPUT_PATH, "an input read from a text file"),),
                short="/skill NAME PATH: for a skill with one input, --file INPUT=PATH"),
    CommandSpec("file", 1, 1, "/file PATH",
                "attach a text file to the next question (it is never stored)",
                positional=(PATH,)),
    CommandSpec("mode", 0, 1, f"/mode [{'|'.join(MODES)}]",
                "the response mode of this session (nothing is sent)", positional=(MODE,)),
    CommandSpec("exit", 0, 0, "/exit", "leave (end of input leaves too)"),
)

BY_NAME: dict[str, CommandSpec] = {spec.name: spec for spec in TABLE}

_USAGE_COLUMN = 22
HELP_HEAD = ("Commands (a line that starts with / is never sent to the provider; start it "
             "with // to ask\na question that begins with /):")
HELP_TAIL = """\
Short forms: the start of a command's name is enough when only one command starts so (/sk is
/skill); the full command is shown (running: ...) before it runs.
In the full screen, / opens a list of the commands and their arguments: tab or the arrows and
enter complete, esc closes it; nothing is sent until enter is pressed with the list closed.
Ctrl+C interrupts a question in progress; it is never resent. Ctrl+C at the approval prompt
leaves the approval undecided. At that prompt, n asks for the word reject to confirm; any other
answer leaves the approval pending."""


def help_text() -> str:
    """`/help`, written from the table."""
    lines = [HELP_HEAD]
    for spec in TABLE:
        usage = spec.usage
        gap = " " * max(1, _USAGE_COLUMN - len(usage)) if len(usage) < _USAGE_COLUMN else "   "
        lines.append(f"  {usage}{gap}{spec.summary}")
        if spec.short:
            lines.append(f"  {'':{_USAGE_COLUMN}}short: {spec.short}")
    lines.append(HELP_TAIL)
    return "\n".join(lines)


def names_starting(start: str) -> list[str]:
    """The command names that start with `start`, in the table's order."""
    return [spec.name for spec in TABLE if spec.name.startswith(start)]


def resolve_name(word: str) -> str | None:
    """The command `word` names: itself, or the only command whose name starts with it."""
    if word in BY_NAME:
        return word
    found = names_starting(word) if word else []
    return found[0] if len(found) == 1 else None
