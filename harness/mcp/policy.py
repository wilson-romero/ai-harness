"""Deny-by-default policy for MCP tool calls (mcp-gateway D5). Pure functions, no effects.

The policy lives in the local allowlist. What a server says about a tool (description, input
schema, annotations such as `readOnlyHint`) can only make a call fail (`tool_absent`,
`schema_mismatch`, `annotation_conflict`); it can never allow anything the allowlist does not.
A server schema is only compared by shape (property names, `required`): no pattern, format or
other construct a server sends is ever evaluated by the harness.

Checks and reasons, in the order they are applied (the first failure wins):

1. `recursion` (by the caller, before anything is read: see `client.RECURSION_MARKER`)
2. `server_not_allowed`
3. `args_too_large`, `args_not_json`, `args_not_object`
4. `tool_not_allowed`
5. `argument_not_allowed`, `argument_missing`, `argument_invalid`
6. `write_requires_approval`
7. after `list_tools`: `tool_absent`, `schema_mismatch`, `annotation_conflict` (a tool the
   allowlist declares `read` that the server annotates `readOnlyHint: false` or
   `destructiveHint: true`; added after the independent review of 2026-11-24)

1 to 6 need no server, so a call they deny never starts a process.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from harness.core.errors import InvalidInput
from harness.core.strict_json import loads_strict
from harness.mcp.config import (
    BooleanArgument,
    EnumArgument,
    IntegerArgument,
    LoadedConfig,
    StringArgument,
    ToolEntry,
)
from harness.text.safe_text import safe_foreign_line

MAX_ARGS_BYTES = 16 * 1024
ALLOWED = "allowed"
# Every reason a call can be denied with. The audit table refuses any other value.
DENIAL_REASONS = (
    "recursion",
    "server_not_allowed",
    "args_too_large",
    "args_not_json",
    "args_not_object",
    "tool_not_allowed",
    "argument_not_allowed",
    "argument_missing",
    "argument_invalid",
    "write_requires_approval",
    "tool_absent",
    "schema_mismatch",
    "annotation_conflict",
)
# Reasons that are a misuse of the command line (exit code 2) rather than a refusal.
USAGE_REASONS = frozenset({"args_too_large", "args_not_json", "args_not_object"})


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str  # ALLOWED or one of DENIAL_REASONS
    detail: str = ""  # already cleaned and short: safe to print, never stored
    operation: str | None = None

    @classmethod
    def deny(cls, reason: str, detail: str = "", operation: str | None = None) -> Decision:
        assert reason in DENIAL_REASONS
        return cls(False, reason, detail, operation)


@dataclass(frozen=True)
class ParsedArguments:
    """The `--args` text, measured and parsed before any policy decision."""

    value: Any  # the parsed JSON value, or None when `problem` is set
    problem: str | None  # args_too_large, args_not_json or None
    size: int  # bytes of the UTF-8 text as given
    canonical: bytes  # canonical JSON of `value` (empty when `problem` is set)


def parse_arguments(text: str) -> ParsedArguments:
    """Measure first, then parse: a text over the limit is never parsed."""
    raw = text.encode("utf-8", errors="surrogatepass")
    if len(raw) > MAX_ARGS_BYTES:
        return ParsedArguments(None, "args_too_large", len(raw), b"")
    try:
        text.encode("utf-8")  # a lone surrogate (undecodable command-line bytes) is not JSON text
        # Depth measured before parsing, duplicates and NaN refused (skill-engine's strict JSON).
        value = loads_strict(text, max_bytes=MAX_ARGS_BYTES, what="--args")
        canonical = canonical_json(value)
    except (InvalidInput, ValueError, RecursionError):
        return ParsedArguments(None, "args_not_json", len(raw), b"")
    return ParsedArguments(value, None, len(raw), canonical)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def decide_before_start(
    config: LoadedConfig, server: str, tool: str, arguments: ParsedArguments
) -> Decision:
    """Checks 2 to 6: everything that can be decided without starting the server."""
    entry = config.servers.get(server)
    if entry is None:
        return Decision.deny("server_not_allowed", f"server {_name(server)} is not allowed")
    if arguments.problem == "args_too_large":
        return Decision.deny(
            "args_too_large", f"--args is {arguments.size} bytes; the limit is {MAX_ARGS_BYTES}"
        )
    if arguments.problem is not None:
        return Decision.deny(arguments.problem, "--args is not valid JSON")
    if not isinstance(arguments.value, dict):
        return Decision.deny("args_not_object", "--args must be a JSON object")
    declared = entry.tools.get(tool)
    if declared is None:
        return Decision.deny("tool_not_allowed", f"tool {_name(tool)} is not allowed")
    problem = check_arguments(declared, arguments.value)
    if problem is not None:
        return Decision.deny(*problem, operation=declared.operation)
    if declared.operation != "read":
        return Decision.deny(
            "write_requires_approval",
            f"tool {tool} writes; writes need a human approval that this build does not offer",
            operation=declared.operation,
        )
    return Decision(True, ALLOWED, operation=declared.operation)


def check_arguments(declared: ToolEntry, arguments: Mapping[str, Any]) -> tuple[str, str] | None:
    """(reason, detail) of the first argument problem, or None. Names first, then values."""
    for name in sorted(arguments):
        if name not in declared.arguments:
            return "argument_not_allowed", f"argument {_name(name)} is not allowed"
    for name in sorted(declared.arguments):
        if declared.arguments[name].required and name not in arguments:
            return "argument_missing", f"argument {name} is required"
    for name in sorted(arguments):
        if not _valid(declared.arguments[name], arguments[name]):
            return "argument_invalid", f"argument {name} does not meet its declared type or limits"
    return None


def _valid(spec: Any, value: Any) -> bool:
    if isinstance(spec, StringArgument):
        if not isinstance(value, str) or len(value) > spec.max_length:
            return False
        return spec.pattern is None or re.fullmatch(spec.pattern, value) is not None
    if isinstance(spec, IntegerArgument):
        return type(value) is int and spec.minimum <= value <= spec.maximum
    if isinstance(spec, BooleanArgument):
        return type(value) is bool
    if isinstance(spec, EnumArgument):
        return isinstance(value, str) and value in spec.values
    return False


def decide_offered(
    declared: ToolEntry, offered_schema: Any | None, tool: str, annotations: Any = None
) -> Decision:
    """Check 7, once `list_tools` has answered: the server must offer the tool, compatibly.

    `offered_schema` is the input schema the server sent (untrusted), or None if the tool was
    not offered. The schema must accept every declared argument and require none that is not
    declared; anything malformed counts as a mismatch.
    """
    if offered_schema is None:
        return Decision.deny("tool_absent", f"the server does not offer tool {tool}")
    properties = offered_schema.get("properties", {}) if isinstance(offered_schema, dict) else None
    required = offered_schema.get("required", []) if isinstance(offered_schema, dict) else None
    if not isinstance(properties, dict) or not isinstance(required, list):
        return Decision.deny("schema_mismatch", f"tool {tool}: the server's input schema is malformed")
    missing = sorted(name for name in declared.arguments if name not in properties)
    if missing:
        return Decision.deny(
            "schema_mismatch", f"tool {tool}: the server's schema has no argument {_name(missing[0])}"
        )
    extra = [name for name in required if not isinstance(name, str) or name not in declared.arguments]
    if extra:
        return Decision.deny(
            "schema_mismatch", f"tool {tool}: the server requires an argument the allowlist does not declare"
        )
    if declared.operation == "read" and _says_it_writes(annotations):
        return Decision.deny(
            "annotation_conflict",
            f"tool {tool}: the allowlist declares it read-only but the server says it writes",
            operation=declared.operation,
        )
    return Decision(True, ALLOWED, operation=declared.operation)


def _says_it_writes(annotations: Any) -> bool:
    """Only explicit statements count: MCP's defaults are not read as a claim either way."""
    if not isinstance(annotations, Mapping):
        return False
    return annotations.get("readOnlyHint") is False or annotations.get("destructiveHint") is True


def _name(text: str) -> str:
    """A name taken from the command line or a server, fit to print: cleaned and short."""
    return repr(safe_foreign_line(text).text[:64])


# -- the shape of a structured result (independent review of 2026-11-24, finding 1) ------------

SHAPE_MAX_DEPTH = 32
SHAPE_MAX_STEPS = 1_000_000
_JSON_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


def matches_shape(schema: Any, value: Any) -> bool:
    """Does `value` have the shape `schema` describes? A server's output schema is untrusted.

    Only `type`, `required`, `properties`, `items` (one schema) and `additionalProperties:
    false` are read. Everything else (`pattern`, `patternProperties`, `format`, `anyOf`,
    `$ref`, ...) is ignored: nothing a server sends is ever compiled or run as a pattern. The
    work is bounded by `SHAPE_MAX_STEPS` and the depth by `SHAPE_MAX_DEPTH`; past either the
    answer is "no" (fail closed).
    """
    budget = [SHAPE_MAX_STEPS]
    return _shape(schema, value, 0, budget) and budget[0] >= 0


def _shape(schema: Any, value: Any, depth: int, budget: list[int]) -> bool:
    budget[0] -= 1
    if budget[0] < 0 or depth > SHAPE_MAX_DEPTH:
        return False
    if not isinstance(schema, Mapping):
        return True  # `true`, or something that is not a schema: no constraint is read
    if not _type_ok(schema.get("type"), value):
        return False
    if isinstance(value, dict):
        return _object_ok(schema, value, depth, budget)
    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, Mapping):
            return all(_shape(items, item, depth + 1, budget) for item in value)
    return True


def _type_ok(kind: Any, value: Any) -> bool:
    if isinstance(kind, str):
        check = _JSON_TYPES.get(kind)
        return check is None or check(value)
    if isinstance(kind, list):
        known = [_JSON_TYPES[k] for k in kind[:8] if isinstance(k, str) and k in _JSON_TYPES]
        return not known or any(check(value) for check in known)
    return True


def _object_ok(schema: Mapping, value: dict, depth: int, budget: list[int]) -> bool:
    required = schema.get("required")
    if isinstance(required, list):
        budget[0] -= len(required)
        if budget[0] < 0:
            return False
        if any(isinstance(name, str) and name not in value for name in required):
            return False
    properties = schema.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    closed = schema.get("additionalProperties") is False
    for key, item in value.items():
        if key in properties:
            if not _shape(properties[key], item, depth + 1, budget):
                return False
        elif closed:
            return False
    return True
