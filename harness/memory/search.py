"""`memory search`: a plain text scan of the vault, without an index (D5)."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from harness.core.errors import InvalidInput
from harness.memory.notes import load_note, project_section
from harness.memory.paths import SKIP_UNREADABLE, resolve_project, walk_vault
from harness.memory.redaction import PRIVATE_KEY, redact

QUERY_MAX_CHARS = 200
QUERY_MAX_TERMS = 10
DEFAULT_LIMIT = 20
MAX_LIMIT = 200
SNIPPET_MAX_CHARS = 160

# Bidirectional controls can reorder what the terminal shows ("trojan source").
_BIDI_CONTROLS = frozenset("‎‏‪‫‬‭‮⁦⁧⁨⁩")


@dataclass(frozen=True)
class SearchHit:
    relative: str  # safe for the terminal
    updated: str | None
    matches: int
    snippet: str  # redacted, without control characters


@dataclass(frozen=True)
class SearchResult:
    hits: tuple[SearchHit, ...]
    omitted: int  # matches beyond the limit
    skipped_counts: Mapping[str, int]
    redactions: int  # substitutions made in the printed snippets
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
        except OSError:
            skipped[SKIP_UNREADABLE] = skipped.get(SKIP_UNREADABLE, 0) + 1
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
        redactions += replaced
        hits.append(
            SearchHit(
                relative=terminal_safe(relative),
                updated=updated,
                matches=matches,
                snippet=terminal_safe(snippet)[:SNIPPET_MAX_CHARS],
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
    """The first line with a term, redacted, and how many substitutions that took.

    A line inside a multi-line private key block is replaced as a whole: no single line of
    the key's body has a recognisable format of its own.
    """
    key_spans = [match.span() for match in PRIVATE_KEY.finditer(text)]
    start = 0
    for line in text.split("\n"):
        end = start + len(line)
        if any(term in line.casefold() for term in terms):
            if any(start < key_end and end > key_start for key_start, key_end in key_spans):
                return "[REDACTED:private-key]", 1
            redacted = redact(line.strip())
            return redacted.text, redacted.count
        start = end + 1
    return "", 0


def terminal_safe(text: str) -> str:
    """Drop control and bidirectional characters; a tab becomes a space (it separates columns)."""
    out = []
    for char in text:
        if char == "\t":
            out.append(" ")
        elif unicodedata.category(char) == "Cc" or char in _BIDI_CONTROLS:
            continue
        else:
            out.append(char)
    return "".join(out)
