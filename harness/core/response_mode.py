"""The response mode of a session (change response-mode).

`auto` lets the provider's page choose; `quick` and `deep` ask for a short or a reasoned answer.
A mode is a word from this closed list, never anything a model or a page wrote.
"""

from __future__ import annotations

from enum import StrEnum

from harness.core.errors import UsageError


class ResponseMode(StrEnum):
    AUTO = "auto"
    QUICK = "quick"
    DEEP = "deep"


MODE_WORDS = "auto, quick or deep"


def parse_mode(raw: str) -> ResponseMode:
    """A mode typed by a person: exactly one of the three words."""
    try:
        return ResponseMode(raw)
    except ValueError:
        shown = raw if raw.isascii() and raw.isprintable() and len(raw) <= 20 else "that"
        raise UsageError(f"unknown response mode {shown!r}; use {MODE_WORDS}") from None


def describe_mode(requested: ResponseMode | None, confirmed: ResponseMode | None) -> str | None:
    """How a request's mode is shown, or None when there is nothing to say: a request from
    before modes existed, or the automatic mode left to the page (design D5)."""
    if requested is None or (requested is ResponseMode.AUTO and confirmed in (None,
                                                                             ResponseMode.AUTO)):
        return None
    if confirmed is None:
        return f"mode {requested} not confirmed"
    if confirmed is requested:
        return f"mode {confirmed}"
    return f"mode {confirmed} (asked {requested})"
