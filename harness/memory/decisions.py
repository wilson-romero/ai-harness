"""Decision notes: the one place where the harness writes in the vault (decision-notes D4-D8).

What is here: the identifier, slug and file name of a decision (pure), the deterministic render
of the note (pure), the confined look at `Decisiones/` shared by `prepare`, `apply` and
`reconcile`, and the writer. The writer never replaces anything: it writes a hidden temporary
file with exclusive creation and publishes it with a hard link, which fails if the final name
exists, of whatever kind (D6). It is the only module of `harness/memory/` exempted from the
no-writes allowlist, and only for the primitives listed in that test (D9). Nothing used by the
`memory …` commands imports it.
"""

from __future__ import annotations

import hashlib
import os
import stat
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from harness.memory.notes import decode, parse_frontmatter
from harness.memory.paths import (
    FILE_MAX_BYTES,
    WALK_MAX_FILES,
    SkippedRead,
    VaultFile,
    is_safe_file_name,
    is_safe_name,
    is_within,
    read_vault_file,
    validate_project_slug,
)
from harness.text.safe_text import neutralise_delimiters

DECISIONS_DIR = "Decisiones"
ID_DOMAIN = "ai-harness/decision/v1\n"
ID_PREFIX = "dec-"
ID_HEX_CHARS = 16
SLUG_MAX_CHARS = 48
SLUG_FALLBACK = "decision"
NOTE_SUFFIX = ".md"
TEMP_PREFIX = ".harness-"
TEMP_SUFFIX = ".tmp"
_SLUG_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")
_HEX = frozenset("0123456789abcdef")


class DecisionRefused(Exception):
    """A controlled refusal: nothing was written. `code` is stable and stored."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DecisionUncertain(Exception):
    """The note may be published: the link was created, or may have been, and something after
    it failed. Never a refusal: the engine leaves the step `uncertain` and `reconcile` decides."""


@dataclass(frozen=True)
class DecisionFields:
    """The validated decision, already cleaned and redacted by the caller."""

    title: str
    context: str
    decision: str
    alternatives: tuple[str, ...]
    consequences: tuple[str, ...]
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class Provenance:
    skill_name: str
    skill_version: str
    skill_sha256: str
    run_id: str
    memory_notes: tuple[tuple[str, str], ...]  # (relative path, sha256), as in request_context
    source_bytes: int
    source_sha256: str
    redactions: int


# -- identifier, slug and name (D4) -------------------------------------------------------------


def normalise_title(title: str) -> str:
    """NFKC, `casefold()`, whitespace collapsed and trimmed: what identifies a decision."""
    return " ".join(unicodedata.normalize("NFKC", title).casefold().split())


def decision_id(project_slug: str, title: str) -> str:
    validate_project_slug(project_slug)
    digest = hashlib.sha256(
        f"{ID_DOMAIN}{project_slug}\n{normalise_title(title)}".encode("utf-8")
    ).hexdigest()
    return ID_PREFIX + digest[:ID_HEX_CHARS]


def is_decision_id(raw: str) -> bool:
    body = raw[len(ID_PREFIX):]
    return raw.startswith(ID_PREFIX) and len(body) == ID_HEX_CHARS and set(body) <= _HEX


def slug_for(title: str) -> str:
    """ASCII, lowercase, `[a-z0-9-]`, at most 48 characters, cut at a hyphen if there is one.

    Empty, or a reserved Windows device name, gives `decision`. No regular expression: one pass.
    """
    ascii_text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    out: list[str] = []
    for char in ascii_text.lower():
        if char in _SLUG_CHARS:
            out.append(char)
        elif out and out[-1] != "-":
            out.append("-")
    slug = "".join(out).strip("-")
    if len(slug) > SLUG_MAX_CHARS:
        cut = slug[:SLUG_MAX_CHARS]
        slug = (cut[: cut.rindex("-")] if "-" in cut else cut).strip("-")
    if not slug or not is_safe_name(slug):
        return SLUG_FALLBACK
    return slug


def decision_file_name(day: date, title: str, ident: str) -> str:
    if not is_decision_id(ident):
        raise ValueError(f"not a decision identifier: {ident!r}")
    name = f"{day.isoformat()}-{slug_for(title)}-{ident[len(ID_PREFIX):][:8]}{NOTE_SUFFIX}"
    if not is_safe_file_name(name):  # cannot happen with the slug rules; checked anyway
        raise ValueError(f"unsafe decision file name {name!r}")
    return name


def temp_name_for(run_id: str, step: str) -> str:
    name = f"{TEMP_PREFIX}{run_id}-{step}{TEMP_SUFFIX}"
    if not is_safe_file_name(name):
        raise ValueError(f"unsafe temporary file name {name!r}")
    return name


# -- render (D5) --------------------------------------------------------------------------------


# What Obsidian or one of its plugins acts on, written as an HTML entity so that the reading view
# shows the character and nothing acts on it (2026-11-25, independent review). `&` goes first, so
# that every entity in the result is the harness's own and a model's literal `&lt;` stays
# literal. Each pair is a plain `str.replace`: linear in the input, no pattern search.
INERT_REPLACEMENTS = (
    ("&", "&amp;"),
    ("<", "&lt;"),  # HTML, <script>, <!-- comments -->, Templater <% %> and <%* %>, autolinks
    ("`", "&#96;"),  # ``` fences (dataview, dataviewjs) and inline code (`= …`, `$= …`)
    ("~~", "~&#126;"),  # ~~~ fences
    ("%%", "%&#37;"),  # Obsidian comments: hidden in the reading view, read back by the memory
    ("![", "!&#91;"),  # images (a remote one is fetched when the note is shown) and embeds
    ("[[", "[&#91;"),  # wikilinks: they add links and graph edges to notes the model names
    ("::", ":&#58;"),  # Dataview inline fields: metadata that queries over the vault would read
)


def make_inert(text: str) -> str:
    """Model text that Obsidian shows literally and no plugin executes, embeds or fetches."""
    for active, inert in INERT_REPLACEMENTS:
        text = text.replace(active, inert)
    return text


def _escape_line(line: str) -> str:
    """Model text cannot open a section, draw a rule that reads as a frontmatter fence, or
    imitate the `--- <path> (<type>, <updated>)` header that `memory context` puts before each
    note (every line that starts with `---` is escaped, whatever the header looks like)."""
    line = make_inert(neutralise_delimiters(line))
    stripped = line.strip()
    if (
        stripped.startswith(("#", "---"))
        or (len(stripped) >= 3 and set(stripped) <= set("-=*_"))
    ):
        return "\\" + line
    return line


def _block(text: str) -> str:
    return "\n".join(_escape_line(line) for line in text.split("\n")).strip("\n")


def _inline(text: str) -> str:
    return make_inert(neutralise_delimiters(" ".join(text.split())))


def _items(items: tuple[str, ...]) -> str:
    return "\n".join(f"- {_inline(item)}" for item in items if item.strip())


def render_note(fields: DecisionFields, project_slug: str, day: date,
                provenance: Provenance) -> str:
    """The whole note, as text with `\\n` line ends. Same inputs, same bytes."""
    ident = decision_id(project_slug, fields.title)
    when = day.isoformat()
    notes = ", ".join(f"{_inline(path)} (sha256 {digest[:8]})"
                      for path, digest in provenance.memory_notes) or "ninguna"
    lines = [
        "---",
        "type: decision",
        f"decision_id: {ident}",
        f"project_slug: {project_slug}",
        "status: accepted",
        f"created: {when}",
        f"updated: {when}",
        f"tags: [decision, {project_slug}]",
        "source: ai-harness",
        f"skill: {provenance.skill_name}@{provenance.skill_version}",
        f"run_id: {provenance.run_id}",
        "---",
        f"# {_inline(fields.title)}",
        "",
        "## Contexto",
        "",
        _block(fields.context),
        "",
        "## Decisión",
        "",
        _block(fields.decision),
        "",
        "## Alternativas consideradas",
        "",
        _items(fields.alternatives) or "Ninguna declarada.",
        "",
        "## Consecuencias",
        "",
        _items(fields.consequences) or "Ninguna declarada.",
        "",
        "## Supuestos",
        "",
        _items(fields.assumptions) or "Ninguno declarado.",
        "",
        "## Procedencia",
        "",
        f"- Skill {provenance.skill_name} {provenance.skill_version} "
        f"(sha256 {provenance.skill_sha256[:8]}), ejecución {provenance.run_id}.",
        f"- Notas de memoria consultadas: {notes}.",
        f"- Fuente: {provenance.source_bytes} bytes (sha256 {provenance.source_sha256[:8]}).",
        f"- Credenciales enmascaradas: {provenance.redactions}.",
        "",
    ]
    return "\n".join(lines)


# -- the confined look at Decisiones/ (D3, D8) --------------------------------------------------


def inspect_decisions_dir(root: Path) -> Path | None:
    """`root/Decisiones` if it is a real directory inside the real root; None if it is missing.

    `root` is the resolved vault root. A link, a junction, anything that is not a directory,
    a folder whose resolved path is not exactly `root/Decisiones`, or a folder whose name only
    differs in case, is refused. Nothing is created here.
    """
    try:
        names = os.listdir(root)
    except OSError:
        raise DecisionRefused("unsafe_target", "the vault root cannot be listed") from None
    variants = [name for name in names if name.casefold() == DECISIONS_DIR.casefold()]
    if not variants:
        return None
    if variants != [DECISIONS_DIR]:
        raise DecisionRefused(
            "unsafe_target", f"the vault has a folder named like {DECISIONS_DIR}/ in other case")
    folder = root / DECISIONS_DIR
    _check_real_dir(root, folder)
    return folder


def _check_real_dir(root: Path, folder: Path) -> None:
    refused = DecisionRefused(
        "unsafe_target",
        f"{DECISIONS_DIR}/ is a link, a junction or not a real folder inside the vault",
    )
    try:
        info = folder.lstat()
        if folder.is_symlink() or folder.is_junction() or not stat.S_ISDIR(info.st_mode):
            raise refused
        real = folder.resolve(strict=True)
    except OSError:
        raise refused from None
    if real != root / DECISIONS_DIR or not is_within(real, root):
        raise refused


def find_decision_notes(folder: Path, ident: str) -> list[tuple[str, str]]:
    """(file name, sha256) of each Markdown note directly in `folder` with that `decision_id`.

    Same rules as the confined walk (no links, no hidden files, regular files of at most
    1 MiB, read through the identity-checked reader, at most WALK_MAX_FILES names), except that
    a file with more than one hard link is still looked at: missing a duplicate is worse here.
    """
    found: list[tuple[str, str]] = []
    try:
        names = sorted(os.listdir(folder))[:WALK_MAX_FILES]
    except OSError:
        raise DecisionRefused("unsafe_target", f"{DECISIONS_DIR}/ cannot be listed") from None
    for name in names:
        if name.startswith(".") or not name.endswith(NOTE_SUFFIX):
            continue
        entry = folder / name
        try:
            if entry.is_symlink() or entry.is_junction():
                continue
            info = entry.lstat()
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_size > FILE_MAX_BYTES:
            continue
        file = VaultFile(entry, f"{DECISIONS_DIR}/{name}", info.st_size, info.st_dev,
                         info.st_ino)
        try:
            raw = read_vault_file(file)
        except SkippedRead:
            continue
        frontmatter, _ = parse_frontmatter(decode(raw))
        if frontmatter.syntax_ok and frontmatter.fields.get("decision_id") == ident:
            found.append((name, hashlib.sha256(raw).hexdigest()))
    return found


# -- the writer (D6) and the reconciliation (D7) ------------------------------------------------


def write_decision(root: Path, name: str, data: bytes, temp_name: str, ident: str) -> str:
    """Write a new note `Decisiones/<name>` with exactly `data`; return its relative path.

    The caller holds the vault lock and has consumed the approval. Refuses (DecisionRefused)
    rather than replace, follow a link or leave its temporary file behind.
    """
    if not (is_safe_file_name(name) and name.endswith(NOTE_SUFFIX) and not name.startswith(".")):
        raise DecisionRefused("unsafe_target", "the note name is not a safe file name")
    if not (is_safe_file_name(temp_name) and temp_name.startswith(TEMP_PREFIX)):
        raise DecisionRefused("unsafe_target", "the temporary name is not a safe hidden name")
    if not is_decision_id(ident):
        raise DecisionRefused("unsafe_target", "not a decision identifier")
    folder = inspect_decisions_dir(root)
    if folder is None:
        try:
            os.mkdir(root / DECISIONS_DIR)
        except FileExistsError:
            pass
        except OSError:
            raise DecisionRefused("write_failed", f"{DECISIONS_DIR}/ cannot be created") from None
        folder = inspect_decisions_dir(root)
        if folder is None:
            raise DecisionRefused("write_failed", f"{DECISIONS_DIR}/ disappeared")
    target = folder / name
    if _exists(target):
        raise DecisionRefused("conflict", f"{DECISIONS_DIR}/{name} already exists")
    existing = find_decision_notes(folder, ident)
    if existing:
        raise DecisionRefused("duplicate_decision",
                              f"decision already recorded in {DECISIONS_DIR}/{existing[0][0]}")
    temp = folder / temp_name
    identity = _write_temp(temp, data)
    try:
        _publish(root, temp, target, identity)
    except (DecisionRefused, DecisionUncertain):
        _drop_temp(temp)  # never raises; a temporary file left behind is reconcile's
        raise
    if not _drop_temp(temp):
        # Published, but with two links the memory skips the note: `reconcile` retries.
        raise DecisionUncertain(
            f"the note is published but its temporary file {DECISIONS_DIR}/{temp_name} cannot be "
            "removed (another program may hold it open)")
    return f"{DECISIONS_DIR}/{name}"


def reconcile_decision(root: Path, ident: str, content_sha256: str, temp_name: str) -> str:
    """`applied`, `absent`, `conflict` or `blocked` for an interrupted write. Writes nothing.

    Removes this step's own temporary file first: after a death between the link and the
    removal, the note has two hard links and is invisible to the memory until then. If that
    file is still there and cannot be removed (another program holds it, or something that is
    not a regular file took its name), the answer is `blocked`: nothing can be said to be
    finished, and a later call tries again.
    """
    if not is_decision_id(ident):
        return "conflict"
    try:
        folder = inspect_decisions_dir(root)
    except DecisionRefused:
        return "conflict"
    if folder is None:
        return "absent"
    if not _drop_temp(folder / temp_name):
        return "blocked"
    found = find_decision_notes(folder, ident)
    if not found:
        return "absent"
    if len(found) == 1 and found[0][1] == content_sha256:
        return "applied"
    return "conflict"


def _exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _write_temp(temp: Path, data: bytes) -> tuple[int, int]:
    """Exclusive creation (never opens an existing file or link), all bytes, fsync."""
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NOINHERIT", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        fd = os.open(temp, flags, 0o644)
    except OSError:
        raise DecisionRefused("write_failed", "the temporary file cannot be created") from None
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
        info = os.fstat(fd)
    except OSError:
        os.close(fd)
        _drop_temp(temp)
        raise DecisionRefused("write_failed", "the temporary file cannot be written") from None
    os.close(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_size != len(data):
        _drop_temp(temp)
        raise DecisionRefused("write_failed", "the temporary file is not what was written")
    return info.st_dev, info.st_ino


def _publish(root: Path, temp: Path, target: Path, identity: tuple[int, int]) -> None:
    """Give the written file its final name; fails, never replaces, if the name exists."""
    try:
        os.link(temp, target)
    except FileExistsError:
        raise DecisionRefused("conflict", f"{DECISIONS_DIR}/{target.name} already exists") from None
    except OSError:
        raise DecisionRefused(
            "write_failed", "the note cannot be published (the file system must allow hard links)"
        ) from None
    # The link exists from here on: the outcome is "published" or "cannot tell", never a
    # refusal, unless the note is taken back out (architecture-skills-llm, 7.1).
    try:
        info = target.lstat()
        real = target.resolve(strict=True)
    except OSError:
        raise DecisionUncertain("the published note cannot be checked") from None
    if (info.st_dev, info.st_ino) != identity:
        raise DecisionUncertain("the published name is not the file written")
    if real.parent != root / DECISIONS_DIR:
        # Decisiones/ was swapped for a link after it was checked: take our file back out.
        _take_back(target)


def _take_back(target: Path) -> None:
    """Remove the name just published (checked to be our file) and refuse the write."""
    try:
        os.unlink(target)
    except OSError:
        raise DecisionUncertain(f"{DECISIONS_DIR}/ changed during the write and the note "
                                "could not be taken back") from None
    raise DecisionRefused("unsafe_target", f"{DECISIONS_DIR}/ changed during the write")


def _drop_temp(temp: Path) -> bool:
    """Remove a temporary file of ours; True when none is left at that name. Never raises.

    Only a name of the harness's temporary form, only a regular file, never through a link.
    Something else at that name, or a file that cannot be removed now (held open by another
    program), gives False and stays.
    """
    name = temp.name
    if not (name.startswith(TEMP_PREFIX) and name.endswith(TEMP_SUFFIX)
            and is_safe_file_name(name)):
        return False
    try:
        info = temp.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode) or temp.is_symlink():
        return False
    try:
        os.unlink(temp)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True
