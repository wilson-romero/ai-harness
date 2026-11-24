"""The deny-by-default policy as a pure function (mcp-gateway D5, task 2.3). No processes."""

from __future__ import annotations

import json

import pytest

from harness.mcp.config import LoadedConfig, McpConfig
from harness.mcp.policy import (
    DENIAL_REASONS,
    MAX_ARGS_BYTES,
    decide_before_start,
    decide_offered,
    parse_arguments,
)
from tests.mcp_support import DEFAULT_TOOLS

CONFIG = LoadedConfig(McpConfig.model_validate({
    "format": "ai-harness/mcp/1",
    "servers": {"synthetic": {
        "command": ["/opt/synthetic/bin/server"],
        "tools": {
            **DEFAULT_TOOLS,
            "count_items": {"operation": "read", "arguments": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                "verbose": {"type": "boolean"},
            }},
        },
    }},
}))
TOOLS = CONFIG.servers["synthetic"].tools


def decide(tool: str, args: object, server: str = "synthetic"):
    text = args if isinstance(args, str) else json.dumps(args)
    return decide_before_start(CONFIG, server, tool, parse_arguments(text))


ALPHA = {"project": "demo-alpha"}

CASES = [
    # (description, server, tool, args, expected reason) - one or more per reason, in order
    ("unknown server", "otro", "get_project_metadata", ALPHA, "server_not_allowed"),
    ("unknown server wins over bad args", "otro", "x", "[", "server_not_allowed"),
    ("args over 16 KiB", "synthetic", "get_project_metadata",
     {"project": "a" * MAX_ARGS_BYTES}, "args_too_large"),
    ("args not JSON", "synthetic", "get_project_metadata", "{project:", "args_not_json"),
    ("duplicate key", "synthetic", "get_project_metadata",
     '{"project": "demo-alpha", "project": "x"}', "args_not_json"),
    ("NaN", "synthetic", "count_items", '{"limit": NaN}', "args_not_json"),
    ("args a list", "synthetic", "get_project_metadata", ["demo-alpha"], "args_not_object"),
    ("tool not declared", "synthetic", "drop_project", ALPHA, "tool_not_allowed"),
    ("undeclared argument", "synthetic", "get_project_metadata",
     {"project": "demo-alpha", "path": "/etc"}, "argument_not_allowed"),
    ("command smuggled as argument", "synthetic", "get_project_metadata",
     {"project": "demo-alpha", "command": ["sh"]}, "argument_not_allowed"),
    ("missing required", "synthetic", "get_project_metadata", {}, "argument_missing"),
    ("number for string", "synthetic", "get_project_metadata", {"project": 7}, "argument_invalid"),
    ("too long", "synthetic", "get_project_metadata", {"project": "a" * 300}, "argument_invalid"),
    ("outside pattern", "synthetic", "get_project_metadata", {"project": "Demo Alpha!"},
     "argument_invalid"),
    ("pattern is a full match", "synthetic", "get_project_metadata", {"project": "demo\n"},
     "argument_invalid"),
    ("integer below range", "synthetic", "count_items", {"limit": 0}, "argument_invalid"),
    ("integer above range", "synthetic", "count_items", {"limit": 11}, "argument_invalid"),
    ("boolean for integer", "synthetic", "count_items", {"limit": True}, "argument_invalid"),
    ("float for integer", "synthetic", "count_items", {"limit": 2.0}, "argument_invalid"),
    ("string for boolean", "synthetic", "count_items", {"verbose": "true"}, "argument_invalid"),
    ("value outside enum", "synthetic", "set_project_metadata",
     {"project": "demo-alpha", "status": "borrado"}, "argument_invalid"),
    ("declared write", "synthetic", "set_project_metadata",
     {"project": "demo-alpha", "status": "activo"}, "write_requires_approval"),
]


@pytest.mark.parametrize(("label", "server", "tool", "args", "reason"), CASES,
                         ids=[case[0] for case in CASES])
def test_each_reason_in_its_order(label, server, tool, args, reason):
    decision = decide(tool, args, server)
    assert not decision.allowed
    assert decision.reason == reason


def test_every_pre_start_reason_is_covered():
    covered = {case[4] for case in CASES}
    assert covered == set(DENIAL_REASONS) - {"recursion", "tool_absent", "schema_mismatch"}


@pytest.mark.parametrize(("tool", "args"), [
    ("get_project_metadata", ALPHA),
    ("count_items", {}),
    ("count_items", {"limit": 10, "verbose": False}),
    ("echo_env", {"name": "HARNESS_TEST_CANARY"}),
])
def test_declared_read_calls_are_allowed(tool, args):
    decision = decide(tool, args)
    assert decision.allowed and decision.reason == "allowed" and decision.operation == "read"


def test_undeclared_argument_is_named_in_the_detail():
    decision = decide("get_project_metadata", {"project": "demo-alpha", "path": "/etc"})
    assert "'path'" in decision.detail
    assert "/etc" not in decision.detail  # the name, never the value


def test_a_name_from_the_command_line_is_cleaned_before_it_is_shown():
    decision = decide("drop\x1b[2J‮project", ALPHA)
    assert "\x1b" not in decision.detail and "‮" not in decision.detail


def test_arguments_are_measured_before_they_are_parsed(monkeypatch):
    calls = []
    monkeypatch.setattr("harness.mcp.policy.loads_strict", lambda *a, **k: calls.append(1))
    parsed = parse_arguments("[" * (MAX_ARGS_BYTES + 1))
    assert parsed.problem == "args_too_large" and calls == []


def test_deep_nesting_is_refused_not_crashing():
    assert parse_arguments("[" * 5000 + "]" * 5000).problem == "args_not_json"


def test_lone_surrogate_from_the_command_line_is_not_json_text():
    assert parse_arguments('{"project": "\udcff"}').problem == "args_not_json"


def test_canonical_arguments_ignore_key_order():
    one = parse_arguments('{"b": 1, "a": "x"}').canonical
    other = parse_arguments('{ "a":"x","b":1 }').canonical
    assert one == other == b'{"a":"x","b":1}'


# -- after list_tools --------------------------------------------------------------------------

DECLARED = TOOLS["get_project_metadata"]
SCHEMA = {"type": "object", "properties": {"project": {"type": "string"}}, "required": ["project"]}


def test_tool_not_offered_is_absent():
    assert decide_offered(DECLARED, None, "get_project_metadata").reason == "tool_absent"


@pytest.mark.parametrize("schema", [
    {"type": "object", "properties": {"slug": {"type": "string"}}},  # lacks a declared argument
    {"type": "object", "properties": {"project": {}, "x": {}}, "required": ["project", "x"]},
    {"type": "object", "properties": ["project"]},  # malformed
    {"type": "object", "properties": {"project": {}}, "required": "project"},  # malformed
    "not an object",
])
def test_incompatible_server_schema_is_a_mismatch(schema):
    assert decide_offered(DECLARED, schema, "get_project_metadata").reason == "schema_mismatch"


def test_compatible_schema_is_allowed():
    assert decide_offered(DECLARED, SCHEMA, "get_project_metadata").allowed


def test_what_the_server_says_never_allows_a_write():
    """`readOnlyHint` and a perfect schema change nothing: the allowlist says `write`."""
    write = TOOLS["set_project_metadata"]
    schema = {"type": "object", "properties": {"project": {}, "status": {}},
              "annotations": {"readOnlyHint": True}}
    assert decide_offered(write, schema, "set_project_metadata").operation == "write"
    decision = decide("set_project_metadata", {"project": "demo-alpha"})
    assert decision.reason == "write_requires_approval"
