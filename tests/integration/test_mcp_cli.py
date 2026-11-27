"""`mcp tools` and `mcp call` against the synthetic server (mcp-gateway groups 2 to 4).

Every test that starts a server is guarded by `hang_guard` (a hang aborts with a traceback in
two minutes) and ends by checking the server's heartbeat: a heartbeat that keeps moving means
a process of the harness survived the command.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
import tracemalloc
from pathlib import Path

import pytest

from harness.mcp.client import BASE_ENV_NAMES, GUARANTEED_EXTRA_S, RECURSION_MARKER
from harness.storage.database import DATABASE_NAME
from tests.conftest import SECRET_SAMPLES
from tests.mcp_support import (
    DEFAULT_TOOLS,
    LOOPBACK_PORT_ZERO,
    REPO_ROOT,
    Server,
    child_env,
    hang_guard,  # noqa: F401 - fixture
    kill_survivors,
    result_lines,
    run_bounded,
    server_entry,
    unexpected_sockets,
    write_config,
)

ALPHA = '{"project": "demo-alpha"}'
# Revised on 2026-11-25: time bounds are the guarantee of D4 (startup + call +
# `GUARANTEED_EXTRA_S`), never a measured value plus a little. That a phase deadline (and not
# the harness's) ended a command is shown by its message, not by how close to it it ended.
DRIVER = REPO_ROOT / "tests" / "fixtures" / "mcp" / "driver.py"


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.config = root / "mcp.local.json"
        self.servers: list[Server] = []

    def server(self, mode: str = "ok", **options) -> Server:
        state = Server(self.root / f"state-{len(self.servers)}")
        self.servers.append(state)
        write_config(self.config, {"synthetic": server_entry(state.state, mode, **options)})
        return state


@pytest.fixture
def ws(tmp_path: Path, hang_guard) -> Workspace:  # noqa: F811
    workspace = Workspace(tmp_path)
    yield workspace
    for server in workspace.servers:
        kill_survivors(server)


@pytest.fixture
def mcp(cli, ws):
    """Run `main.py mcp ...` in this process against the workspace's allowlist. The session
    itself runs in a separate process (D4 as revised on 2026-11-24)."""

    def run(*args: str, **env: str):
        started = time.monotonic()
        code, out, err = cli("mcp", *args, **({"HARNESS_MCP_CONFIG": str(ws.config)} | env))
        return code, out, err, time.monotonic() - started

    return run


def rows(data_dir: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(data_dir / DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM tool_calls ORDER BY created_at").fetchall()
    finally:
        conn.close()


def all_text(data_dir: Path) -> str:
    """Every text value of every column of every table of the database."""
    conn = sqlite3.connect(data_dir / DATABASE_NAME)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        values = []
        for table in tables:
            for row in conn.execute(f'SELECT * FROM "{table}"'):
                values += [str(v) for v in row if v is not None]
        return "\n".join(values)
    finally:
        conn.close()


# -- 3.1 discovering tools ---------------------------------------------------------------------


def test_tools_of_the_synthetic_server(mcp, ws):
    server = ws.server()
    code, out, err, _ = mcp("tools", "synthetic")
    assert code == 0, err
    lines = {line.split("\t")[0]: line.split("\t") for line in out.splitlines()}
    assert lines["get_project_metadata"][1:3] == ["read", "allowed"]
    assert lines["drop_project"][1:3] == ["-", "denied:tool_not_allowed"]
    assert lines["set_project_metadata"][1:3] == ["write", "denied:write_requires_approval"]
    assert lines["archive_project"][1:3] == ["read", "absent"]
    assert lines["rename_project"][1:3] == ["read", "denied:schema_mismatch"]
    assert "tools: synthetic, 7 offered by the server, 7 declared" in err
    assert server.calls() == []
    assert server.stopped()


def test_the_servers_stderr_goes_to_its_log_not_to_the_terminal(mcp, ws, data_dir):
    server = ws.server("chatty-stderr")
    code, out, err, _ = mcp("tools", "synthetic")
    assert code == 0
    assert "CANARIO-STDERR-SINTETICO" not in out + err
    log = data_dir / "logs" / "mcp" / "synthetic.stderr.log"
    assert "CANARIO-STDERR-SINTETICO" in log.read_text(encoding="utf-8")
    assert server.stopped()


def test_a_credential_split_across_two_stderr_writes_is_redacted_in_the_log(mcp, ws, data_dir):
    """SEC-01 on the server's log (revised 2026-11-25): the token arrives in two writes."""
    server = ws.server("stderr-split-secret")
    code, _, err, _ = mcp("tools", "synthetic")
    assert code == 0, err
    log = (data_dir / "logs" / "mcp" / "synthetic.stderr.log").read_text(encoding="utf-8")
    assert "CANARIO-STDERR-SINTETICO" in log  # the line was logged at all
    assert "[REDACTED:github]" in log
    assert "S" * 18 not in log  # neither half of the token
    assert server.stopped()


def test_a_burst_of_utf8_continuation_bytes_on_stderr_does_not_end_the_session(mcp, ws,
                                                                               data_dir):
    """Second review of 2026-11-25, finding 1: this input made the redactor raise and the
    session die with an ExceptionGroup. Now it is one line over the limit: dropped, marked."""
    server = ws.server("stderr-continuation-bytes")
    code, out, err, _ = mcp("tools", "synthetic")
    assert code == 0, err
    assert "get_project_metadata" in out
    log = (data_dir / "logs" / "mcp" / "synthetic.stderr.log").read_bytes()
    assert log == (b"[ai-harness: a line of 70000 bytes was dropped: too long to redact]\n"
                   b"\n[ai-harness: 70000 more bytes of stderr were dropped; lines too long to "
                   b"redact or private key blocks, marked above]\n")
    assert "warning: 70000 of the 70000 bytes the server wrote on stderr are not in its log" in err
    assert server.stopped()


def test_a_declared_tool_the_server_lacks_is_denied_without_sending(mcp, ws, data_dir):
    server = ws.server()
    code, _, err, _ = mcp("call", "synthetic", "archive_project", "--args", ALPHA)
    assert code == 1 and "tool_absent" in err
    assert server.calls() == []
    assert [(r["decision"], r["reason"], r["status"]) for r in rows(data_dir)] == [
        ("denied", "tool_absent", "denied")
    ]
    assert server.stopped()


def test_a_server_schema_without_the_declared_argument_is_a_mismatch(mcp, ws):
    server = ws.server()
    code, _, err, _ = mcp("call", "synthetic", "rename_project", "--args", ALPHA)
    assert code == 1 and "schema_mismatch" in err
    assert server.calls() == [] and server.stopped()


# -- 3.2 calling -------------------------------------------------------------------------------


def test_allowed_call(mcp, ws, data_dir):
    server = ws.server()
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 0, err
    assert json.loads(result_lines(out))["name"] == "Demo Alpha"
    assert re.search(r"^call: synthetic/get_project_metadata completed in \d+ ms, \d+ bytes, "
                     r"0 credential\(s\) redacted$", err, re.M)
    assert server.calls() == ["call get_project_metadata"]
    row = rows(data_dir)[0]
    assert (row["decision"], row["status"], row["server_stopped"]) == ("allowed", "completed", 1)
    assert server.stopped()


def test_a_server_written_with_the_official_sdk(mcp, ws, tmp_path):
    """Interoperability: the bounded transport and handshake against SDK 2.3.0's own server."""
    sdk_server = Path(__file__).parents[1] / "fixtures" / "mcp" / "sdk_server.py"
    config = write_config(tmp_path / "sdk.local.json", {"sdk": {
        "command": [sys.executable, str(sdk_server)], "startup_timeout_s": 30,
        "call_timeout_s": 10, "tools": {"get_project_metadata": {
            "operation": "read", "arguments": {"project": DEFAULT_TOOLS["get_project_metadata"]
                                               ["arguments"]["project"]}}},
    }})
    code, out, err, _ = mcp("call", "sdk", "get_project_metadata", "--args", ALPHA,
                            HARNESS_MCP_CONFIG=str(config))
    assert code == 0, err
    assert json.loads(result_lines(out))["name"] == "Demo Alpha (SDK)"
    code, out, err, _ = mcp("tools", "sdk", HARNESS_MCP_CONFIG=str(config))
    assert code == 0 and "get_project_metadata\tread\tallowed" in out, err


def test_the_tool_reports_an_error(mcp, ws, data_dir):
    server = ws.server()
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata",
                            "--args", '{"project": "demo-error"}')
    assert code == 1 and out == ""
    assert "error: the tool reported an error:\n| fallo sintetico rojo [REDACTED:github]" in err
    assert "\x1b" not in err
    assert (rows(data_dir)[0]["status"], rows(data_dir)[0]["error_code"]) == ("failed", "tool_error")
    assert server.stopped()


def test_metacharacters_in_the_command_reach_the_server_literally(mcp, ws, tmp_path):
    work = tmp_path / "cwd"
    work.mkdir()
    tricky = (";touch CANARY", "&& touch CANARY2", "$(touch CANARY3)", "`touch CANARY4`")
    entry = server_entry(ws.root / "state-meta", extra=tricky)
    entry["cwd"] = str(work)
    write_config(ws.config, {"synthetic": entry})
    ws.servers.append(Server(ws.root / "state-meta"))
    code, out, err, _ = mcp("call", "synthetic", "echo_argv")
    assert code == 0, err
    assert json.loads(result_lines(out))[-4:] == list(tricky)
    assert list(work.iterdir()) == [] and not list(REPO_ROOT.glob("CANARY*"))


def test_command_or_env_passed_in_args_is_just_an_undeclared_argument(mcp, ws):
    server = ws.server()
    for extra in ('"command": ["/bin/sh"]', '"env": {"X": "1"}'):
        code, _, err, _ = mcp("call", "synthetic", "get_project_metadata",
                              "--args", '{"project": "demo-alpha", ' + extra + "}")
        assert code == 1 and "argument_not_allowed" in err
    assert not server.started


# -- 2.4 denied before starting ----------------------------------------------------------------


@pytest.mark.parametrize(("server_name", "tool", "args", "reason", "code"), [
    ("otro", "get_project_metadata", ALPHA, "server_not_allowed", 1),
    ("synthetic", "drop_project", ALPHA, "tool_not_allowed", 1),
    ("synthetic", "get_project_metadata", '{"project": "demo-alpha", "path": "/etc"}',
     "argument_not_allowed", 1),
    ("synthetic", "get_project_metadata", '{"project": 7}', "argument_invalid", 1),
    ("synthetic", "get_project_metadata", "{}", "argument_missing", 1),
    ("synthetic", "set_project_metadata", '{"project": "demo-alpha", "status": "activo"}',
     "write_requires_approval", 1),
    ("synthetic", "get_project_metadata", "{no json", "args_not_json", 2),
    ("synthetic", "get_project_metadata", '["demo-alpha"]', "args_not_object", 2),
])
def test_denied_calls_start_no_process(mcp, ws, data_dir, server_name, tool, args, reason, code):
    server = ws.server()
    got, out, err, _ = mcp("call", server_name, tool, "--args", args)
    assert got == code
    assert f"error: denied: {reason}" in err and out == ""
    assert not server.started  # no start, no heartbeat, no call received
    assert [(r["decision"], r["reason"], r["status"]) for r in rows(data_dir)] == [
        ("denied", reason, "denied")
    ]


def test_arguments_over_16_kib_are_a_usage_error(mcp, ws, data_dir):
    server = ws.server()
    code, _, err, _ = mcp("call", "synthetic", "get_project_metadata",
                          "--args", json.dumps({"project": "a" * 17000}))
    assert code == 2 and "args_too_large" in err and "limit is 16384" in err
    assert not server.started


# -- 2.2 environment ---------------------------------------------------------------------------


def test_an_undeclared_variable_does_not_reach_the_server(mcp, ws):
    server = ws.server()
    code, out, _, _ = mcp("call", "synthetic", "echo_env", "--args",
                          '{"name": "HARNESS_TEST_CANARY"}', HARNESS_TEST_CANARY="1")
    assert code == 0 and result_lines(out).strip() == "HARNESS_TEST_CANARY: absent"
    assert server.stopped()


def test_a_declared_variable_reaches_the_server_with_its_value(mcp, ws):
    server = ws.server(env=("HARNESS_TEST_CANARY",))
    code, out, _, _ = mcp("call", "synthetic", "echo_env", "--args",
                          '{"name": "HARNESS_TEST_CANARY"}', HARNESS_TEST_CANARY="valor-1")
    assert code == 0 and result_lines(out).strip() == "HARNESS_TEST_CANARY: visible=valor-1"
    assert server.stopped()


def test_the_server_starts_with_only_the_base_environment(mcp, ws, monkeypatch):
    """No variable of the harness beyond the documented base list (and the marker) arrives.

    The operating system may add its own variables to a new process (macOS adds
    `__CF_USER_TEXT_ENCODING`); those are not the harness's and are listed separately.
    """
    monkeypatch.setenv("HARNESS_TEST_SECRETO", "no-debe-llegar")
    server = ws.server()
    code, out, err, _ = mcp("call", "synthetic", "env_names")
    assert code == 0, err
    names = set(result_lines(out).split())
    added_by_os = {"__CF_USER_TEXT_ENCODING", "LC_CTYPE", "PWD", "SHLVL", "_"}
    assert names - added_by_os <= set(BASE_ENV_NAMES) | {RECURSION_MARKER}
    assert RECURSION_MARKER in names and "HARNESS_TEST_SECRETO" not in names
    assert server.stopped()


# -- 3.3 deadlines -----------------------------------------------------------------------------


def test_a_server_that_never_answers_the_handshake(mcp, ws, data_dir):
    server = ws.server("hang-init", startup=2)
    code, _, err, elapsed = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 1
    assert "timeout: the server did not answer in time (start and handshake, 2 s)" in err
    assert elapsed < 2 + 5 + GUARANTEED_EXTRA_S
    assert (rows(data_dir)[0]["status"], rows(data_dir)[0]["error_code"]) == ("timeout", "timeout")
    assert server.stopped()


def test_a_tool_that_never_ends(mcp, ws, data_dir):
    server = ws.server("hang-call", call=2)
    code, _, err, elapsed = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 1 and "timeout: the server did not answer in time (call, 2 s)" in err
    assert elapsed < 5 + 2 + GUARANTEED_EXTRA_S
    row = rows(data_dir)[0]
    assert (row["status"], row["error_code"], row["server_stopped"]) == ("timeout", "timeout", 1)
    assert server.stopped()


def test_a_server_that_ignores_the_end_of_its_input_and_sigterm(mcp, ws, data_dir):
    server = ws.server("ignore-close", startup=5, call=5)
    code, out, _, elapsed = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 0 and "Demo Alpha" in out
    assert elapsed < 5 + 5 + GUARANTEED_EXTRA_S
    assert rows(data_dir)[0]["server_stopped"] == 1
    assert server.stopped()


# -- 3.4 no process left behind ----------------------------------------------------------------


@pytest.mark.parametrize("mode", ["die", "die-init"])
def test_a_server_that_dies(mcp, ws, data_dir, mode):
    server = ws.server(mode)
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 1 and out == ""
    assert "server_exited: the server process ended before answering" in err
    assert "Traceback" not in err
    assert (rows(data_dir)[0]["status"], rows(data_dir)[0]["error_code"]) == (
        "failed", "server_exited")
    assert server.stopped()


def test_a_program_that_cannot_start(mcp, ws, data_dir):
    entry = server_entry(ws.root / "state-x")
    entry["command"] = [str(ws.root / "no-existe" / "server")]
    write_config(ws.config, {"synthetic": entry})
    code, _, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 1 and "spawn_failed" in err and "Traceback" not in err
    assert rows(data_dir)[0]["error_code"] == "spawn_failed"


def test_interrupting_a_call(ws, data_dir, tmp_path):
    server = ws.server("hang-call", call=60)
    env = child_env(HARNESS_DATA_DIR=str(data_dir), HARNESS_MCP_CONFIG=str(ws.config))
    code, _, err, elapsed = run_bounded(
        [sys.executable, str(DRIVER), "interrupt", str(server.state), "mcp", "call",
         "synthetic", "get_project_metadata", "--args", ALPHA],
        env, tmp_path / "run", deadline_s=60,
    )
    assert code == 130, err
    assert "interrupted" in err and "Traceback" not in err
    assert elapsed < 30  # the call deadline was 60 s
    row = rows(data_dir)[0]
    assert (row["status"], row["error_code"], row["server_stopped"]) == ("failed", "interrupted", 1)
    assert server.stopped()


# -- 3.5 garbage and schemas -------------------------------------------------------------------


def test_text_that_is_not_json_rpc_ends_the_session(mcp, ws, data_dir):
    server = ws.server("garbage")
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 1 and "protocol_error" in err
    assert "LINEA-BASURA" not in out + err and "respuesta tras la basura" not in out
    assert rows(data_dir)[0]["error_code"] == "protocol_error"
    assert server.stopped()


def test_a_result_that_breaks_its_output_schema_is_not_shown(mcp, ws, data_dir):
    server = ws.server("bad-schema")
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 1 and "invalid_result" in err
    assert "Demo Alpha" not in out + err and out == ""
    assert rows(data_dir)[0]["error_code"] == "invalid_result"
    assert server.stopped()


# -- 3.6 sizes ---------------------------------------------------------------------------------


def test_a_result_over_the_limit_is_refused_and_not_printed(mcp, ws, data_dir):
    server = ws.server("flood")
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 1 and out == ""
    assert re.search(r"result_too_large: the server sent \d{7} bytes in one message; "
                     r"the limit is 65536 bytes", err), err
    assert "yyyy" not in err
    row = rows(data_dir)[0]
    assert (row["status"], row["error_code"]) == ("failed", "result_too_large")
    assert server.stopped()


def test_a_line_without_end_is_never_buffered_whole(mcp, ws, data_dir):
    """Task 2.6: 8 MiB without a newline. Measured with tracemalloc (portable, Python heap)."""
    server = ws.server("long-line", call=10)
    tracemalloc.start()
    try:
        code, out, err, elapsed = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert code == 1 and "result_too_large" in err and "at least" in err
    assert peak < 16 * 1024 * 1024, peak
    assert elapsed < 5 + 10 + GUARANTEED_EXTRA_S
    print(f"\nlong-line: {elapsed:.2f} s, Python heap peak {peak / 1024 / 1024:.1f} MiB")
    assert server.stopped()


# -- 3.7, 3.8 loops ----------------------------------------------------------------------------


def test_a_sampling_request_from_the_server_is_refused(mcp, ws, data_dir):
    server = ws.server("sampling")
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 0, err
    assert "sampling answered with error" in out
    assert "sampling-answer error -32600" in server.calls()  # what SDK 2.3.0 answers, measured
    assert len(rows(data_dir)) == 1
    assert server.stopped()


def test_a_server_that_runs_the_harness_is_refused_as_recursion(mcp, ws):
    server = ws.server("recurse", call=30)
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 0, err
    calls = server.calls()
    assert "recurse-exit 1" in calls
    assert any("recursion" in line for line in calls if line.startswith("recurse-stderr"))
    assert server.starts() == 1
    assert server.stopped()


# -- 4.1 results as untrusted data -------------------------------------------------------------


def test_a_leaky_result_is_cleaned_and_asks_for_nothing(mcp, ws, data_dir):
    server = ws.server("leaky")
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 0, err
    github = "gh" + "p_" + "S" * 36
    aws = "AK" + "IA" + "T" * 16
    for text in (out, err):
        assert github not in text and aws not in text
        for char in ("\x1b", "\x07", "‮", "​"):
            assert char not in text
    assert "[REDACTED:github]" in out and "[REDACTED:aws]" in out
    assert "2 credential(s) redacted" in err
    assert server.calls() == ["call get_project_metadata"]  # nothing else was called
    assert len(rows(data_dir)) == 1


# -- 4.3 audit without content -----------------------------------------------------------------


def test_audit_rows_never_hold_argument_values_or_result_text(mcp, ws, data_dir):
    ws.server()
    mcp("call", "synthetic", "get_project_metadata",
        "--args", '{"project": "demo-alpha", "path": "/etc/CANARIO-ARG"}')
    mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    # A colour code right before the token: dropped whole, so the token keeps its boundary.
    mcp("call", "otro \x1b[2J" + SECRET_SAMPLES["github"], "x")
    stored = all_text(data_dir)
    assert "CANARIO-ARG" not in stored
    assert "demo-alpha" not in stored and "Demo Alpha" not in stored and "activo" not in stored
    assert SECRET_SAMPLES["github"] not in stored and "\x1b" not in stored
    reasons = [(r["decision"], r["reason"], r["status"]) for r in rows(data_dir)]
    assert reasons == [
        ("denied", "argument_not_allowed", "denied"),
        ("allowed", "allowed", "completed"),
        ("denied", "server_not_allowed", "denied"),
    ]
    unknown = rows(data_dir)[2]["server"]
    assert unknown == "otro [REDACTED:github]"
    assert all(len(r["args_hmac"] or "x" * 64) == 64 for r in rows(data_dir))


def test_a_stale_running_row_is_recovered_as_interrupted(mcp, ws, data_dir):
    ws.server()
    mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    conn = sqlite3.connect(data_dir / DATABASE_NAME)
    with conn:
        conn.execute(
            "INSERT INTO tool_calls (call_id, server, tool, operation, decision, reason, "
            "args_bytes, status, created_at) VALUES ('old', 'synthetic', 't', 'read', "
            "'allowed', 'allowed', 2, 'running', '2026-01-01T00:00:00+00:00')")
        conn.execute(
            "INSERT INTO tool_calls (call_id, server, tool, operation, decision, reason, "
            "args_bytes, status, created_at) VALUES ('fresh', 'synthetic', 't', 'read', "
            "'allowed', 'allowed', 2, 'running', strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'))")
    conn.close()
    # "Stale" is "nobody holds its lock" (revised 2026-11-24), not an age: the fresh row's
    # lock is held here, as a live command would hold it.
    from harness.mcp.audit import call_lock

    live = call_lock(data_dir, "fresh")
    assert live.acquire()
    try:
        mcp("call", "synthetic", "drop_project")
    finally:
        live.release()
    by_id = {r["call_id"]: r for r in rows(data_dir)}
    assert (by_id["old"]["status"], by_id["old"]["error_code"]) == ("failed", "interrupted")
    assert by_id["fresh"]["status"] == "running"  # its owner is alive


def test_the_table_refuses_content_shaped_values(data_dir, conn):
    insert = ("INSERT INTO tool_calls (call_id, server, tool, decision, reason, args_bytes, "
              "status, created_at, args_hmac) VALUES (?, 's', 't', ?, ?, 0, ?, 'now', ?)")
    for values in [
        ("a", "maybe", "allowed", "running", None),
        ("b", "denied", "a value /etc/passwd", "denied", None),
        ("c", "allowed", "allowed", "running", "abc"),
        ("d", "allowed", "allowed", "denied", None),
        ("e", "denied", "allowed", "denied", None),
    ]:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, values)


# -- 4.4 no listening surface ------------------------------------------------------------------


@pytest.mark.parametrize("socketpair", ["native", "fallback"])
def test_no_socket_is_bound_during_a_call(ws, data_dir, tmp_path, socketpair):
    """Audit hook installed before the SDK is imported. Only the event loop's own socket pair
    may bind, recognised by its call stack (revised on 2026-11-25, hotfix 0.2.1: on Windows
    that pair is `socket._fallback_socketpair`, which binds `('127.0.0.1', 0)`; `fallback`
    forces it here, so Windows's condition runs on every system)."""
    server = ws.server()
    env = child_env(HARNESS_DATA_DIR=str(data_dir), HARNESS_MCP_CONFIG=str(ws.config),
                    AI_HARNESS_TEST_FALLBACK_SOCKETPAIR="1" if socketpair == "fallback" else "0")
    code, out, err, _ = run_bounded(
        [sys.executable, str(DRIVER), "sockets", str(server.state), "mcp", "call",
         "synthetic", "get_project_metadata", "--args", ALPHA],
        env, tmp_path / "run", deadline_s=60,
    )
    assert code == 0, err
    binds = [{"event": "socket.bind", **bind}
             for bind in json.loads((server.state / "binds.json").read_text(encoding="utf-8"))]
    report = {"argv": ["driver.py", "sockets"], "environment": json.loads(
        (server.state / "binds-environment.json").read_text(encoding="utf-8"))}
    foreign = [bind for bind in binds if not bind["self_pipe"]]
    assert foreign == [], unexpected_sockets(report, foreign)
    outside = [bind for bind in binds if bind["address"] not in LOOPBACK_PORT_ZERO]
    assert outside == [], unexpected_sockets(report, outside)
    if socketpair == "fallback":
        assert binds, report  # the emulation really ran, and was recognised
    print(f"\nsocket binds: {len(binds)} (the event loop's own pair only)")
    assert server.stopped()
