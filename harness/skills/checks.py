"""Deterministic checks of a `validate` step (skill-engine D6).

Only declared rules, no regular expression written in a skill, no interpretation of the text.
The output of a passing step is the normalised, redacted text, or canonical JSON for the
`json` format: the same input always gives the same bytes.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any

from harness.core.errors import InvalidInput
from harness.core.strict_json import loads_strict
from harness.text.safe_text import safe_text
from harness.skills.definition import FieldSpec, ValidateStep

_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


@dataclass(frozen=True)
class CheckResult:
    output: str | None  # None when the check failed
    error_code: str | None = None
    fields: dict[str, Any] | None = None  # parsed fields of a passing json check

    @property
    def ok(self) -> bool:
        return self.output is not None


class _Fail(Exception):
    def __init__(self, rule: str, field: str = "-") -> None:
        super().__init__(f"validation_failed:{rule}:{field}")
        self.code = f"validation_failed:{rule}:{field}"


def check(step: ValidateStep, text: str) -> CheckResult:
    try:
        output, fields = _check(step, text)
    except _Fail as failure:
        return CheckResult(None, failure.code)
    return CheckResult(output, None, fields)


def parse_fields(output: str) -> dict[str, Any]:
    """The fields of a stored canonical JSON output (it was produced by `check`)."""
    return json.loads(output)


def _check(step: ValidateStep, text: str) -> tuple[str, dict[str, Any] | None]:
    normalised = safe_text(text).text
    size = len(normalised.encode("utf-8"))
    if size > step.max_bytes:
        raise _Fail("max_bytes")
    if size < step.min_bytes:
        raise _Fail("min_bytes")
    if step.format == "markdown":
        _headings(step, normalised)
        return normalised, None
    if step.format == "text":
        return normalised, None
    data = _json(step, normalised)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return canonical, data


# Fenced code blocks as CommonMark reads them (revised 2026-11-26, after the Copilot reader
# began writing fences longer than three backticks): an opening line of three or more
# backticks or tildes, indented at most three spaces (a backtick fence's info string has no
# backtick); it is closed by a line of the same character, at least as long, indented at most
# three spaces, with nothing else; a fence never closed runs to the end of the text.
_OPEN_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
_CLOSE_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*")
# An ATX heading: one to six `#`, indented at most three spaces (four or more is code), then a
# space or the end of the line.
_HEADING = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*")


@dataclass(frozen=True)
class _Fence:
    info: str  # the info string, trimmed: its first word is the language
    body: list[str]
    closed: bool


def _split(text: str) -> tuple[list[str], list[_Fence]]:
    """The lines outside fenced code blocks, and the fenced blocks, in order."""
    lines = text.split("\n")
    outside: list[str] = []
    fences: list[_Fence] = []
    i = 0
    while i < len(lines):
        opening = _OPEN_FENCE.fullmatch(lines[i])
        if opening is None or (opening.group(1)[0] == "`" and "`" in opening.group(2)):
            outside.append(lines[i])
            i += 1
            continue
        marker = opening.group(1)
        body: list[str] = []
        i += 1
        closed = False
        while i < len(lines):
            closing = _CLOSE_FENCE.fullmatch(lines[i])
            if closing and closing.group(1)[0] == marker[0] and len(closing.group(1)) >= len(marker):
                closed = True
                i += 1
                break
            body.append(lines[i])
            i += 1
        fences.append(_Fence(opening.group(2).strip(), body, closed))
    return outside, fences


Fence = _Fence


def split_fences(text: str) -> tuple[list[str], list[Fence]]:
    """The lines outside fenced code blocks, and the fenced blocks, in order, as `validate`
    reads them. The plan reader of code mode uses this same reading (code-mode D3), so a block
    is a block for both or for neither. `text` must already have `\\n` line ends."""
    return _split(text)


def _headings(step: ValidateStep, text: str) -> None:
    """Headings count only outside fenced code blocks: a heading inside code is code."""
    found = set()
    outside, _ = _split(text)
    for line in outside:
        match = _HEADING.fullmatch(line)
        if match:
            title = re.sub(r"(?:^|[ \t]+)#+[ \t]*$", "", match.group(2) or "")  # closing #s
            found.add(title.strip().casefold())
    for heading in step.required_headings:
        if heading.strip().casefold() not in found:
            raise _Fail("required_headings", heading)


def _json(step: ValidateStep, text: str) -> dict[str, Any]:
    body = _json_body(text)
    try:
        data = loads_strict(body, max_bytes=step.max_bytes, what="the output")
    except InvalidInput:
        raise _Fail("json") from None
    if not isinstance(data, dict):
        raise _Fail("json_object")
    extra = sorted(set(data) - set(step.fields))
    if extra:
        raise _Fail("extra_field", extra[0])
    result: dict[str, Any] = {}
    for name, spec in step.fields.items():
        if name not in data:
            if spec.required:
                raise _Fail("missing_field", name)
            continue
        result[name] = _field(name, spec, data[name])
    return result


def _json_body(text: str) -> str:
    """The inside of the only fenced block labelled `json` (any fence length, backticks or
    tildes), or the whole text if there is none. Two such blocks, or one never closed, fail."""
    _, fences = _split(text)
    blocks = [f for f in fences if [w.casefold() for w in f.info.split()[:1]] == ["json"]]
    if not blocks:
        return text
    if len(blocks) > 1 or not blocks[0].closed:
        raise _Fail("json_block")
    return "\n".join(blocks[0].body)


def _field(name: str, spec: FieldSpec, value: Any) -> Any:
    if spec.type == "boolean":
        if not isinstance(value, bool):
            raise _Fail("type", name)
        return value
    if spec.type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise _Fail("type", name)
        if spec.min is not None and value < spec.min:
            raise _Fail("min", name)
        if spec.max is not None and value > spec.max:
            raise _Fail("max", name)
        return value
    if spec.type == "string":
        return _string(name, spec, value)
    if not isinstance(value, list):
        raise _Fail("type", name)
    if spec.max_items is not None and len(value) > spec.max_items:
        raise _Fail("max_items", name)
    return [_string(name, spec, item) for item in value]


def _string(name: str, spec: FieldSpec, value: Any) -> str:
    if not isinstance(value, str):
        raise _Fail("type", name)
    if spec.single_line and ("\n" in value or "\r" in value):
        raise _Fail("single_line", name)
    # An escaped control or credential inside a JSON string is cleaned here, after decoding.
    value = unicodedata.normalize("NFC", safe_text(value).text)
    if spec.max_length is not None and len(value) > spec.max_length:
        raise _Fail("max_length", name)
    if spec.min_length is not None and len(value) < spec.min_length:
        raise _Fail("min_length", name)
    if spec.enum is not None and value not in spec.enum:
        raise _Fail("enum", name)
    if spec.format == "slug" and not _SLUG_RE.fullmatch(value):
        raise _Fail("format", name)
    if spec.format == "date":
        if not _DATE_RE.fullmatch(value):
            raise _Fail("format", name)
        try:
            date.fromisoformat(value)
        except ValueError:
            raise _Fail("format", name) from None
    return value
