"""The catalogue and the instructions a `/plan` question sends first (code-mode D8, D15;
tasks 4.1 and 4.2). Everything comes from the local allowlist and this module's constants."""

from __future__ import annotations

import pytest

from harness.core.errors import HarnessError
from harness.mcp.plan_prompt import (
    MAX_CATALOGUE_CHARS,
    MAX_CATALOGUE_TOOLS,
    NONCE_SHOWN,
    PlanUnavailable,
    build_catalogue,
    plan_instructions,
    shown_instructions,
)
from tests.plan_support import McpList

PROJECT = "project: string, max 64, pattern [a-z0-9][a-z0-9-]*"
EXPECTED = (
    f"synthetic.archive_project({PROJECT}, required)",
    "synthetic.echo_argv()",
    "synthetic.echo_env(name: string, max 128, required)",
    "synthetic.env_names()",
    f"synthetic.get_project_metadata({PROJECT}, required)",
    f"synthetic.rename_project({PROJECT}, optional)",
)


@pytest.fixture
def mcp(tmp_path) -> McpList:
    return McpList(tmp_path / "mcp")


def test_one_line_per_read_tool_and_no_write_tool(mcp):
    catalogue = build_catalogue(mcp.load())
    assert catalogue.lines == EXPECTED
    assert (catalogue.servers, catalogue.write_tools) == (1, 1)
    assert mcp.starts() == 0  # read from the list: no server is started, nothing it says


def test_the_server_says_nothing_in_the_catalogue(tmp_path):
    """The server's own tools/list (any mode, a forged description) is never read for it."""
    for mode in ("ok", "forge-output", "destructive"):
        assert build_catalogue(McpList(tmp_path / mode, mode).load()).lines == EXPECTED


def test_the_person_s_description_is_one_clean_line(mcp):
    tools = {"get_project_metadata": {"operation": "read", "description": "lee la ficha"}}
    mcp.write(tools=tools)
    assert build_catalogue(mcp.load()).lines == ("synthetic.get_project_metadata(): lee la ficha",)
    for bad in ("dos\nlíneas", "escape \x1b[31m", " borde", "x" * 121, "invisible\u200b"):
        mcp.write(tools={"get_project_metadata": {"operation": "read", "description": bad}})
        with pytest.raises(HarnessError):
            mcp.load()


def test_no_read_tool_is_refused(mcp):
    mcp.write(tools={"set_project_metadata": {"operation": "write"}})
    with pytest.raises(PlanUnavailable, match="at least one read tool"):
        build_catalogue(mcp.load())


def test_too_many_tools_or_characters_are_refused(mcp):
    many = {f"t{n:03d}": {"operation": "read"} for n in range(MAX_CATALOGUE_TOOLS + 1)}
    mcp.write(tools=many)
    with pytest.raises(PlanUnavailable, match="at most 64"):
        build_catalogue(mcp.load())
    fits = {f"t{n:03d}": {"operation": "read"} for n in range(MAX_CATALOGUE_TOOLS)}
    mcp.write(tools=fits)
    assert len(build_catalogue(mcp.load()).lines) == 64  # control: at the bound, it fits
    wide = {f"t{n:03d}": {"operation": "read", "description": "d" * 120} for n in range(64)}
    mcp.write(tools=wide)
    with pytest.raises(PlanUnavailable, match=f"the limit is {MAX_CATALOGUE_CHARS}"):
        build_catalogue(mcp.load())


def test_the_instructions_hold_the_nonce_in_its_two_places_only(mcp):
    catalogue = build_catalogue(mcp.load())
    text = plan_instructions("0123456789abcdef", catalogue)
    assert text.count("0123456789abcdef") == 2  # the rule and the example
    assert text.startswith("Instrucciones del harness para esta pregunta (no son datos):\n")
    assert text.endswith("\n" + catalogue.text)
    assert '"nonce" vale "0123456789abcdef"' in text
    for bad in ("0123456789ABCDEF", "0123", "{nonce}", ""):
        with pytest.raises(ValueError):
            plan_instructions(bad, catalogue)


def test_context_shows_the_same_block_with_the_nonce_named(mcp):
    catalogue = build_catalogue(mcp.load())
    shown = shown_instructions(catalogue)
    assert shown == plan_instructions("0123456789abcdef", catalogue).replace(
        "0123456789abcdef", NONCE_SHOWN)
