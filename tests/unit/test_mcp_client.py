"""The parts of the MCP client that need no server: environment, watchdog, last barrier."""

from __future__ import annotations

import time

import anyio
import pytest

from harness.mcp import client as client_module
from harness.mcp import commands
from harness.mcp.client import (
    BASE_ENV_NAMES,
    RECURSION_MARKER,
    Outcome,
    SessionRequest,
    build_server_env,
    run_session,
)
from harness.mcp.config import ServerEntry
from tests.mcp_support import hang_guard  # noqa: F401 - fixture

ENTRY = ServerEntry.model_validate({
    "command": ["/opt/synthetic/server"], "env": ["DECLARED"], "startup_timeout_s": 1,
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


def test_watchdog_abandons_a_worker_that_ignores_cancellation(monkeypatch, hang_guard):  # noqa: F811
    """The conversation itself blocks its own event loop and never sees the cancel."""

    async def stuck(request, env, control):
        time.sleep(6)  # blocks the loop: a cancel scope cannot interrupt this
        return Outcome()

    monkeypatch.setattr(client_module, "_converse", stuck)
    monkeypatch.setattr(client_module, "CANCEL_MARGIN_S", 0.5)
    monkeypatch.setattr(client_module, "ABANDON_MARGIN_S", 1.5)
    started = time.monotonic()
    outcome = run_session(SessionRequest(ENTRY, None), {})
    elapsed = time.monotonic() - started
    assert outcome.abandoned and outcome.error_code == "abandoned"
    assert elapsed < ENTRY.startup_timeout_s + 1.5 + 1.0


def test_watchdog_cancels_a_cooperative_worker_at_the_deadline(monkeypatch, hang_guard):  # noqa: F811
    async def slow(request, env, control):
        with anyio.CancelScope() as scope:
            control.attach(__import__("asyncio").get_running_loop(), scope)
            await anyio.sleep(30)
        return Outcome(error_code=control.reason)

    monkeypatch.setattr(client_module, "_converse", slow)
    monkeypatch.setattr(client_module, "CANCEL_MARGIN_S", 0.5)
    started = time.monotonic()
    outcome = run_session(SessionRequest(ENTRY, None), {})
    assert not outcome.abandoned and outcome.error_code == "timeout"
    assert time.monotonic() - started < ENTRY.startup_timeout_s + 0.5 + 1.0


def test_an_abandoned_call_is_audited_and_ends_the_process(cli, tmp_path, monkeypatch):
    from tests.mcp_support import server_entry, write_config

    config = write_config(tmp_path / "mcp.json", {"synthetic": server_entry(tmp_path / "s")})
    exits: list[int] = []
    monkeypatch.setattr(commands, "hard_exit", exits.append)
    monkeypatch.setattr(client_module, "run_session",
                        lambda request, environ: Outcome(error_code="abandoned", abandoned=True))
    code, out, err = cli("mcp", "call", "synthetic", "get_project_metadata",
                         "--args", '{"project": "demo-alpha"}', HARNESS_MCP_CONFIG=str(config))
    assert exits == [1]
    assert "did not shut down in time" in err and out == ""
    from tests.conftest import query

    assert query(tmp_path / "data", "SELECT status, error_code FROM tool_calls") == [
        ("abandoned", "abandoned")
    ]


@pytest.mark.parametrize(("error", "phase", "code"), [
    (TimeoutError(), "call", "timeout"),
    (ExceptionGroup("g", [ValueError("x"), TimeoutError()]), "call", "timeout"),
    (anyio.EndOfStream(), "list", "server_exited"),
    (FileNotFoundError("/x"), "startup", "spawn_failed"),
    (RuntimeError("Invalid structured content returned by tool x"), "call", "invalid_result"),
    (RuntimeError("Unsupported protocol version from the server: 1999"), "startup",
     "protocol_error"),
    (KeyError("x"), "call", "internal_error"),
])
def test_errors_are_classified_without_their_text(error, phase, code):
    assert client_module._classify(error, phase) == code
