"""`memory maintain --dry-run`: what a deterministic maintenance pass would find (D10).

Phase 1 of the "Sueño" of `claude-memory-system`, as a report only: nothing in the vault is
created, changed, moved or deleted. The report names relative paths and kinds of finding,
never a credential or a fragment of a note's body, and is identical byte for byte on the same
vault (no dates, no durations).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from harness.memory.notes import Note, frontmatter_problem, load_note
from harness.memory.paths import (
    SKIP_HARD_LINK,
    SKIP_LINK,
    SKIP_NOT_MARKDOWN,
    SKIP_NOT_REGULAR,
    SKIP_OUTSIDE_ROOT,
    SKIP_TOO_LARGE,
    SKIP_UNREADABLE,
    walk_vault,
)
from harness.memory.redaction import secret_kinds
from harness.memory.search import terminal_safe

CATEGORIES = (
    "sync_conflicts",
    "broken_links",
    "index_dangling",
    "index_orphans",
    "duplicate_candidates",
    "invalid_frontmatter",
    "secrets_found",
    "skipped",
)
MAX_LISTED = 50
LINK_FIX_CUTOFF = 0.85  # same thresholds as memoria-dream.sh (measured)
DUPLICATE_THRESHOLD = 0.72
LINK_ROOTS_NOT_CHECKED = ("projects", "daily")  # written by the capture, not repaired
CURATED_MEMORY = "Memoria-CC"
# Entries the confined read refused. Hidden entries, the archive and non-Markdown files are
# excluded by design, not defects, so they are not reported.
REPORTED_SKIPS = (
    SKIP_LINK,
    SKIP_HARD_LINK,
    SKIP_NOT_REGULAR,
    SKIP_TOO_LARGE,
    SKIP_OUTSIDE_ROOT,
    SKIP_UNREADABLE,
)
LIMIT_NOTE = (
    "note: secrets_found only covers known credential formats; "
    "a credential in an unknown format is not detected\n"
)

_CONFLICT_RE = re.compile(r"\.sync-conflict-|\.\.path\d+$")
_WIKI_LINK_RE = re.compile(r"\[\[([^\[\]\n]+)\]\]")
_INDEX_NAME_RE = re.compile(r"MEMORY.*\.md")
_INDEX_ENTRY_RE = re.compile(r"^\s*[-*]\s+\[[^\]]*\]\(([^)\s]+)\)")


@dataclass(frozen=True)
class MaintenanceReport:
    findings: dict[str, tuple[str, ...]]  # category -> sorted entries
    truncated_walk: bool

    @property
    def text(self) -> str:
        lines: list[str] = []
        for category in CATEGORIES:
            entries = self.findings[category]
            lines.append(f"{category}: {len(entries)}")
            lines += [f"  {terminal_safe(entry)}" for entry in entries[:MAX_LISTED]]
            if len(entries) > MAX_LISTED:
                lines.append(f"  ... and {len(entries) - MAX_LISTED} more")
        return "\n".join(lines) + "\n" + LIMIT_NOTE


def maintenance_report(root: Path) -> MaintenanceReport:
    """Read the vault with the confined walk and report; `root` is the real vault root."""
    walk = walk_vault(root)
    findings: dict[str, list[str]] = {category: [] for category in CATEGORIES}

    findings["skipped"] += [
        f"{relative} ({reason})" for relative, reason in walk.skipped if reason in REPORTED_SKIPS
    ]
    # A sync conflict copy need not end in .md (`nota.md..path1`), so regular files that the
    # walk did not read as notes are looked at too, by name only.
    unread = (SKIP_NOT_MARKDOWN, SKIP_TOO_LARGE)
    other_files = [relative for relative, reason in walk.skipped if reason in unread]
    all_files = [file.relative for file in walk.files] + other_files
    findings["sync_conflicts"] += [r for r in all_files if _is_conflict(r)]

    notes: list[Note] = []
    for file in walk.files:
        if _is_conflict(file.relative):
            continue  # it would be quarantined; its content is not analysed
        try:
            notes.append(load_note(file))
        except OSError:
            findings["skipped"].append(f"{file.relative} ({SKIP_UNREADABLE})")

    indexes = [n for n in notes if _is_index(n.relative)]
    for note in notes:
        if not _is_index(note.relative):
            problem = frontmatter_problem(note.frontmatter)
            if problem:
                findings["invalid_frontmatter"].append(f"{note.relative} ({problem})")
        kinds = secret_kinds(note.text)
        if kinds:
            listed = ", ".join(f"{kind} ({kinds[kind]})" for kind in sorted(kinds))
            findings["secrets_found"].append(f"{note.relative}: {listed}")

    known = [r for r in all_files if not _is_conflict(r)]
    findings["broken_links"] += _broken_links(notes, known)
    curated = [n.relative for n in notes if _in_curated(n.relative) and not _is_index(n.relative)]
    dangling, orphans = _index_audit(indexes, curated)
    findings["index_dangling"] += dangling
    findings["index_orphans"] += orphans
    findings["duplicate_candidates"] += _duplicate_candidates(curated)

    return MaintenanceReport(
        findings={category: tuple(sorted(entries)) for category, entries in findings.items()},
        truncated_walk=walk.truncated,
    )


def _is_conflict(relative: str) -> bool:
    return bool(_CONFLICT_RE.search(relative.rsplit("/", 1)[-1]))


def _in_curated(relative: str) -> bool:
    return relative.startswith(CURATED_MEMORY + "/")


def _is_index(relative: str) -> bool:
    parts = relative.split("/")
    return (
        len(parts) == 2
        and parts[0] == CURATED_MEMORY
        and bool(_INDEX_NAME_RE.fullmatch(parts[1]))
    )


def _stem(relative: str) -> str:
    return PurePosixPath(relative).name.removesuffix(".md").casefold()


def _broken_links(notes: list[Note], known: list[str]) -> list[str]:
    """`[[...]]` links outside projects/ and daily/ that name no file, with a unique fix."""
    known_paths = {r.casefold().removesuffix(".md") for r in known}
    known_names = {_stem(r) for r in known}
    candidates: dict[str, list[str]] = {}
    for relative in known:
        if relative.endswith(".md"):
            candidates.setdefault(_stem(relative), []).append(relative)

    broken: list[str] = []
    for note in notes:
        if note.relative.split("/")[0] in LINK_ROOTS_NOT_CHECKED:
            continue
        for match in _WIKI_LINK_RE.finditer(note.body):
            target = match.group(1).split("|", 1)[0].split("#", 1)[0].strip()
            if not target:
                continue  # a link to a heading of the same note
            key = target.casefold().removesuffix(".md")
            if key in known_paths or key in known_names:
                continue
            if any(path.endswith("/" + key) for path in known_paths):
                continue
            name = key.rsplit("/", 1)[-1]
            close = [
                stem
                for stem in candidates
                if difflib.SequenceMatcher(None, name, stem).ratio() >= LINK_FIX_CUTOFF
            ]
            if len(close) == 1 and len(candidates[close[0]]) == 1:
                fix = candidates[close[0]][0]
            else:
                fix = "(no unique candidate)"
            # The link text is part of the body: only the note and the fix are named.
            broken.append(f"{note.relative} -> {fix}")
    return broken


def _index_audit(indexes: list[Note], curated: list[str]) -> tuple[list[str], list[str]]:
    """Index entries that name no note, and curated notes that no index names."""
    present = set(curated)
    named: set[str] = set()
    dangling: list[str] = []
    for index in indexes:
        for line in index.text.split("\n"):
            match = _INDEX_ENTRY_RE.match(line)
            if not match or "://" in match.group(1):
                continue
            target = f"{CURATED_MEMORY}/{match.group(1).removeprefix('./')}"
            named.add(target)
            if target not in present:
                dangling.append(f"{index.relative} -> {target}")
    orphans = [relative for relative in curated if relative not in named]
    return dangling, orphans


def _duplicate_candidates(curated: list[str]) -> list[str]:
    """Pairs of curated notes whose names are similar enough to be the same note."""
    ordered = sorted(curated)
    pairs: list[str] = []
    for i, first in enumerate(ordered):
        for second in ordered[i + 1 :]:
            ratio = difflib.SequenceMatcher(None, _stem(first), _stem(second)).ratio()
            if ratio > DUPLICATE_THRESHOLD:
                pairs.append(f"{first} ~ {second}")
    return pairs
