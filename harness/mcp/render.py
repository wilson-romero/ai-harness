"""What a tool result may show of itself (mcp-gateway D7). A result is untrusted data.

The size limit is enforced earlier, by the transport, on the message as it arrived and before
it is parsed. Here every text of the result (each text block, and every key and every string
of a structured result, at any depth) goes through the same cleaning and redaction as vault
text: invisible and control characters are dropped first, then known credentials are masked.
Everything is linear in the size of the result. Nothing of the result is interpreted: a result
that reads like an instruction or a tool call is just printed, cleaned.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import mcp_types as types

from harness.text.safe_text import safe_foreign_line, safe_foreign_text

MAX_DEPTH = 32
DESCRIPTION_CHARS = 120
NAME_CHARS = 64


@dataclass(frozen=True)
class Rendered:
    text: str
    redactions: int


def render_result(result: types.CallToolResult) -> Rendered:
    """The text to print for a result that is not an error."""
    if result.structured_content is not None:
        counter = _Counter()
        cleaned = _clean(result.structured_content, counter, 0)
        text = json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True)
        return Rendered(text, counter.count)
    return _render_blocks(result.content)


def render_error(result: types.CallToolResult) -> Rendered:
    """The message of a result marked as an error (printed on stderr)."""
    return _render_blocks(result.content)


def clean_description(text: str) -> str:
    """A server's tool description for one line of `mcp tools`: cleaned whole, then cut."""
    return _cut(safe_foreign_line(text).text, DESCRIPTION_CHARS)


def clean_name(text: str) -> str:
    return _cut(safe_foreign_line(text).text, NAME_CHARS)


def _render_blocks(blocks: list[Any]) -> Rendered:
    parts: list[str] = []
    redactions = 0
    for block in blocks:
        if isinstance(block, types.TextContent):
            cleaned = safe_foreign_text(block.text)
            parts.append(cleaned.text)
            redactions += cleaned.count
        elif isinstance(block, (types.ImageContent, types.AudioContent)):
            parts.append(f"[{block.type} withheld: {len(block.data)} bytes of base64]")
        else:
            parts.append(f"[{_kind(block)} withheld]")
    return Rendered("\n".join(parts), redactions)


class _Counter:
    def __init__(self) -> None:
        self.count = 0


def _clean(value: Any, counter: _Counter, depth: int) -> Any:
    if depth > MAX_DEPTH:
        return "[nested too deep]"
    if isinstance(value, str):
        cleaned = safe_foreign_text(value)
        counter.count += cleaned.count
        return cleaned.text
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        next_suffix: dict[str, int] = {}
        for key, item in value.items():
            cleaned_key = safe_foreign_line(str(key))
            counter.count += cleaned_key.count
            name = base = cleaned_key.text
            # Two keys that clean to the same text both stay visible. The next free suffix is
            # remembered per base, so many colliding keys cost linear time, not quadratic.
            while name in out:
                suffix = next_suffix.get(base, 2)
                next_suffix[base] = suffix + 1
                name = f"{base} ({suffix})"
            out[name] = _clean(item, counter, depth + 1)
        return out
    if isinstance(value, list):
        return [_clean(item, counter, depth + 1) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"[{type(value).__name__} withheld]"


def _kind(block: Any) -> str:
    kind = getattr(block, "type", None)
    return kind if isinstance(kind, str) and kind.isidentifier() and len(kind) <= 32 else "content"


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
