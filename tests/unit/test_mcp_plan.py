"""The plan reader of code mode as a pure function (code-mode slice 1, tasks 2.x).

Every refusal is a negative control: each case was watched failing before `harness/mcp/plan.py`
existed (receipts in `openspec/changes/code-mode/tasks.md`). Only synthetic names and values.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import random
import re
import socket
import subprocess
import uuid
from pathlib import Path

import pytest

from harness.core.contracts import LLMResponse, RequestStatus
from harness.mcp.config import LoadedConfig, McpConfig
from harness.mcp.plan import (
    MAX_PLAN_BYTES,
    MAX_PLAN_DEPTH,
    MAX_REPLY_CHARS,
    MAX_STEPS,
    PLAN_FORMAT,
    PLAN_HASH_DOMAIN,
    REFUSAL_REASONS,
    NoPlan,
    Plan,
    Refusal,
    read_plan,
    read_plan_reply,
)
from tests.mcp_support import ABSOLUTE_PROGRAM, DEFAULT_TOOLS

CONFIG = LoadedConfig(McpConfig.model_validate({
    "format": "ai-harness/mcp/1",
    "servers": {
        "synthetic": {
            "command": [ABSOLUTE_PROGRAM],
            "tools": {
                **DEFAULT_TOOLS,
                "count_items": {"operation": "read", "arguments": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                    "verbose": {"type": "boolean"},
                }},
            },
        },
        "catalogue": {
            "command": [ABSOLUTE_PROGRAM],
            "tools": {"list_items": {"operation": "read"}},
        },
    },
}))
NONCE = "0123456789abcdef"
FOREIGN_NONCE = "fedcba9876543210"


def step(sid: str, tool: str = "get_project_metadata", server: str = "synthetic", **args):
    return {"id": sid, "server": server, "tool": tool, "args": args}


def plan(*steps, nonce=NONCE, **extra) -> dict:
    return {"format": PLAN_FORMAT, "nonce": nonce,
            "steps": list(steps) or [step("a", project="demo-alpha")], **extra}


def fenced(body: str, label: str = "json", fence: str = "```") -> str:
    return f"{fence}{label}\n{body}\n{fence}"


def reply(body: str | dict, label: str = "json") -> str:
    text = body if isinstance(body, str) else json.dumps(body, indent=2)
    return f"Here is the plan.\n\n{fenced(text, label)}\n\nIt reads two projects."


TWO_READS = plan(step("a", project="demo-alpha"), step("b", project="demo-beta"))


def read(text: str) -> Plan | Refusal | NoPlan:
    return read_plan(text, nonce=NONCE, config=CONFIG)


# -- a valid plan --------------------------------------------------------------------------------


def test_a_valid_plan_is_read_with_its_canonical_bytes_and_hash():
    result = read(reply(TWO_READS))
    assert isinstance(result, Plan)
    assert [s.id for s in result.steps] == ["a", "b"]
    assert [(s.server, s.tool, s.operation) for s in result.steps] == [
        ("synthetic", "get_project_metadata", "read")] * 2
    assert result.steps[0].arguments == {"project": "demo-alpha"}
    assert result.steps[0].canonical_arguments == b'{"project":"demo-alpha"}'
    assert result.nonce == NONCE
    expected = (
        '{"format":"ai-harness/plan/1","nonce":"0123456789abcdef","steps":['
        '{"args":{"project":"demo-alpha"},"id":"a","server":"synthetic",'
        '"tool":"get_project_metadata"},'
        '{"args":{"project":"demo-beta"},"id":"b","server":"synthetic",'
        '"tool":"get_project_metadata"}]}'
    ).encode()
    assert result.canonical == expected
    assert result.sha256 == hashlib.sha256(PLAN_HASH_DOMAIN + expected).hexdigest()


def test_steps_on_two_servers_and_a_tool_without_arguments():
    result = read(reply(plan(step("a", project="demo-alpha"),
                             step("b", "list_items", "catalogue"),
                             step("c", "count_items", limit=3, verbose=True))))
    assert isinstance(result, Plan)
    assert [s.server for s in result.steps] == ["synthetic", "catalogue", "synthetic"]
    assert result.steps[1].arguments == {}
    assert result.steps[2].arguments == {"limit": 3, "verbose": True}


def test_args_may_be_left_out_and_read_as_empty():
    body = plan({"id": "a", "server": "catalogue", "tool": "list_items"})
    result = read(reply(body))
    assert isinstance(result, Plan)
    assert b'"args":{}' in result.canonical


def test_crlf_line_ends_and_a_longer_or_tilde_fence_are_read():
    text = reply(TWO_READS).replace("\n", "\r\n")
    assert isinstance(read(text), Plan)
    assert isinstance(read(fenced(json.dumps(TWO_READS), fence="````")), Plan)
    assert isinstance(read(fenced(json.dumps(TWO_READS), fence="~~~")), Plan)
    assert isinstance(read(fenced(json.dumps(TWO_READS), label="JSON")), Plan)


def test_foreign_text_is_kept_literally_never_expanded():
    value = "~/$HOME/${USER}/{{name}}/%PATH%/$(id)"
    result = read(reply(plan(step("a", "echo_env", name=value))))
    assert isinstance(result, Plan)
    assert result.steps[0].arguments == {"name": value}
    assert json.loads(result.steps[0].canonical_arguments) == {"name": value}


def test_json_escapes_read_as_the_characters_they_stand_for():
    escaped = '{"format":"ai-harness/plan/1","nonce":"0123456789abcdef","steps":[' \
              '{"id":"a","server":"synthetic","tool":"echo_env","args":{"name":"caf\\u00e9"}}]}'
    literal = escaped.replace("\\u00e9", "é")
    first, second = read(fenced(escaped)), read(fenced(literal))
    assert isinstance(first, Plan) and isinstance(second, Plan)
    assert first.sha256 == second.sha256


# -- no plan -------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "The projects are demo-alpha and demo-beta.",
    "Use this:\n\n```python\nprint('hello')\n```\n",
    "",
])
def test_a_reply_without_a_plan_is_a_final_answer(text):
    assert isinstance(read(text), NoPlan)


# -- refusals: one or more cases per reason ------------------------------------------------------

DEEP = '{"format":"ai-harness/plan/1","nonce":"0123456789abcdef","steps":[' + \
       '{"id":"a","server":"synthetic","tool":"echo_env","args":{"name":' + \
       "[" * (MAX_PLAN_DEPTH) + "]" * (MAX_PLAN_DEPTH) + "}}]}"
PLAN_TEXT = json.dumps(TWO_READS, indent=2)
QUOTED = "\n".join("> " + line for line in fenced(PLAN_TEXT).split("\n"))
INDENTED = "\n".join("    " + line for line in fenced(PLAN_TEXT).split("\n"))
NESTED = "````markdown\n" + fenced(PLAN_TEXT) + "\n````"
TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"

CASES = [
    # (case, reply text, reason, step named)
    ("two json blocks", reply(TWO_READS) + "\n\n" + fenced(PLAN_TEXT), "too_many_blocks", None),
    ("a json and a tilde json block", reply(TWO_READS) + "\n" + fenced("{}", fence="~~~"),
     "too_many_blocks", None),
    ("a block never closed", "Plan:\n```json\n" + PLAN_TEXT, "block_not_closed", None),
    ("a plan labelled javascript", reply(TWO_READS, label="javascript"), "wrong_language", None),
    ("a plan without a label", reply(TWO_READS, label=""), "wrong_language", None),
    ("a plan labelled json5", reply(TWO_READS, label="json5"), "wrong_language", None),
    ("a json block inside a markdown block", NESTED, "wrong_language", None),
    ("a plan inside a quote", "See:\n\n" + QUOTED, "plan_outside_block", None),
    ("a plan indented as code", "See:\n\n" + INDENTED, "plan_outside_block", None),
    ("a plan without any fence", "Plan: " + json.dumps(TWO_READS), "plan_outside_block", None),
    ("a reply over its limit", "x" * (MAX_REPLY_CHARS + 1), "reply_too_large", None),
    ("a plan over its limit",
     reply(plan(step("a", "echo_env", name="x" * MAX_PLAN_BYTES))), "plan_too_large", None),
    ("a plan nested too deep", fenced(DEEP), "plan_too_deep", None),
    ("a plan nested 8 000 levels", fenced("[" * 8_000 + "]" * 8_000), "plan_too_deep", None),
    ("a duplicate key at the top",
     fenced('{"format":"ai-harness/plan/1","format":"ai-harness/plan/1",'
            '"nonce":"0123456789abcdef","steps":[]}'), "duplicate_key", None),
    ("the nonce twice in the reply", "Nonce " + NONCE + "\n\n" + reply(TWO_READS),
     "nonce_elsewhere", None),
    ("a duplicate key inside args",
     fenced('{"format":"ai-harness/plan/1","nonce":"0123456789abcdef","steps":[{"id":"a",'
            '"server":"synthetic","tool":"get_project_metadata",'
            '"args":{"project":"demo-alpha","project":"demo-beta"}}]}'), "duplicate_key", None),
    ("NaN", fenced(json.dumps(plan(step("a", "count_items"))).replace('"args": {}',
                                                                      '"args": {"limit": NaN}')),
     "not_finite", None),
    ("Infinity", fenced(json.dumps(plan(step("a", "count_items"))).replace(
        '"args": {}', '"args": {"limit": -Infinity}')), "not_finite", None),
    ("trailing data", fenced(PLAN_TEXT + "\n{}"), "not_json", None),
    ("a byte order mark", fenced("\ufeff" + PLAN_TEXT), "not_json", None),
    ("a non-string key", fenced('{"format":"ai-harness/plan/1",1:2}'), "not_json", None),
    ("a truncated object", fenced(PLAN_TEXT[:-5]), "not_json", None),
    ("a list, not an object", fenced(json.dumps([TWO_READS])), "not_an_object", None),
    ("a zero-width space in a tool name",
     reply(plan(step("a", "get_project\u200bmetadata", project="demo-alpha"))),
     "invisible_character", None),
    ("a bidi control in an argument key",
     reply(plan({"id": "a", "server": "synthetic", "tool": "get_project_metadata",
                 "args": {"pro\u202eject": "demo-alpha"}})), "invisible_character", None),
    ("a bidi control in an argument value",
     reply(plan(step("a", "echo_env", name="abc\u2066def"))), "invisible_character", None),
    ("a lone surrogate", fenced(json.dumps(plan(step("a", "echo_env", name="X"))).replace(
        '"X"', '"\\ud800"')), "invisible_character", None),
    ("a decomposed character", reply(plan(step("a", "echo_env", name="cafe\u0301"))),
     "not_nfc", None),
    ("a credential in an argument", reply(plan(step("a", "echo_env", name=TOKEN))),
     "credential_in_plan", None),
    ("no nonce", reply({"format": PLAN_FORMAT, "steps": TWO_READS["steps"]}),
     "nonce_missing", None),
    ("a foreign nonce", reply(plan(nonce=FOREIGN_NONCE)), "nonce_mismatch", None),
    ("a nonce that is a number", reply(plan(nonce=123)), "nonce_mismatch", None),
    ("the foreign nonce wins over a bad schema",
     reply(plan(nonce=FOREIGN_NONCE, extra_field=1)), "nonce_mismatch", None),
    ("another format", reply({**TWO_READS, "format": "ai-harness/plan/2"}),
     "unsupported_format", None),
    ("an unknown field at the top", reply(plan(**{"return": {"a": 1}})), "unknown_field", None),
    ("an unknown field in a step",
     reply(plan({**step("a", project="demo-alpha"), "for_each": "x"})), "unknown_field", None),
    ("a step without its tool",
     reply(plan({"id": "a", "server": "synthetic", "args": {}})), "missing_field", None),
    ("no steps field", reply({"format": PLAN_FORMAT, "nonce": NONCE}), "missing_field", None),
    ("args that are a list",
     reply(plan({"id": "a", "server": "synthetic", "tool": "env_names", "args": []})),
     "invalid_field", None),
    ("a step id with capitals", reply(plan(step("A", project="demo-alpha"))),
     "invalid_field", None),
    ("empty steps", reply({**TWO_READS, "steps": []}), "no_steps", None),
    ("too many steps",
     reply(plan(*[step(f"s{i}", project="demo-alpha") for i in range(MAX_STEPS + 1)])),
     "too_many_steps", None),
    ("a repeated step id",
     reply(plan(step("a", project="demo-alpha"), step("a", project="demo-beta"))),
     "duplicate_step_id", "a"),
    ("a reference to a later step",
     reply(plan(step("a", project={"$ref": "b"}), step("b", project="demo-beta"))),
     "reference_not_supported", "a"),
    ("a reference to a step that does not exist",
     reply(plan(step("a", project="demo-alpha"), step("b", project={"$ref": "zz.status"}))),
     "reference_not_supported", "b"),
    ("a server not listed",
     reply(plan(step("a", project="demo-alpha"), step("b", server="other", project="x"))),
     "server_not_allowed", "b"),
    ("a tool not listed",
     reply(plan(step("a", project="demo-alpha"), step("b", "drop_project", project="demo-x"))),
     "tool_not_allowed", "b"),
    ("a write tool",
     reply(plan(step("a", project="demo-alpha"),
                step("b", "set_project_metadata", project="demo-alpha", status="activo"))),
     "write_not_allowed", "b"),
    ("an argument not declared",
     reply(plan(step("a", project="demo-alpha", path="/etc"))), "argument_not_allowed", "a"),
    ("a required argument missing", reply(plan(step("a"))), "argument_missing", "a"),
    ("an argument against its pattern", reply(plan(step("a", project="Demo Alpha"))),
     "argument_invalid", "a"),
    ("a float for an integer", reply(plan(step("a", "count_items", limit=1.0))),
     "argument_invalid", "a"),
    ("a boolean for an integer", reply(plan(step("a", "count_items", limit=True))),
     "argument_invalid", "a"),
    ("an integer out of range", reply(plan(step("a", "count_items", limit=11))),
     "argument_invalid", "a"),
]


@pytest.mark.parametrize("case, text, reason, step_id", CASES, ids=[c[0] for c in CASES])
def test_each_refusal_names_its_reason(case, text, reason, step_id):
    result = read(text)
    assert isinstance(result, Refusal), result
    assert (result.reason, result.step) == (reason, step_id)
    assert result.reason in REFUSAL_REASONS


def test_every_reason_has_a_case():
    covered = {case[2] for case in CASES} | {"reply_not_completed", "reply_truncated"}
    assert covered == set(REFUSAL_REASONS)


def test_the_first_failing_step_is_named_and_later_steps_are_not_read():
    text = reply(plan(step("a", project="demo-alpha"), step("b", "drop_project"),
                      step("c", "set_project_metadata", project="demo-alpha", status="activo")))
    assert (read(text).reason, read(text).step) == ("tool_not_allowed", "b")


def test_a_refusal_never_repeats_an_argument_value():
    secret_like = "zz-value-that-must-not-show"
    for text in (reply(plan(step("a", project=secret_like.upper()))),
                 reply(plan(step("a", "drop_project", project=secret_like)))):
        result = read(text)
        assert isinstance(result, Refusal)
        assert secret_like not in result.detail.lower()


def test_the_detail_of_a_refusal_is_cleaned():
    result = read(reply(plan(step("a", "drop\x1b[31m_project", project="demo-alpha"))))
    assert isinstance(result, Refusal)
    assert "\x1b" not in result.detail


# -- the reply, not only its text ----------------------------------------------------------------


def response(status: RequestStatus, *, truncated: bool = False) -> LLMResponse:
    return LLMResponse(request_id=uuid.uuid4(), session_id=uuid.uuid4(), status=status,
                       text=reply(TWO_READS), duration_ms=1, truncated=truncated)


@pytest.mark.parametrize("status", [s for s in RequestStatus if s != RequestStatus.COMPLETED])
def test_a_reply_that_did_not_complete_is_never_read(status, monkeypatch):
    monkeypatch.setattr("harness.mcp.plan.read_plan", lambda *a, **k: pytest.fail("read"))
    result = read_plan_reply(response(status), nonce=NONCE, config=CONFIG)
    assert isinstance(result, Refusal) and result.reason == "reply_not_completed"


def test_a_truncated_reply_is_never_read(monkeypatch):
    monkeypatch.setattr("harness.mcp.plan.read_plan", lambda *a, **k: pytest.fail("read"))
    result = read_plan_reply(response(RequestStatus.COMPLETED, truncated=True),
                             nonce=NONCE, config=CONFIG)
    assert isinstance(result, Refusal) and result.reason == "reply_truncated"


def test_a_completed_reply_is_read():
    result = read_plan_reply(response(RequestStatus.COMPLETED), nonce=NONCE, config=CONFIG)
    assert isinstance(result, Plan)


@pytest.mark.parametrize("bad", ["", "0123", "0123456789ABCDEF", "0123456789abcdeg"])
def test_the_expected_nonce_must_be_well_formed(bad):
    with pytest.raises(ValueError):
        read_plan(reply(TWO_READS), nonce=bad, config=CONFIG)


# -- the hash changes if and only if the canonical plan changes ----------------------------------


def _shuffled(value, rng: random.Random):
    if isinstance(value, dict):
        keys = list(value)
        rng.shuffle(keys)
        return {k: _shuffled(value[k], rng) for k in keys}
    if isinstance(value, list):
        return [_shuffled(v, rng) for v in value]
    return value


def _spaced(value, rng: random.Random) -> str:
    """JSON text of `value` with random whitespace between tokens."""
    space = lambda: rng.choice(["", " ", "\n", "\t", "  \n  "])  # noqa: E731
    if isinstance(value, dict):
        parts = [f"{space()}{json.dumps(k)}{space()}:{space()}{_spaced(v, rng)}{space()}"
                 for k, v in value.items()]
        return "{" + ",".join(parts) + "}"
    if isinstance(value, list):
        return "[" + ",".join(f"{space()}{_spaced(v, rng)}{space()}" for v in value) + "]"
    return json.dumps(value, ensure_ascii=rng.random() < 0.5)


BASE = plan(step("a", project="demo-alpha"), step("b", "echo_env", name="año-ü"),
            step("c", "count_items", limit=3, verbose=False))
MUTATIONS = [
    lambda p: p["steps"][0]["args"].update(project="demo-alphb"),
    lambda p: p["steps"][1]["args"].update(name="año-u"),
    lambda p: p["steps"][2]["args"].update(limit=4),
    lambda p: p["steps"][2]["args"].update(verbose=True),
    lambda p: p["steps"][2]["args"].pop("verbose"),
    lambda p: p["steps"][0].update(id="z"),
    lambda p: p["steps"].reverse(),
    lambda p: p["steps"].pop(),
    lambda p: p.update(nonce=FOREIGN_NONCE),
]


def test_key_order_and_whitespace_never_change_the_hash():
    rng = random.Random(20261127)
    reference = read(fenced(json.dumps(BASE)))
    assert isinstance(reference, Plan)
    for _ in range(200):
        variant = read(fenced(_spaced(_shuffled(BASE, rng), rng)))
        assert isinstance(variant, Plan)
        assert (variant.canonical, variant.sha256) == (reference.canonical, reference.sha256)


@pytest.mark.parametrize("mutate", MUTATIONS)
def test_any_change_of_the_canonical_plan_changes_the_hash(mutate):
    reference = read(fenced(json.dumps(BASE)))
    changed = json.loads(json.dumps(BASE))
    mutate(changed)
    result = read_plan(fenced(json.dumps(changed)), nonce=changed["nonce"], config=CONFIG)
    assert isinstance(result, Plan)
    assert result.canonical != reference.canonical
    assert result.sha256 != reference.sha256


# -- pure: no I/O, no process, no network, no clock ----------------------------------------------


def test_reading_a_plan_touches_nothing_outside_the_process(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("the plan reader did I/O")

    monkeypatch.setattr("harness.mcp.client.run_session", forbidden)  # imported before `open`
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    assert isinstance(read(reply(TWO_READS)), Plan)
    assert isinstance(read(reply(plan(step("a", "set_project_metadata")))), Refusal)


def test_the_module_imports_nothing_that_does_io_or_reads_the_clock():
    source = (Path(__file__).resolve().parents[2] / "harness" / "mcp" / "plan.py").read_text(
        encoding="utf-8")
    imported = set(re.findall(r"^(?:from|import) ([\w.]+)", source, flags=re.MULTILINE))
    forbidden = {"os", "sys", "subprocess", "socket", "time", "datetime", "pathlib", "random",
                 "secrets", "asyncio", "sqlite3", "harness.mcp.client", "harness.mcp.audit",
                 "harness.mcp.worker", "harness.mcp.transport", "harness.storage"}
    assert imported & forbidden == set()
    assert not re.search(r"\b(eval|exec|compile|open|expanduser|expandvars)\(", source)
