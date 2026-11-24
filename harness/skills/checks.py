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
from harness.memory.safe_text import safe_text
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


def _headings(step: ValidateStep, text: str) -> None:
    found = set()
    for line in text.split("\n"):
        stripped = line.strip()
        level = len(stripped) - len(stripped.lstrip("#"))
        if 1 <= level <= 6 and stripped[level : level + 1] == " ":
            found.add(stripped[level:].strip().rstrip("#").strip().casefold())
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
    """The inside of the only ```json block, or the whole text if there is none."""
    lines = text.split("\n")
    opens = [i for i, line in enumerate(lines) if line.strip().casefold() == "```json"]
    if not opens:
        return text
    if len(opens) > 1:
        raise _Fail("json_block")
    start = opens[0] + 1
    for end in range(start, len(lines)):
        if lines[end].strip() == "```":
            return "\n".join(lines[start:end])
    raise _Fail("json_block")


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
