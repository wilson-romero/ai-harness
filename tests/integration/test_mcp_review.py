"""Findings of the independent review of 2026-11-24 (mcp-gateway, tasks group 6).

Each test was written before its fix and seen failing for the reason the review gave. The
servers are the standard-library synthetic server in adversarial modes; a test that could hang
the pytest process itself runs the CLI in a child process with a deadline measured here.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from harness.mcp import client as client_module
from harness.storage.database import open_database
from tests.integration.test_mcp_cli import (  # noqa: F401 - fixtures
    ALPHA,
    DRIVER,
    mcp,
    rows,
    ws,
)
from tests.mcp_support import (
    REPO_ROOT,
    child_env,
    hang_guard,  # noqa: F401 - fixture
    result_lines,
    run_bounded,
    run_main_bounded,
)

STUCK_WORKER = REPO_ROOT / "tests" / "fixtures" / "mcp" / "stuck_worker.py"
AUDIT_SITE = REPO_ROOT / "tests" / "fixtures" / "mcp" / "audit_site"
OWNER_ONLY = hasattr(os, "getuid")  # POSIX permission bits mean something here


def beat_stopped(path: Path, within_s: float = 3.0) -> bool:
    """A heartbeat file that has not changed for 0.5 s (or never existed)."""
    if not path.exists():
        return True
    deadline = time.monotonic() + within_s
    previous = path.read_text(encoding="utf-8")
    while time.monotonic() < deadline:
        time.sleep(0.5)
        current = path.read_text(encoding="utf-8")
        if current == previous:
            return True
        previous = current
    return False


def kill_logged(path: Path) -> None:
    """Test cleanup only: kill the pids a fixture logged, if their heartbeat still moves."""
    if not path.exists():
        return
    for word in path.read_text(encoding="utf-8").split():
        if word.isdigit():
            try:
                os.kill(int(word), 9 if hasattr(os, "getuid") else 15)
            except OSError:
                pass


# -- 1. a server cannot hang the harness -------------------------------------------------------


def test_a_regex_bomb_in_an_output_schema_is_never_run(ws, data_dir, tmp_path):  # noqa: F811
    """The review's exact reproduction: `^(a+)+$` against 34 `a` and `!` in a server-sent
    output schema, call deadline 2 s. Run in a child process: before the fix it never ends."""
    server = ws.server("regex-bomb", startup=5, call=2)
    env = child_env(HARNESS_DATA_DIR=str(data_dir), HARNESS_MCP_CONFIG=str(ws.config))
    code, out, err, elapsed = run_main_bounded(
        env, tmp_path / "run", "mcp", "call", "synthetic", "get_project_metadata",
        "--args", ALPHA, deadline_s=60,
    )
    assert code == 0, (code, err[-500:])
    assert elapsed < 5 + 2 + client_module.GUARANTEED_EXTRA_S
    assert json.loads(result_lines(out))["project"].startswith("aaaa")
    row = rows(data_dir)[0]
    assert (row["status"], row["server_stopped"]) == ("completed", 1)
    assert server.stopped()


def test_a_session_process_stuck_in_c_code_is_killed_at_the_deadline(mcp, ws, data_dir,  # noqa: F811
                                                                     monkeypatch):
    """A CPU-bound hang holding the GIL inside the session process itself."""
    server = ws.server("ok", startup=2, call=2)
    monkeypatch.setattr(client_module, "WORKER_ARGS", [str(STUCK_WORKER), str(server.state)])
    try:
        code, out, err, elapsed = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
        assert code == 1 and "timeout" in err, err
        assert out == ""
        assert elapsed < 2 + 2 + client_module.GUARANTEED_EXTRA_S
        row = rows(data_dir)[0]
        assert (row["status"], row["error_code"]) == ("timeout", "timeout")
        assert beat_stopped(server.state / "heartbeat-grandchild")
    finally:
        kill_logged(server.state / "stuck.log")
    print(f"\nstuck session process killed after {elapsed:.1f} s")


def test_ctrl_c_ends_a_stuck_session_with_130(ws, data_dir, tmp_path):  # noqa: F811
    server = ws.server("ok", startup=30, call=30)
    env = child_env(HARNESS_DATA_DIR=str(data_dir), HARNESS_MCP_CONFIG=str(ws.config))
    try:
        code, _, err, elapsed = run_bounded(
            [sys.executable, str(DRIVER), "interrupt-stuck", str(server.state), "mcp", "call",
             "synthetic", "get_project_metadata", "--args", ALPHA],
            env, tmp_path / "run", deadline_s=60,
        )
        assert code == 130, err[-500:]
        assert "Traceback" not in err
        assert elapsed < 20  # the deadline was 60 s
        row = rows(data_dir)[0]
        assert (row["status"], row["error_code"]) == ("failed", "interrupted")
        assert beat_stopped(server.state / "heartbeat-grandchild")
    finally:
        kill_logged(server.state / "stuck.log")


def test_a_live_call_is_never_recovered_as_stale(ws, data_dir, tmp_path):  # noqa: F811
    """`stale` means "nobody holds the call's lock", not "older than N seconds"."""
    from harness.mcp.audit import recover_stale

    server = ws.server("hang-call", call=30)
    env = child_env(HARNESS_DATA_DIR=str(data_dir), HARNESS_MCP_CONFIG=str(ws.config))
    later = datetime.now(UTC) + timedelta(hours=2)
    work = tmp_path / "run"
    work.mkdir()
    with (work / "out.txt").open("wb") as out:
        process = subprocess.Popen(
            [sys.executable, "main.py", "mcp", "call", "synthetic", "get_project_metadata",
             "--args", ALPHA], cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL, stdout=out,
            stderr=out,
        )
        try:
            deadline = time.monotonic() + 30
            while not server.calls() and time.monotonic() < deadline:
                time.sleep(0.1)
            assert server.calls(), "the call never reached the server"
            conn = open_database(data_dir)
            try:
                assert recover_stale(conn, data_dir, later) == 0
            finally:
                conn.close()
            assert rows(data_dir)[0]["status"] == "running"
        finally:
            process.kill()
            process.wait(timeout=10)
    conn = open_database(data_dir)
    try:
        assert recover_stale(conn, data_dir, later) == 1  # its owner is gone now
    finally:
        conn.close()
    assert (rows(data_dir)[0]["status"], rows(data_dir)[0]["error_code"]) == (
        "failed", "interrupted")
    deadline = time.monotonic() + 20  # the session process ends by its own deadline
    while server.alive() and time.monotonic() < deadline:
        time.sleep(0.5)


# -- 2. the server's stderr is bounded and private ---------------------------------------------


def test_a_server_flooding_stderr_is_capped_and_stopped(mcp, ws, data_dir):  # noqa: F811
    server = ws.server("stderr-flood", call=60)  # only bounds a failing run
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    log = data_dir / "logs" / "mcp" / "synthetic.stderr.log"
    size = log.stat().st_size
    assert size <= 1024 * 1024 + 512, size  # client.STDERR_KEEP_BYTES
    assert code == 1 and "stderr_too_large" in err, err
    row = rows(data_dir)[0]
    assert (row["status"], row["error_code"]) == ("failed", "stderr_too_large")
    assert server.stopped()


@pytest.mark.skipif(not OWNER_ONLY, reason="POSIX permission bits are not used on this system")
def test_the_stderr_log_is_private(mcp, ws, data_dir):  # noqa: F811
    ws.server("chatty-stderr")
    code, _, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 0, err
    log = data_dir / "logs" / "mcp" / "synthetic.stderr.log"
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert stat.S_IMODE(log.parent.stat().st_mode) == 0o700


# -- 4. the whole process tree ends ------------------------------------------------------------


def test_a_grandchild_of_the_server_is_killed_too(mcp, ws, data_dir):  # noqa: F811
    server = ws.server("grandchild")
    try:
        code, _, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
        assert code == 0, err
        assert beat_stopped(server.state / "heartbeat-grandchild")
        assert rows(data_dir)[0]["server_stopped"] == 1
        assert server.stopped()
    finally:
        kill_logged(server.state / "starts.log")


@pytest.mark.skipif(not hasattr(os, "setsid"), reason="no sessions to escape into here")
def test_a_grandchild_in_its_own_session_escapes_as_documented(mcp, ws, data_dir):  # noqa: F811
    """The limit that README and SECURITY state: a process that leaves the group escapes."""
    server = ws.server("grandchild-escapes")
    try:
        code, _, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
        assert code == 0, err
        assert not beat_stopped(server.state / "heartbeat-escaped", within_s=1.5)
    finally:
        kill_logged(server.state / "starts.log")
    assert beat_stopped(server.state / "heartbeat-escaped")


# -- 6. annotations can only restrict ----------------------------------------------------------


def test_a_read_tool_the_server_calls_destructive_is_denied(mcp, ws, data_dir):  # noqa: F811
    server = ws.server("destructive")
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 1 and "annotation_conflict" in err, err
    assert out == "" and server.calls() == []
    row = rows(data_dir)[0]
    assert (row["decision"], row["reason"]) == ("denied", "annotation_conflict")
    code, out, _, _ = mcp("tools", "synthetic")
    assert "get_project_metadata\tread\tdenied:annotation_conflict" in out


# -- 7. a result cannot pass for the harness's own lines ---------------------------------------


def test_a_result_cannot_forge_harness_lines(mcp, ws):  # noqa: F811
    ws.server("forge-output")
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 0, err
    assert all(line.startswith("|") for line in out.splitlines()), out
    assert sum(line.startswith("call: ") for line in err.splitlines()) == 1
    assert "call: synthetic/get_project_metadata completed in 1 ms" in result_lines(out)


# -- 8. an error the server sent is not a closed connection ------------------------------------


def test_a_server_error_reply_is_not_reported_as_an_exit(mcp, ws, data_dir):  # noqa: F811
    ws.server("server-error")
    code, _, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 1
    assert "server_error" in err and "server_exited" not in err, err
    assert rows(data_dir)[0]["error_code"] == "server_error"


# -- 9. the "no listening socket" oracle covers creation and the session process --------------


def _sockets_run(ws, data_dir, tmp_path, args):  # noqa: F811
    logs = tmp_path / "sockets"
    logs.mkdir()
    env = child_env(HARNESS_DATA_DIR=str(data_dir), HARNESS_MCP_CONFIG=str(ws.config),
                    AI_HARNESS_TEST_SOCKET_LOG=str(logs), PYTHONPATH=str(AUDIT_SITE))
    code, out, err, _ = run_bounded(args, env, tmp_path / "run", deadline_s=60)
    reports = [json.loads(p.read_text(encoding="utf-8")) for p in logs.glob("sockets-*.json")]
    return code, err, reports


def test_the_socket_oracle_sees_a_listen_without_bind(ws, data_dir, tmp_path):  # noqa: F811
    code, err, reports = _sockets_run(ws, data_dir, tmp_path, [
        sys.executable, "-c", "import socket; s = socket.socket(); s.listen(1); s.close()"])
    assert code == 0, err
    [report] = reports
    assert [e for e in report["events"] if not e["socketpair"]], report


def test_no_socket_is_created_by_the_harness_or_its_session_process(ws, data_dir, tmp_path):  # noqa: F811
    server = ws.server()
    code, err, reports = _sockets_run(ws, data_dir, tmp_path, [
        sys.executable, "main.py", "mcp", "call", "synthetic", "get_project_metadata",
        "--args", ALPHA])
    assert code == 0, err
    assert len(reports) == 2, [r["argv"] for r in reports]  # the CLI and its session process
    for report in reports:
        assert [e for e in report["events"] if not e["socketpair"]] == [], report
    assert server.stopped()


# -- 11. arguments are kept as a keyed hash ----------------------------------------------------


def test_arguments_are_kept_as_an_hmac_with_a_private_local_key(mcp, ws, data_dir, tmp_path):  # noqa: F811
    import hashlib

    ws.server()
    mcp("call", "synthetic", "drop_project", "--args", ALPHA)
    digest = rows(data_dir)[0]["args_hmac"]
    canonical = json.dumps({"project": "demo-alpha"}, sort_keys=True, separators=(",", ":"))
    assert digest is not None and len(digest) == 64
    assert digest != hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    key = data_dir / "keys" / "mcp-args.key"
    assert key.exists()
    if OWNER_ONLY:
        assert stat.S_IMODE(key.stat().st_mode) == 0o600
        assert stat.S_IMODE(key.parent.stat().st_mode) == 0o700
    other = tmp_path / "otros-datos"
    mcp("call", "synthetic", "drop_project", "--args", ALPHA, HARNESS_DATA_DIR=str(other))
    assert rows(other)[0]["args_hmac"] != digest  # another key, another digest


# -- weak tests made real ----------------------------------------------------------------------


def test_the_per_tool_result_limit_applies_below_the_listing_limit(mcp, ws, data_dir):  # noqa: F811
    ws.server("result-over-64k")
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 1 and "result_too_large" in err and "the limit is 65536 bytes" in err, err
    assert out == ""


def test_a_line_just_over_the_limit_is_refused(mcp, ws, data_dir):  # noqa: F811
    ws.server("line-over-limit")
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 1 and "result_too_large" in err, err
    sent = int(err.split("the server sent ")[1].split(" bytes")[0])
    assert 65536 < sent < 65536 + 64 * 1024
    assert out == ""


def test_a_tool_on_the_second_page_of_the_listing_is_found(mcp, ws):  # noqa: F811
    ws.server("paged")
    code, out, err, _ = mcp("call", "synthetic", "get_project_metadata", "--args", ALPHA)
    assert code == 0, err
    assert json.loads(result_lines(out))["name"] == "Demo Alpha"
