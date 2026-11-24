"""`memory search`: a plain text scan of the vault, without an index (D5)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from harness.core.errors import InvalidInput
from harness.memory.notes import load_note, project_section
from harness.memory.paths import SkippedRead, resolve_project, walk_vault
from harness.memory.redaction import private_key_spans
from harness.memory.safe_text import safe_line, strip_controls

QUERY_MAX_CHARS = 200
QUERY_MAX_TERMS = 10
DEFAULT_LIMIT = 20
MAX_LIMIT = 200
SNIPPET_MAX_CHARS = 160


@dataclass(frozen=True)
class SearchHit:
    relative: str  # cleaned and redacted, like every vault text that is printed
    updated: str | None
    matches: int
    snippet: str  # redacted, without control characters


@dataclass(frozen=True)
class SearchResult:
    hits: tuple[SearchHit, ...]
    omitted: int  # matches beyond the limit
    skipped_counts: Mapping[str, int]
    redactions: int  # substitutions made in what is printed: paths and snippets
    truncated_walk: bool


def parse_query(query: str) -> tuple[str, ...]:
    """Casefolded terms. Raises before anything is read."""
    if len(query) > QUERY_MAX_CHARS:
        raise InvalidInput(f"the query must be at most {QUERY_MAX_CHARS} characters")
    terms = tuple(dict.fromkeys(term.casefold() for term in query.split()))
    if not terms:
        raise InvalidInput("the query must not be empty")
    if len(terms) > QUERY_MAX_TERMS:
        raise InvalidInput(f"the query must have at most {QUERY_MAX_TERMS} terms")
    return terms


def validate_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInput(f"--limit must be between 1 and {MAX_LIMIT}")
    return limit


def search_vault(
    root: Path,
    terms: tuple[str, ...],
    *,
    project: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> SearchResult:
    """Notes containing every term, ordered by matches desc, `updated` desc, path asc."""
    validate_limit(limit)
    if project is not None:
        resolve_project(root, project)
    walk = walk_vault(root)
    skipped = dict(walk.skipped_counts)
    found: list[tuple[int, str | None, str, str]] = []
    for file in walk.files:
        try:
            note = load_note(file)
        except SkippedRead as refused:
            skipped[refused.reason] = skipped.get(refused.reason, 0) + 1
            continue
        if project and project_section(note.relative, note.frontmatter, project) is None:
            continue
        folded = note.text.casefold()
        if not all(term in folded for term in terms):
            continue
        matches = sum(folded.count(term) for term in terms)
        found.append((matches, note.updated, note.relative, note.text))

    found.sort(key=lambda hit: hit[2])
    found.sort(key=lambda hit: hit[1] or "", reverse=True)
    found.sort(key=lambda hit: hit[0], reverse=True)
    hits: list[SearchHit] = []
    redactions = 0
    for matches, updated, relative, text in found[:limit]:
        snippet, replaced = _snippet(text, terms)
        path = safe_line(relative)
        redactions += replaced + path.count
        hits.append(
            SearchHit(
                relative=path.text,
                updated=updated,
                matches=matches,
                snippet=snippet[:SNIPPET_MAX_CHARS],
            )
        )
    return SearchResult(
        hits=tuple(hits),
        omitted=max(0, len(found) - limit),
        skipped_counts=skipped,
        redactions=redactions,
        truncated_walk=walk.truncated,
    )


def _snippet(text: str, terms: tuple[str, ...]) -> tuple[str, int]:
    """The first line with a term, cleaned, redacted, and how many substitutions that took.

    Control characters go first, over the whole text, so that one hidden inside a credential
    cannot hide it from the redaction. A line inside a private key block (including one
    without an END line) is replaced as a whole: no single line of the key's body has a
    recognisable format of its own.
    """
    text = strip_controls(text)
    key_spans = private_key_spans(text)
    start = 0
    for line in text.split("\n"):
        end = start + len(line)
        if any(term in line.casefold() for term in terms):
            if any(start < key_end and end > key_start for key_start, key_end in key_spans):
                return "[REDACTED:private-key]", 1
            redacted = safe_line(line.strip())
            return redacted.text, redacted.count
        start = end + 1
    return "", 0
