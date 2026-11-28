"""`memory maintain --dry-run`: what a deterministic maintenance pass would find (D10).

Phase 1 of the "Sueño" of `claude-memory-system`, as a report only: nothing in the vault is
created, changed, moved or deleted. The report names relative paths and kinds of finding,
never a credential or a fragment of a note's body, and is identical byte for byte on the same
vault (no dates, no durations).
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from harness.memory.notes import Note, frontmatter_problem, load_note
from harness.memory.paths import (
    SKIP_CHANGED,
    SKIP_HARD_LINK,
    SKIP_LINK,
    SKIP_NOT_MARKDOWN,
    SKIP_NOT_REGULAR,
    SKIP_OUTSIDE_ROOT,
    SKIP_TOO_LARGE,
    SKIP_UNREADABLE,
    SkippedRead,
    walk_vault,
)
from harness.text.safe_text import safe_line, safe_text

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
# Name comparisons (`difflib`) of each of the two passes that make them, the fixes of broken
# links and the duplicate pairs (security review 2026-11-27, F-07): the duplicate pass compares
# every pair of curated notes, which is quadratic by nature (100 000 pairs: about 450 curated
# notes). Past this many pairs a pass stops, the report says so, and what it found until then
# is kept. About 2.5 s per pass at most on the Mac (measured 2026-11-27).
MAX_NAME_COMPARISONS = 100_000
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
    SKIP_CHANGED,
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
    truncated_comparisons: bool = False  # a pass reached MAX_NAME_COMPARISONS

    @property
    def text(self) -> str:
        lines: list[str] = []
        for category in CATEGORIES:
            entries = self.findings[category]
            lines.append(f"{category}: {len(entries)}")
            # Entries hold paths and index targets: vault text, so cleaned and redacted.
            lines += [f"  {safe_line(entry).text}" for entry in entries[:MAX_LISTED]]
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
        except SkippedRead as refused:
            findings["skipped"].append(f"{file.relative} ({refused.reason})")

    indexes = [n for n in notes if _is_index(n.relative)]
    # A credential may sit in a file name as well as in a note's text; names are checked for
    # every entry the report can name, texts only for the notes that were read.
    kinds_by_path: dict[str, Counter[str]] = {}
    reported = [relative for relative, reason in walk.skipped if reason in REPORTED_SKIPS]
    for relative in dict.fromkeys(all_files + reported):
        kinds_by_path[relative] = Counter(safe_line(relative).kinds)
    for note in notes:
        if not _is_index(note.relative):
            problem = frontmatter_problem(note.frontmatter, note.relative)
            if problem:
                findings["invalid_frontmatter"].append(f"{note.relative} ({problem})")
        kinds_by_path[note.relative] += Counter(safe_text(note.text).kinds)
    for relative, kinds in kinds_by_path.items():
        if kinds:
            listed = ", ".join(f"{kind} ({kinds[kind]})" for kind in sorted(kinds))
            findings["secrets_found"].append(f"{relative}: {listed}")

    known = [r for r in all_files if not _is_conflict(r)]
    link_budget, pair_budget = _Budget(MAX_NAME_COMPARISONS), _Budget(MAX_NAME_COMPARISONS)
    findings["broken_links"] += _broken_links(notes, known, link_budget)
    curated = [n.relative for n in notes if _in_curated(n.relative) and not _is_index(n.relative)]
    dangling, orphans = _index_audit(indexes, curated, all_files)
    findings["index_dangling"] += dangling
    findings["index_orphans"] += orphans
    findings["duplicate_candidates"] += _duplicate_candidates(curated, pair_budget)

    return MaintenanceReport(
        findings={category: tuple(sorted(entries)) for category, entries in findings.items()},
        truncated_walk=walk.truncated,
        truncated_comparisons=link_budget.exhausted or pair_budget.exhausted,
    )


class _Budget:
    """Name comparisons left for one report; deterministic, so the report stays so."""

    def __init__(self, pairs: int) -> None:
        self.left = pairs
        self.exhausted = False

    def take(self) -> bool:
        if self.left <= 0:
            self.exhausted = True
            return False
        self.left -= 1
        return True


def _similar(first: str, second: str, cutoff: float, budget: _Budget, *,
             strict: bool = False) -> bool | None:
    """`SequenceMatcher(None, first, second).ratio()` against `cutoff` (`>`, or `>=` unless
    `strict`), or None once the budget is spent. The two quick upper bounds go first: they
    never change the answer, they only skip `ratio` where it cannot reach the cutoff."""
    if not budget.take():
        return None
    matcher = difflib.SequenceMatcher(None, first, second)
    for bound in (matcher.real_quick_ratio, matcher.quick_ratio, matcher.ratio):
        value = bound()
        if value < cutoff or (strict and value == cutoff):
            return False
    return True


def _is_conflict(relative: str) -> bool:
    return bool(_CONFLICT_RE.search(relative.rsplit("/", 1)[-1]))


def _in_curated(relative: str) -> bool:
    """A note directly in `Memoria-CC/`. The original looks at that folder's first level only
    (`os.listdir` in `scripts/memoria-dream.sh` at 92b19ea, lines 147-174), so a note in a
    sub-folder is neither an orphan nor half of a duplicate pair (memory-format-conformance
    D4)."""
    parts = relative.split("/")
    return len(parts) == 2 and parts[0] == CURATED_MEMORY


def _is_index(relative: str) -> bool:
    parts = relative.split("/")
    return (
        len(parts) == 2
        and parts[0] == CURATED_MEMORY
        and bool(_INDEX_NAME_RE.fullmatch(parts[1]))
    )


def _stem(relative: str) -> str:
    return PurePosixPath(relative).name.removesuffix(".md").casefold()


def _broken_links(notes: list[Note], known: list[str], budget: _Budget) -> list[str]:
    """`[[...]]` links outside projects/ and daily/ that name no file, with a unique fix.

    Linear in the links (F-07): a link may name any trailing part of a path, so every trailing
    part is in one set; and the fix for a name is searched once, however many links use it.
    """
    known_paths = {r.casefold().removesuffix(".md") for r in known}
    known_names = {_stem(r) for r in known}
    # Every trailing part of a known path after a "/": a link `b/c` names `a/b/c`.
    known_tails = {path.split("/", cut)[-1] for path in known_paths
                   for cut in range(1, path.count("/") + 1)}
    candidates: dict[str, list[str]] = {}
    for relative in known:
        if relative.endswith(".md"):
            candidates.setdefault(_stem(relative), []).append(relative)

    fixes: dict[str, str] = {}
    broken: list[str] = []
    for note in notes:
        if note.relative.split("/")[0] in LINK_ROOTS_NOT_CHECKED:
            continue
        for match in _WIKI_LINK_RE.finditer(note.body):
            # Inside a Markdown table the alias pipe is escaped, `[[a/b\|alias]]`, as the
            # capture writes `agents/_skills-index.md`: the `\` belongs to the table, not to
            # the target (memory-format-conformance D6).
            target = match.group(1).split("|", 1)[0].removesuffix("\\")
            target = target.split("#", 1)[0].strip()
            if not target:
                continue  # a link to a heading of the same note
            key = target.casefold().removesuffix(".md")
            if key in known_paths or key in known_names or key in known_tails:
                continue
            name = key.rsplit("/", 1)[-1]
            if name not in fixes:
                fixes[name] = _link_fix(name, candidates, budget)
            # The link text is part of the body: only the note and the fix are named.
            broken.append(f"{note.relative} -> {fixes[name]}")
    return broken


def _link_fix(name: str, candidates: dict[str, list[str]], budget: _Budget) -> str:
    close = []
    for stem in candidates:
        similar = _similar(name, stem, LINK_FIX_CUTOFF, budget)
        if similar is None:
            return "(not searched: comparison limit reached)"
        if similar:
            close.append(stem)
    if len(close) == 1 and len(candidates[close[0]]) == 1:
        return candidates[close[0]][0]
    return "(no unique candidate)"


def _index_audit(
    indexes: list[Note], curated: list[str], known: list[str]
) -> tuple[list[str], list[str]]:
    """Index entries that name no file of the vault, and curated notes that no index names.

    An entry is a path relative to `Memoria-CC/`, as Markdown and the original read it: `../`
    goes up (`../Lecciones/x.md` names `Lecciones/x.md`) and a branch `MEMORY-<tema>.md` is a
    file like any other (memory-format-conformance D5). `known` is every file the confined
    walk saw, so the answer never depends on anything outside the vault: an entry that climbs
    out of it names nothing the harness may look at, and is reported as dangling.
    """
    present = set(known)
    named: set[str] = set()
    dangling: list[str] = []
    for index in indexes:
        for line in index.text.split("\n"):
            match = _INDEX_ENTRY_RE.match(line)
            if not match or "://" in match.group(1):
                continue
            target = _index_target(match.group(1))
            named.add(target)
            if target not in present:
                dangling.append(f"{index.relative} -> {target}")
    orphans = [relative for relative in curated if relative not in named]
    return dangling, orphans


def _index_target(entry: str) -> str:
    """The vault path an index entry names, with `.` and `..` resolved as text (nothing on
    disk is looked at). One that climbs out of the vault keeps a leading `..` and so names no
    file of the walk."""
    parts: list[str] = []
    for part in f"{CURATED_MEMORY}/{entry.split('#', 1)[0]}".split("/"):
        if part in ("", "."):
            continue
        if part == ".." and parts and parts[-1] != "..":
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)


def _duplicate_candidates(curated: list[str], budget: _Budget) -> list[str]:
    """Pairs of curated notes whose names are similar enough to be the same note. Every pair
    is compared (quadratic): the comparisons stop when the budget is spent (F-07)."""
    ordered = sorted(curated)
    pairs: list[str] = []
    for i, first in enumerate(ordered):
        for second in ordered[i + 1 :]:
            similar = _similar(_stem(first), _stem(second), DUPLICATE_THRESHOLD, budget,
                               strict=True)
            if similar is None:
                return pairs
            if similar:
                pairs.append(f"{first} ~ {second}")
    return pairs
