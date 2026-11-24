"""Demo of the MCP gateway (Corte 5, first half) with the synthetic MCP server of the tests.

Everything lives in temporary directories outside the repository: the allowlist, the server's
state (its heartbeat) and the data directory. Same code on macOS and in PowerShell.

Usage: uv run python scripts/demo_mcp_gateway.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from demo_common import ROOT, base_env, check, harness_bounded, header, run, step

SERVER = ROOT / "tests" / "fixtures" / "mcp" / "synthetic_server.py"
PROJECT = {"type": "string", "max_length": 64, "pattern": "[a-z0-9][a-z0-9-]*", "required": True}
TOOLS = {
    "get_project_metadata": {"operation": "read", "arguments": {"project": PROJECT}},
    "set_project_metadata": {"operation": "write", "arguments": {"project": PROJECT}},
    "archive_project": {"operation": "read", "arguments": {"project": PROJECT}},
}
ALPHA = '{"project": "demo-alpha"}'


def entry(state: Path, mode: str, call_s: int = 10) -> dict:
    return {
        "command": [sys.executable, str(SERVER), "--state", str(state), "--mode", mode],
        "startup_timeout_s": 10,
        "call_timeout_s": call_s,
        "tools": TOOLS,
    }


def heartbeat_stopped(state: Path, within_s: float = 3.0) -> bool:
    """The synthetic server rewrites `heartbeat` every 100 ms while it lives."""
    beat = state / "heartbeat"
    if not beat.exists():
        return True
    deadline = time.monotonic() + within_s
    previous = beat.read_text(encoding="utf-8")
    while time.monotonic() < deadline:
        time.sleep(0.5)
        current = beat.read_text(encoding="utf-8")
        if current == previous:
            return True
        previous = current
    return False


def demo() -> list[str]:
    header()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        data = work / "data"
        states = {name: work / f"state-{name}" for name in ("synthetic", "leaky", "hanging",
                                                             "stubborn")}
        config = work / "mcp.local.json"
        config.write_text(json.dumps({"format": "ai-harness/mcp/1", "servers": {
            "synthetic": entry(states["synthetic"], "ok"),
            "leaky": entry(states["leaky"], "leaky"),
            "hanging": entry(states["hanging"], "hang-call", call_s=3),
            "stubborn": entry(states["stubborn"], "ignore-close"),
        }}, indent=2), encoding="utf-8")
        bare = base_env(HARNESS_DATA_DIR=str(data))
        env = bare | {"HARNESS_MCP_CONFIG": str(config)}

        step("(a) mcp list without an allowlist, then with the synthetic one")
        result = harness_bounded(bare, "mcp", "list")
        check(result.returncode == 0 and "No MCP servers configured." in result.stdout,
              "without HARNESS_MCP_CONFIG there should be no servers")
        result = harness_bounded(env, "mcp", "list")
        check(result.returncode == 0 and "synthetic\texternal" in result.stdout,
              "the synthetic server is not listed")
        check(str(SERVER) not in result.stdout, "mcp list showed the command")

        step("(b) mcp tools synthetic: allowed, denied and absent tools")
        result = harness_bounded(env, "mcp", "tools", "synthetic")
        lines = {line.split("\t")[0]: line for line in result.stdout.splitlines()}
        check("\tread\tallowed" in lines.get("get_project_metadata", ""), "get not allowed")
        check("denied:tool_not_allowed" in lines.get("drop_project", ""), "drop not denied")
        check("denied:write_requires_approval" in lines.get("set_project_metadata", ""),
              "the write tool is not denied")
        check("\tabsent" in lines.get("archive_project", ""), "archive not absent")
        check(heartbeat_stopped(states["synthetic"]), "the server outlived mcp tools")

        step("(c) mcp call synthetic get_project_metadata: synthetic metadata")
        result = harness_bounded(env, "mcp", "call", "synthetic", "get_project_metadata",
                                 "--args", ALPHA)
        check(result.returncode == 0 and "Demo Alpha" in result.stdout, "the call failed")
        check(heartbeat_stopped(states["synthetic"]), "the server outlived the call")

        step("(d) the same call with an undeclared argument: denied, nothing started")
        starts = (states["synthetic"] / "starts.log").read_text(encoding="utf-8")
        result = harness_bounded(env, "mcp", "call", "synthetic", "get_project_metadata",
                                 "--args", '{"project": "demo-alpha", "path": "/etc"}')
        check(result.returncode == 1 and "argument_not_allowed" in result.stderr,
              "the undeclared argument was not denied")
        check((states["synthetic"] / "starts.log").read_text(encoding="utf-8") == starts,
              "the server was started for a denied call")

        step("(e) a tool declared as a write: write_requires_approval")
        result = harness_bounded(env, "mcp", "call", "synthetic", "set_project_metadata",
                                 "--args", ALPHA)
        check(result.returncode == 1 and "write_requires_approval" in result.stderr,
              "the write was not denied")

        step("(f) a result with credentials and terminal escapes: masked and cleaned")
        result = harness_bounded(env, "mcp", "call", "leaky", "get_project_metadata",
                                 "--args", ALPHA)
        check(result.returncode == 0 and "[REDACTED:github]" in result.stdout,
              "the credential was not masked")
        check("\x1b" not in result.stdout + result.stderr, "an escape sequence got through")
        check("2 credential(s) redacted" in result.stderr, "the redactions were not counted")

        step("(g) a tool that never ends: timeout within its deadline, server stopped")
        started = time.monotonic()
        result = harness_bounded(env, "mcp", "call", "hanging", "get_project_metadata",
                                 "--args", ALPHA, deadline_s=60)
        elapsed = time.monotonic() - started
        print(f"elapsed: {elapsed:.1f} s (call deadline 3 s)")
        check(result.returncode == 1 and "timeout" in result.stderr, "no timeout reported")
        check(elapsed < 3 + 10, "the command outlived its deadline")
        check(heartbeat_stopped(states["hanging"]), "the hanging server is still alive")

        step("(h) a server that ignores the end of its input and SIGTERM: stopped anyway")
        result = harness_bounded(env, "mcp", "call", "stubborn", "get_project_metadata",
                                 "--args", ALPHA, deadline_s=60)
        check(result.returncode == 0, "the call to the stubborn server failed")
        check(heartbeat_stopped(states["stubborn"]), "the stubborn server is still alive")

        step("(i) SELECT server, tool, decision, reason, status, error_code FROM tool_calls")
        conn = sqlite3.connect(data / "harness.sqlite3")
        try:
            rows = conn.execute("SELECT server, tool, decision, reason, status, error_code "
                                "FROM tool_calls ORDER BY created_at").fetchall()
            everything = "\n".join(str(value) for row in conn.execute("SELECT * FROM tool_calls")
                                   for value in row)
        finally:
            conn.close()
        for row in rows:
            print("\t".join(str(value) if value is not None else "-" for value in row))
        check(len(rows) == 6, f"expected 6 audited calls, found {len(rows)}")
        check("demo-alpha" not in everything and "/etc" not in everything,
              "an argument value was stored")
    return []


if __name__ == "__main__":
    sys.exit(run(demo))
