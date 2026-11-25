"""The local allowlist (mcp-gateway D2, tasks 2.1 and 2.5). Nothing here starts a server."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from harness.mcp import config as config_module
from tests.mcp_support import Server, server_entry, write_config


@pytest.fixture
def state(tmp_path: Path) -> Server:
    return Server(tmp_path / "state")


def _config(tmp_path: Path, state: Server, **changes) -> Path:
    entry = server_entry(state.state)
    entry.update(changes)
    return write_config(tmp_path / "mcp.json", {"synthetic": entry})


def test_without_configuration_there_are_no_servers(cli):
    code, out, err = cli("mcp", "list")
    assert code == 0
    assert out.strip() == "No MCP servers configured."


def test_list_names_servers_tools_and_operations_but_no_command(cli, tmp_path, state):
    path = _config(tmp_path, state)
    code, out, _ = cli("mcp", "list", HARNESS_MCP_CONFIG=str(path))
    assert code == 0
    assert "synthetic\texternal\t7 tool(s)" in out
    assert "  get_project_metadata\tread" in out
    assert "  set_project_metadata\twrite" in out
    assert "synthetic_server.py" not in out and str(tmp_path) not in out
    assert not state.started


def test_unknown_server_is_refused_without_starting_anything(cli, tmp_path, state):
    path = _config(tmp_path, state)
    code, _, err = cli("mcp", "tools", "otro", HARNESS_MCP_CONFIG=str(path))
    assert code == 1
    assert "server_not_allowed" in err and "'otro'" in err
    assert not state.started


def _invalid_cases(state: Server) -> list[tuple[str, dict, str]]:
    entry = server_entry(state.state)
    tool = entry["tools"]["get_project_metadata"]
    return [
        ("unknown field", {**entry, "shell": True}, "shell"),
        ("command as one string", {**entry, "command": "python server.py"}, "command"),
        ("relative program", {**entry, "command": ["python", "server.py"]}, "command"),
        ("no command", {k: v for k, v in entry.items() if k != "command"}, "command"),
        ("startup timeout 0", {**entry, "startup_timeout_s": 0}, "startup_timeout_s"),
        ("call timeout 301", {**entry, "call_timeout_s": 301}, "call_timeout_s"),
        ("relative cwd", {**entry, "cwd": "sub"}, "cwd"),
        ("env value instead of name", {**entry, "env": ["TOKEN=x"]}, "env"),
        ("operation missing", {**entry, "tools": {"get_project_metadata": {
            k: v for k, v in tool.items() if k != "operation"}}}, "operation"),
        ("string without max_length", {**entry, "tools": {"get_project_metadata": {
            "operation": "read", "arguments": {"project": {"type": "string"}}}}}, "max_length"),
        ("result limit too big", {**entry, "tools": {"get_project_metadata": {
            **tool, "max_result_bytes": 2 * 1024 * 1024}}}, "max_result_bytes"),
        ("bad pattern", {**entry, "tools": {"get_project_metadata": {
            "operation": "read", "arguments": {"project": {
                "type": "string", "max_length": 8, "pattern": "("}}}}}, "pattern"),
    ]


@pytest.mark.parametrize("index", range(12))
def test_invalid_configuration_names_the_field_and_starts_nothing(cli, tmp_path, state, index):
    label, entry, field = _invalid_cases(state)[index]
    path = write_config(tmp_path / "mcp.json", {"synthetic": entry})
    for command in (("list",), ("tools", "synthetic"),
                    ("call", "synthetic", "get_project_metadata", "--args",
                     '{"project": "demo-alpha"}')):
        code, out, err = cli("mcp", *command, HARNESS_MCP_CONFIG=str(path))
        assert code == 1, label
        assert field in err, (label, err)
        assert out == ""
    assert not state.started


@pytest.mark.parametrize("bad", ["Synthetic", "a/b", "1abc", "x" * 65, ""])
def test_server_names_are_plain(cli, tmp_path, state, bad):
    path = write_config(tmp_path / "mcp.json", {bad: server_entry(state.state)})
    code, _, err = cli("mcp", "list", HARNESS_MCP_CONFIG=str(path))
    assert code == 1 and "servers" in err


def test_other_top_level_problems(cli, tmp_path):
    path = tmp_path / "mcp.json"
    for text, expected in [
        ('{"format": "otro/1", "servers": {}}', "format"),
        ('{"format": "ai-harness/mcp/1", "servers": {}, "servers": {}}', "duplicate"),
        ("no es json", "not valid JSON"),
        ("x" * (config_module.MAX_CONFIG_BYTES + 1), "larger than"),
    ]:
        path.write_text(text, encoding="utf-8")
        code, _, err = cli("mcp", "list", HARNESS_MCP_CONFIG=str(path))
        assert code == 1 and expected in err, (text[:40], err)
    code, _, err = cli("mcp", "list", HARNESS_MCP_CONFIG="mcp.json")
    assert code == 1 and "absolute" in err
    code, _, err = cli("mcp", "list", HARNESS_MCP_CONFIG=str(tmp_path / "absent.json"))
    assert code == 1 and "cannot be read" in err


def test_the_error_never_quotes_the_offending_value(cli, tmp_path, state):
    entry = server_entry(state.state)
    entry["startup_timeout_s"] = "CANARIO-VALOR"
    path = write_config(tmp_path / "mcp.json", {"synthetic": entry})
    code, out, err = cli("mcp", "list", HARNESS_MCP_CONFIG=str(path))
    assert code == 1 and "startup_timeout_s" in err
    assert "CANARIO-VALOR" not in out + err


# -- versionable location ----------------------------------------------------------------------

def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is not available here")
    root = tmp_path / "repo"
    root.mkdir()
    _git("init", "-q", cwd=root)
    return root


def test_a_configuration_git_could_version_is_refused(cli, repo, state):
    path = write_config(repo / "mcp.json", {"synthetic": server_entry(state.state)})
    code, out, err = cli("mcp", "list", HARNESS_MCP_CONFIG=str(path))
    assert code == 1
    assert "not ignored" in err
    assert out == ""


def test_an_ignored_configuration_in_a_repository_is_accepted(cli, repo, state):
    (repo / ".gitignore").write_text("mcp.local.json\n", encoding="utf-8")
    path = write_config(repo / "mcp.local.json", {"synthetic": server_entry(state.state)})
    code, out, _ = cli("mcp", "list", HARNESS_MCP_CONFIG=str(path))
    assert code == 0 and "synthetic" in out


def test_a_tracked_file_is_refused_even_if_a_pattern_matches_it(cli, repo, state):
    path = write_config(repo / "mcp.local.json", {"synthetic": server_entry(state.state)})
    _git("add", "mcp.local.json", cwd=repo)
    (repo / ".gitignore").write_text("mcp.local.json\n", encoding="utf-8")
    code, _, err = cli("mcp", "list", HARNESS_MCP_CONFIG=str(path))
    assert code == 1 and "not ignored" in err


def test_without_git_a_work_tree_is_refused(cli, repo, state, monkeypatch):
    path = write_config(repo / "mcp.json", {"synthetic": server_entry(state.state)})
    monkeypatch.setattr("harness.core.git_guard._git", lambda arguments, cwd: None)
    code, _, err = cli("mcp", "list", HARNESS_MCP_CONFIG=str(path))
    assert code == 1 and "Git is not available" in err


def test_a_file_swapped_after_the_check_is_not_read(cli, tmp_path, state, monkeypatch):
    path = _config(tmp_path, state)
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"format": "ai-harness/mcp/1", "servers": {}}), encoding="utf-8")

    def swap(target: Path) -> None:
        other.replace(target)  # what an attacker would do between the check and the read

    monkeypatch.setattr(config_module, "ensure_not_versionable", swap)
    code, out, err = cli("mcp", "list", HARNESS_MCP_CONFIG=str(path))
    assert code == 1 and "changed while it was read" in err


# -- who can write the allowlist (independent review of 2026-11-24, finding 5) ------------------

POSIX_OWNERS = pytest.mark.skipif(
    not hasattr(os, "getuid"), reason="file owners and mode bits are not checked on this system"
)


@POSIX_OWNERS
@pytest.mark.parametrize("mode", [0o666, 0o620, 0o602])
def test_an_allowlist_others_can_write_is_refused(cli, tmp_path, state, mode):
    path = _config(tmp_path, state)
    path.chmod(mode)
    code, _, err = cli("mcp", "list", HARNESS_MCP_CONFIG=str(path))
    assert code == 1 and "writable by other users" in err, err


@POSIX_OWNERS
def test_an_allowlist_in_a_directory_others_can_write_is_refused(cli, tmp_path, state):
    shared = tmp_path / "compartida"
    shared.mkdir()
    path = write_config(shared / "mcp.json", {"synthetic": server_entry(state.state)})
    path.chmod(0o600)
    shared.chmod(0o777)
    try:
        code, _, err = cli("mcp", "list", HARNESS_MCP_CONFIG=str(path))
    finally:
        shared.chmod(0o700)
    assert code == 1 and "writable by other users" in err, err


@POSIX_OWNERS
def test_a_link_from_a_directory_others_can_write_is_refused(cli, tmp_path, state):
    """The review's reproduction: the file itself is private, the link to it is not."""
    path = _config(tmp_path, state)
    path.chmod(0o600)
    shared = tmp_path / "abierta"
    shared.mkdir()
    link = shared / "mcp.json"
    link.symlink_to(path)
    shared.chmod(0o777)
    try:
        code, _, err = cli("mcp", "list", HARNESS_MCP_CONFIG=str(link))
    finally:
        shared.chmod(0o700)
    assert code == 1 and "writable by other users" in err, err


@POSIX_OWNERS
def test_a_private_allowlist_is_accepted(cli, tmp_path, state):
    path = _config(tmp_path, state)
    path.chmod(0o600)
    tmp_path.chmod(0o700)
    code, _, err = cli("mcp", "list", HARNESS_MCP_CONFIG=str(path))
    assert code == 0, err
