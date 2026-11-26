"""The parts of the MCP client that need no server: environment, deadline, classification."""

from __future__ import annotations

import time

import anyio
import pytest

from harness.mcp import client as client_module
from harness.mcp import commands
from harness.mcp.client import (
    BASE_ENV_NAMES,
    RECURSION_MARKER,
    SessionRequest,
    build_server_env,
    run_session,
)
from harness.mcp.config import ServerEntry
from harness.mcp.worker import classify
from tests.mcp_support import ABSOLUTE_PROGRAM
from tests.mcp_support import hang_guard  # noqa: F401 - fixture

ENTRY = ServerEntry.model_validate({
    "command": [ABSOLUTE_PROGRAM], "env": ["DECLARED"], "startup_timeout_s": 1,
    "call_timeout_s": 1, "tools": {},
})


def test_server_environment_is_copied_from_the_harness_and_filtered():
    environ = {"PATH": "/usr/bin", "SYSTEMROOT": "C:\\Windows", "DECLARED": "d",
               "HARNESS_SECRET": "s", "OTHER": "o", "SHELL": "() { :; }"}
    env = build_server_env(ENTRY, environ)
    assert env == {"PATH": "/usr/bin", "SYSTEMROOT": "C:\\Windows", "DECLARED": "d",
                   RECURSION_MARKER: "1"}
    for name, value in env.items():  # nothing invented: every value comes from the harness
        assert name == RECURSION_MARKER or environ[name] == value


def test_the_base_list_holds_what_a_windows_process_needs_to_start():
    for name in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP",
                 "USERPROFILE", "LOCALAPPDATA", "APPDATA"):
        assert name in BASE_ENV_NAMES


def test_cli_and_client_agree_on_the_marker():
    assert commands.RECURSION_MARKER == RECURSION_MARKER


def test_recursion_is_refused_before_the_configuration_is_read(cli, tmp_path):
    code, out, err = cli("mcp", "list", HARNESS_MCP_CONFIG=str(tmp_path / "absent.json"),
                         **{RECURSION_MARKER: "1"})
    assert code == 1 and "recursion" in err and out == ""


def test_the_bound_covers_the_child_margin_and_the_tree_kill():
    """D4 as revised on 2026-11-24: startup + call + GUARANTEED_EXTRA_S, by construction."""
    assert client_module.GUARANTEED_EXTRA_S >= (
        client_module.CHILD_MARGIN_S + client_module.TREE_END_S
    )
    assert client_module.session_budget_s(ENTRY, True) == 1 + 1 + client_module.GUARANTEED_EXTRA_S


def test_a_session_process_that_never_answers_is_killed_at_the_deadline(
    monkeypatch, tmp_path, hang_guard  # noqa: F811
):
    """The session process reads nothing and says nothing: the harness ends it by itself."""
    script = tmp_path / "silent.py"
    script.write_text("import time\nwhile True:\n    time.sleep(1)\n", encoding="utf-8")
    monkeypatch.setattr(client_module, "WORKER_ARGS", [str(script)])
    monkeypatch.setattr(client_module, "CHILD_MARGIN_S", 0.5)
    started = time.monotonic()
    outcome = run_session(SessionRequest(ENTRY, None), {})
    elapsed = time.monotonic() - started
    assert outcome.error_code == "timeout" and outcome.server_stopped is True
    assert elapsed < ENTRY.startup_timeout_s + 0.5 + client_module.TREE_END_S + 2


def test_a_session_process_that_says_nonsense_is_an_internal_error(
    monkeypatch, tmp_path, hang_guard  # noqa: F811
):
    script = tmp_path / "nonsense.py"
    script.write_text("print('[1, 2, 3]', flush=True)\n", encoding="utf-8")
    monkeypatch.setattr(client_module, "WORKER_ARGS", [str(script)])
    outcome = run_session(SessionRequest(ENTRY, None), {})
    assert outcome.error_code == "internal_error" and outcome.server_stopped is True


@pytest.mark.parametrize(("error", "phase", "code"), [
    (TimeoutError(), "call", "timeout"),
    (ExceptionGroup("g", [ValueError("x"), TimeoutError()]), "call", "timeout"),
    (anyio.EndOfStream(), "list", "server_exited"),
    (FileNotFoundError("/x"), "startup", "spawn_failed"),
    (RuntimeError("Unsupported protocol version from the server: 1999"), "startup",
     "protocol_error"),
    (KeyError("x"), "call", "internal_error"),
])
def test_errors_are_classified_without_their_text(error, phase, code):
    assert classify(error, phase) == code


def test_an_error_reply_is_a_server_error_only_if_the_server_sent_one():
    """Finding 8 of the review: the SDK makes up -32000 for a closed connection."""
    from mcp import MCPError

    from harness.mcp.transport import TransportState

    error = MCPError(code=-32000, message="Connection closed")
    state = TransportState(limit=1)
    assert classify(error, "call", state) == "server_exited"
    state.error_replies = 1
    assert classify(error, "call", state) == "server_error"
