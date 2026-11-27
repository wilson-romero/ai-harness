"""The plan of code mode: read, validate and canonicalise it (code-mode slice 1, D1-D6).

A plan is a JSON object the model writes in its reply: a short list of MCP read calls that the
harness, not the model, will run later through the same gateway as `mcp call`. This module only
reads it. It is a pure function of the reply text, the nonce of the question and the local
allowlist: no file, process, network, clock or randomness, and nothing is started. A server is
never asked anything here; what the allowlist decides without a server is all that counts.

Version 1 of the plan (`ai-harness/plan/1`):

    {"format": "ai-harness/plan/1", "nonce": "<16 hex of this question>",
     "steps": [{"id": "a", "server": "synthetic", "tool": "get_project_metadata",
                "args": {"project": "demo-alpha"}}]}

No references between steps, no expressions, no loops, no `return`: every argument is a
literal (D2). The reply holds either no plan (a final answer) or exactly one fenced `json`
block with it. The checks run in this order and the first failure wins, so a plan is refused
for one stated reason:

1. the reply: `reply_too_large`;
2. the block (D3): no `json` block and no nonce anywhere is no plan at all;
   `too_many_blocks`, `block_not_closed`; the nonce only inside a block with another label
   (`wrong_language`) or only outside any block, quoted or indented (`plan_outside_block`);
   once the block is chosen, the nonce more than once anywhere in the reply
   (`nonce_elsewhere`: a second copy the person could see rendered, review finding 3);
3. the JSON (`loads_strict`, D4): a raw lone surrogate in the block (`invisible_character`),
   `plan_too_large`, `plan_too_deep`, `duplicate_key`, `not_finite` (also `1e400`),
   `not_json`; `not_an_object`;
4. the text of every key and string (D5): `invisible_character`, `not_nfc`,
   `credential_in_plan`, and `invisible_character` again for a string any display path
   would change (a newline, U+2028, U+2029: what is shown equals what is sent);
5. the nonce, before the schema, so that a plan of another question says so: `nonce_missing`,
   `nonce_mismatch`;
6. the closed schema: `unsupported_format`, `unknown_field`, `missing_field`,
   `invalid_field`, `no_steps`, `too_many_steps`; then `duplicate_step_id`;
7. each step in order, naming it (D6): `reference_not_supported`, then the gateway's own
   checks without a server (`decide_before_start`): `server_not_allowed`, `tool_not_allowed`,
   `argument_not_allowed`, `argument_missing`, `argument_invalid`, and `write_not_allowed`
   for a tool the allowlist declares `write`.

`read_plan_reply` adds, before all of them, `reply_not_completed` and `reply_truncated`: an
uncertain, failed or truncated reply is never read, even when its text holds a plan.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harness.core.contracts import LLMResponse, RequestStatus
from harness.core.strict_json import StrictJsonError, loads_strict
from harness.mcp.config import LoadedConfig
from harness.mcp.policy import (
    MAX_ARGS_BYTES,
    canonical_json,
    decide_before_start,
    parse_arguments,
)
from harness.skills.approvals import is_invisible, normalise_content
from harness.skills.checks import split_fences
from harness.text.redaction import secret_kinds
from harness.text.safe_text import safe_foreign_line, terminal_safe

PLAN_FORMAT = "ai-harness/plan/1"
PLAN_HASH_DOMAIN = b"ai-harness/plan/v1\n"
MAX_REPLY_CHARS = 200_000  # the provider's own reading bound (`REPLY_MAX_CHARS`)
MAX_PLAN_BYTES = 16 * 1024
MAX_PLAN_DEPTH = 6  # plan, steps, step, args, value; one level left for a refused `$ref`
MAX_STEPS = 10
MAX_DETAIL_CHARS = 200
NONCE_PATTERN = r"[0-9a-f]{16}"
STEP_ID_PATTERN = r"[a-z][a-z0-9_]{0,15}"
REFERENCE_KEY = "$ref"

REFUSAL_REASONS = (
    "reply_not_completed",
    "reply_truncated",
    "reply_too_large",
    "too_many_blocks",
    "block_not_closed",
    "wrong_language",
    "plan_outside_block",
    "nonce_elsewhere",
    "plan_too_large",
    "plan_too_deep",
    "duplicate_key",
    "not_finite",
    "not_json",
    "not_an_object",
    "invisible_character",
    "not_nfc",
    "credential_in_plan",
    "nonce_missing",
    "nonce_mismatch",
    "unsupported_format",
    "unknown_field",
    "missing_field",
    "invalid_field",
    "no_steps",
    "too_many_steps",
    "duplicate_step_id",
    "reference_not_supported",
    "server_not_allowed",
    "tool_not_allowed",
    "argument_not_allowed",
    "argument_missing",
    "argument_invalid",
    "write_not_allowed",
)
# The gateway's `args_too_large` cannot happen inside a plan: the arguments of a step are a
# part of the plan, and the whole plan is already held to a bound no larger than theirs.
assert MAX_PLAN_BYTES <= MAX_ARGS_BYTES
_JSON_KINDS = {"too_large": "plan_too_large", "too_deep": "plan_too_deep",
               "duplicate_key": "duplicate_key", "not_finite": "not_finite",
               "not_json": "not_json"}
# A policy reason a step can be refused with, as the plan names it.
_POLICY_REASONS = {"server_not_allowed": "server_not_allowed",
                   "tool_not_allowed": "tool_not_allowed",
                   "argument_not_allowed": "argument_not_allowed",
                   "argument_missing": "argument_missing",
                   "argument_invalid": "argument_invalid",
                   "write_requires_approval": "write_not_allowed"}


# -- what reading gives --------------------------------------------------------------------------


@dataclass(frozen=True)
class NoPlan:
    """The reply has no plan: it is a final answer, to be shown as foreign text."""


@dataclass(frozen=True)
class Refusal:
    """The reply tried to hold a plan and nothing of it may run. `detail` is short, cleaned
    and never repeats an argument value; `step` names the step when one is at fault."""

    reason: str
    detail: str
    step: str | None = None

    def __post_init__(self) -> None:
        assert self.reason in REFUSAL_REASONS


@dataclass(frozen=True)
class PlanStep:
    id: str
    server: str
    tool: str
    operation: str  # what the allowlist declares: always "read" in a plan of version 1
    arguments: Mapping[str, Any]  # read-only; every value a JSON scalar
    canonical_arguments: bytes  # what the gateway would receive, byte for byte


@dataclass(frozen=True)
class Plan:
    """A validated plan. `canonical` is what an approval shows and hashes and what runs."""

    nonce: str
    steps: tuple[PlanStep, ...]
    canonical: bytes
    sha256: str


Reading = NoPlan | Refusal | Plan


def plan_hash(canonical: bytes) -> str:
    return hashlib.sha256(PLAN_HASH_DOMAIN + canonical).hexdigest()


# -- the closed schema ---------------------------------------------------------------------------


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _StepModel(_Closed):
    id: str = Field(pattern=f"^{STEP_ID_PATTERN}$")
    server: str = Field(min_length=1, max_length=64)
    tool: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict, max_length=64)


class _PlanModel(_Closed):
    format: Literal["ai-harness/plan/1"]
    nonce: str
    steps: list[_StepModel] = Field(min_length=1, max_length=MAX_STEPS)


# -- reading -------------------------------------------------------------------------------------


def read_plan_reply(response: LLMResponse, *, nonce: str, config: LoadedConfig) -> Reading:
    """`read_plan` on a provider's reply, which is read only if it completed whole."""
    if response.status != RequestStatus.COMPLETED or response.text is None:
        return Refusal("reply_not_completed",
                       f"the reply is {response.status.value}; it is never read for a plan")
    if response.truncated:
        return Refusal("reply_truncated", "the reply was read only in part; it is never read "
                                          "for a plan")
    return read_plan(response.text, nonce=nonce, config=config)


def read_plan(text: str, *, nonce: str, config: LoadedConfig) -> Reading:
    """The plan in `text`, a refusal with its reason, or no plan. See the module docstring."""
    if not re.fullmatch(NONCE_PATTERN, nonce):
        raise ValueError("the expected nonce must be 16 lowercase hexadecimal characters")
    if len(text) > MAX_REPLY_CHARS:
        return Refusal("reply_too_large", f"the reply is longer than {MAX_REPLY_CHARS} "
                                          "characters")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    body = _block(text, nonce)
    if not isinstance(body, str):
        return body
    if text.count(nonce) > 1:
        # Anywhere else (a quote, an HTML comment, `<details>`, a list item, the prose, or a
        # second time inside the block), the person could see a plan other than the one read.
        return Refusal("nonce_elsewhere", "the nonce appears more than once in the reply; "
                                          "it must appear only in the plan's nonce field")
    try:
        body.encode("utf-8")
    except UnicodeEncodeError:  # a raw lone surrogate: not text that can be shown or sent
        return Refusal("invisible_character", "an invisible character in the plan")
    try:
        data = loads_strict(body, max_bytes=MAX_PLAN_BYTES, what="the plan",
                            max_depth=MAX_PLAN_DEPTH)
    except StrictJsonError as exc:
        return Refusal(_JSON_KINDS[exc.kind], _clean(str(exc)))
    if not isinstance(data, dict):
        return Refusal("not_an_object", "the plan must be a JSON object")
    problem = _text_problem(data, "plan")
    if problem is not None:
        return problem
    if "nonce" not in data:
        return Refusal("nonce_missing", "the plan has no nonce")
    found = data["nonce"]
    if not isinstance(found, str) or not hmac.compare_digest(found.encode(), nonce.encode()):
        return Refusal("nonce_mismatch", "the plan's nonce is not the one of this question")
    try:
        model = _PlanModel.model_validate(data)
    except ValidationError as exc:
        return _schema_refusal(exc)
    return _steps(model, config)


def _block(text: str, nonce: str) -> str | Refusal | NoPlan:
    """The body of the only `json` block, or why there is none (D3)."""
    outside, fences = split_fences(text)
    blocks = [f for f in fences if [w.casefold() for w in f.info.split()[:1]] == ["json"]]
    if len(blocks) > 1:
        return Refusal("too_many_blocks", f"the reply has {len(blocks)} json blocks; a plan "
                                          "is exactly one")
    if blocks:
        if not blocks[0].closed:
            return Refusal("block_not_closed", "the json block is never closed")
        return "\n".join(blocks[0].body)
    if any(nonce in line for fence in fences for line in fence.body):
        return Refusal("wrong_language", "the plan is in a block not labelled json")
    if any(nonce in line for line in outside):
        return Refusal("plan_outside_block", "the plan's nonce is outside any fenced block")
    return NoPlan()


def _text_problem(value: Any, where: str) -> Refusal | None:
    """Every key and string of the plan, checked as one text is shown and hashed (D5)."""
    stack: list[tuple[Any, str]] = [(value, where)]
    while stack:
        item, path = stack.pop()
        strings: list[tuple[str, str]] = []
        if isinstance(item, dict):
            for key, inner in item.items():
                strings.append((key, f"{path} key"))
                stack.append((inner, f"{path}.{_clean(key)[:32]}"))
        elif isinstance(item, list):
            stack.extend((inner, f"{path}[{n}]") for n, inner in enumerate(item))
        elif isinstance(item, str):
            strings.append((item, path))
        for string, at in strings:
            reason = string_refusal(string)
            if reason is not None:
                return Refusal(reason, f"{_WHAT[reason]} in {at}")
    return None


_WHAT = {"invisible_character": "an invisible character",
         "not_nfc": "a text not in Unicode NFC form",
         "credential_in_plan": "a credential"}


def string_refusal(string: str) -> str | None:
    """Why one key or string of a plan cannot be shown, hashed and sent as it is, or None.

    One rule (independent review, finding 2): what is shown equals what is sent. Besides the
    invisible characters, a string that any display path would change (`normalise_content`
    for the approval, `terminal_safe` for one line) is refused as `invisible_character`: that
    catches a newline and the line and paragraph separators U+2028 and U+2029, which those
    paths drop. NFC and credentials keep their own reasons and are checked first.
    """
    if any(is_invisible(c) for c in string):
        return "invisible_character"
    if unicodedata.normalize("NFC", string) != string:
        return "not_nfc"
    if secret_kinds(string):
        return "credential_in_plan"
    if terminal_safe(string) != string or normalise_content(string) != string:
        return "invisible_character"
    return None


def _schema_refusal(exc: ValidationError) -> Refusal:
    error = exc.errors(include_url=False, include_input=False, include_context=False)[0]
    location = ".".join(str(part) for part in error["loc"]) or "(top level)"
    kind = error["type"]
    if kind == "extra_forbidden":
        reason = "unknown_field"
    elif kind == "missing":
        reason = "missing_field"
    elif error["loc"] == ("format",):
        reason = "unsupported_format"
    elif error["loc"] == ("steps",) and kind == "too_short":
        reason = "no_steps"
    elif error["loc"] == ("steps",) and kind == "too_long":
        reason = "too_many_steps"
    else:
        reason = "invalid_field"
    return Refusal(reason, _clean(f"{location}: {error['msg']}"))


def _steps(model: _PlanModel, config: LoadedConfig) -> Plan | Refusal:
    seen: set[str] = set()
    for item in model.steps:
        if item.id in seen:
            return Refusal("duplicate_step_id", f"step id {item.id} is used twice", item.id)
        seen.add(item.id)
    steps: list[PlanStep] = []
    for item in model.steps:
        if any(isinstance(v, dict) and REFERENCE_KEY in v for v in item.args.values()):
            return Refusal("reference_not_supported", "a plan of version 1 has no references "
                                                      "between steps; every argument is a "
                                                      "literal", item.id)
        canonical = canonical_json(item.args)
        decision = decide_before_start(config, item.server, item.tool,
                                       parse_arguments(canonical.decode("utf-8")))
        if not decision.allowed:
            return Refusal(_POLICY_REASONS[decision.reason], _clean(decision.detail), item.id)
        steps.append(PlanStep(item.id, item.server, item.tool, str(decision.operation),
                              MappingProxyType(dict(item.args)), canonical))
    whole = canonical_json(model.model_dump(mode="python"))
    return Plan(model.nonce, tuple(steps), whole, plan_hash(whole))


def _clean(text: str) -> str:
    return safe_foreign_line(text).text[:MAX_DETAIL_CHARS]
