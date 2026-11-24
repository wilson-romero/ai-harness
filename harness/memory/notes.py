"""Reading notes and the minimal frontmatter parser (D10), plus project membership (D6).

The parser accepts only the two measured forms of `claude-memory-system`: a leading `---`
block of `key: value` scalars, with lists either inline (`[a, b]`) or as a block (`- a`).
Anything else marks the frontmatter as not valid; it never raises.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from harness.memory.paths import PROJECTS_DIR, VaultFile, read_vault_file

FieldValue = str | tuple[str, ...]

CURATED_DIRS = ("Decisiones", "Lecciones", "Memoria-CC")
SECTION_PROJECT = "project"
SECTION_SESSION = "session"

_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_UNSUPPORTED_VALUE_START = ("{", "|", ">", "&", "*", "!", "%", "@", "`")


@dataclass(frozen=True)
class Frontmatter:
    present: bool  # the text opens with a `---` line
    syntax_ok: bool  # present, closed and made only of the supported forms
    fields: Mapping[str, FieldValue] = field(default_factory=dict)


@dataclass(frozen=True)
class Note:
    relative: str
    text: str  # normalised: no BOM, `\n` line ends
    body: str  # the text without the frontmatter block
    frontmatter: Frontmatter
    sha256: str  # of the bytes on disk
    size: int

    @property
    def updated(self) -> str | None:
        """`updated` as `YYYY-MM-DD`, or None if missing, not a date or in the future.

        A date in the future is not trusted: it would put the note ahead of every other
        note of its group for as long as the date lasts (SEC-03).
        """
        value = date_prefix(self.frontmatter.fields.get("updated"))
        return None if value is None or value > today() else value

    @property
    def tags(self) -> tuple[str, ...]:
        return as_list(self.frontmatter.fields.get("tags"))


def decode(raw: bytes) -> str:
    """UTF-8 with replacement, without a BOM and with `\\n` line ends."""
    text = raw.decode("utf-8", errors="replace")
    return text.removeprefix("﻿").replace("\r\n", "\n")


def today() -> str:
    """The local date as `YYYY-MM-DD`; a function so that tests can fix it."""
    return date.today().isoformat()


def load_note(file: VaultFile) -> Note:
    """Read a walked note. Raises `SkippedRead` if it is not the file the walk saw."""
    raw = read_vault_file(file)
    text = decode(raw)
    frontmatter, body = parse_frontmatter(text)
    return Note(
        relative=file.relative,
        text=text,
        body=body,
        frontmatter=frontmatter,
        sha256=hashlib.sha256(raw).hexdigest(),
        size=len(raw),
    )


def parse_frontmatter(text: str) -> tuple[Frontmatter, str]:
    """Split a normalised note into its frontmatter and body."""
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return Frontmatter(present=False, syntax_ok=False), text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].rstrip() == "---")
    except StopIteration:
        return Frontmatter(present=True, syntax_ok=False), text
    body = "\n".join(lines[end + 1 :])
    fields = _parse_block(lines[1:end])
    if fields is None:
        return Frontmatter(present=True, syntax_ok=False), body
    return Frontmatter(present=True, syntax_ok=True, fields=fields), body


def _parse_block(lines: list[str]) -> dict[str, FieldValue] | None:
    fields: dict[str, FieldValue] = {}
    open_list: str | None = None  # key whose block list is being read
    for line in lines:
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- ") or stripped == "-":
            if open_list is None:
                return None
            item = _unquote(stripped[1:].strip())
            fields[open_list] = (*as_list(fields[open_list]), item) if item else fields[open_list]
            continue
        if line[0].isspace() or ":" not in line:
            return None
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not _KEY_RE.fullmatch(key) or key in fields:
            return None
        if value.startswith(_UNSUPPORTED_VALUE_START) or value.startswith("#"):
            return None
        if not value:
            fields[key] = ()
            open_list = key
            continue
        open_list = None
        if value.startswith("["):
            if not value.endswith("]"):
                return None
            inner = value[1:-1].strip()
            fields[key] = tuple(_unquote(p.strip()) for p in inner.split(",")) if inner else ()
        else:
            fields[key] = _unquote(value)
    return fields


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def as_list(value: FieldValue | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(item for item in value if item)


def date_prefix(value: FieldValue | None) -> str | None:
    """`YYYY-MM-DD` at the start of a scalar value, if it is a real date."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        date.fromisoformat(value[:10])
    except ValueError:
        return None
    return value[:10]


def frontmatter_problem(frontmatter: Frontmatter) -> str | None:
    """Why a note's frontmatter is not valid for maintenance (D10), or None."""
    if not frontmatter.present:
        return "missing"
    if not frontmatter.syntax_ok:
        return "unsupported"
    if not isinstance(frontmatter.fields.get("type"), str) or not frontmatter.fields["type"]:
        return "missing type"
    for key in ("created", "updated"):
        value = frontmatter.fields.get(key)
        if not isinstance(value, str) or not _DATE_RE.fullmatch(value) or not date_prefix(value):
            return f"{key} is not YYYY-MM-DD"
        if value > today():
            return f"{key} is in the future"
    return None


# -- project membership (D6): shared by `memory search --project` and the context ----------------


def declares_project(frontmatter: Frontmatter, slug: str) -> bool:
    fields = frontmatter.fields
    return fields.get("project_slug") == slug or slug in as_list(fields.get("tags"))


def project_section(relative: str, frontmatter: Frontmatter, slug: str) -> str | None:
    """Which part of project `slug`'s memory a note belongs to, or None if it does not.

    Returns `project` for `projects/<slug>/_project.md`, `session` for a note directly under
    `projects/<slug>/sessions/`, or the curated folder name (`Decisiones`, `Lecciones`,
    `Memoria-CC`) for a curated note that declares the project in its frontmatter.
    """
    parts = relative.split("/")
    if parts[:2] == [PROJECTS_DIR, slug]:
        if parts[2:] == ["_project.md"]:
            return SECTION_PROJECT
        if len(parts) == 4 and parts[2] == "sessions":
            return SECTION_SESSION
        return None
    if len(parts) > 1 and parts[0] in CURATED_DIRS and declares_project(frontmatter, slug):
        return parts[0]
    return None
