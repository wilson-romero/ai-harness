"""Strict JSON for files and texts that are not trusted (skill-engine D3, D6).

The standard parser accepts duplicate keys (the last one wins), `NaN` and `Infinity`, and
recurses once per nesting level. Here the size is checked before anything else, the nesting
depth is measured with a linear scan before parsing, and duplicates and non-finite numbers
are refused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.core.errors import InvalidInput

MAX_DEPTH = 32
# What a refusal was about (code-mode D4: a plan names its reason without reading a message).
KINDS = ("too_large", "too_deep", "duplicate_key", "not_finite", "not_json")


class StrictJsonError(InvalidInput):
    """A refusal of `loads_strict`, with its `kind` (one of KINDS). The message is unchanged."""

    def __init__(self, message: str, kind: str) -> None:
        assert kind in KINDS
        super().__init__(message)
        self.kind = kind


def loads_strict(
    text: str, *, max_bytes: int, what: str = "the JSON text", max_depth: int = MAX_DEPTH
) -> Any:
    """Parse `text` as JSON, refusing what the standard parser lets through.

    Refused, each with its kind: more than `max_bytes` UTF-8 bytes (`too_large`, before any
    parsing); nesting deeper than `max_depth` (`too_deep`, measured with a linear scan, so a
    deep text never reaches the recursive parser); a repeated key in an object
    (`duplicate_key`); `NaN`, `Infinity` or `-Infinity` (`not_finite`); and anything that is
    not one JSON value (`not_json`): syntax errors, data after the value, a leading byte order
    mark, raw control characters inside a string, an integer past the interpreter's digit
    limit. JSON keys are always strings, so a non-string key is a syntax error. `max_depth`
    can only tighten the default. A string escape such as `\\ud800` (a lone surrogate) is
    accepted, as the standard says: a caller that needs valid Unicode checks it.
    """
    if not 0 < max_depth <= MAX_DEPTH:
        raise ValueError(f"max_depth must be between 1 and {MAX_DEPTH}")
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        raise StrictJsonError(f"{what} is larger than {max_bytes} bytes", "too_large")
    if _depth(text, max_depth) > max_depth:
        raise StrictJsonError(f"{what} is nested deeper than {max_depth} levels", "too_deep")
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except _Refused as exc:
        raise StrictJsonError(f"{what}: {exc}", exc.kind) from None
    except (ValueError, RecursionError):
        raise StrictJsonError(f"{what} is not valid JSON", "not_json") from None


def read_text_limited(path: Path, *, max_bytes: int, what: str) -> str:
    """A UTF-8 text file of at most `max_bytes`, never read beyond that bound.

    The size is decided by reading at most one byte more than the limit, so a file that grows
    after a `stat` cannot make this read more. Line ends are normalised to `\\n` and a BOM is
    dropped, so the same file gives the same text on every platform.
    """
    try:
        with path.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError:
        raise InvalidInput(f"{what} cannot be read") from None
    return decode_text_limited(raw, max_bytes=max_bytes, what=what)


def decode_text_limited(raw: bytes, *, max_bytes: int, what: str) -> str:
    """The checks of `read_text_limited` on bytes already read (at most `max_bytes + 1`)."""
    if len(raw) > max_bytes:
        raise InvalidInput(f"{what} is larger than {max_bytes} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidInput(f"{what} is not valid UTF-8") from None
    return text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


class _Refused(Exception):
    def __init__(self, message: str, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _Refused(f"duplicate key {key!r}", "duplicate_key")
        result[key] = value
    return result


def _no_constant(name: str) -> Any:
    raise _Refused(f"{name} is not allowed", "not_finite")


def _depth(text: str, limit: int = MAX_DEPTH) -> int:
    """Deepest bracket nesting outside strings, in one pass."""
    depth = deepest = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > deepest:
                deepest = depth
                if deepest > limit:
                    return deepest
        elif char in "]}":
            depth -= 1
    return deepest
