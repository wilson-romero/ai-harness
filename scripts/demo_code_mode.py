"""Demo of `/plan` (code-mode slice 2) with the Mock provider and the synthetic MCP server.

Everything lives in temporary directories outside the repository: the allowlist, the scripted
Mock answers, the server's state and the data directory. Same code on macOS and in PowerShell.

Approving needs a person at a terminal. Step (a) runs the real program in a separate process,
where no person types: it refuses before sending anything. The other steps drive the plain
conversation in this process with the scripted terminal the tests use; in step (d) it types
the code the box shows, as a person would, and it is labelled so. The oracle of what ran is
the synthetic server's own `calls.log` and `starts.log`, and the rows of the data directory.

Usage: uv run python scripts/demo_code_mode.py
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

from demo_common import ROOT, base_env, check, harness_bounded, header, run, step

sys.path.insert(0, str(ROOT))
from harness.storage.database import open_database  # noqa: E402
from tests.plan_support import ALPHA, BETA, KEY, QUESTION, McpList, plan_reply  # noqa: E402
from tests.shell_support import CODE, ScriptedTerminal, make_conversation  # noqa: E402

WRITE = {"id": "w", "server": "synthetic", "tool": "set_project_metadata",
         "args": {"project": "demo-alpha", "status": "activo"}}


def query(data: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(data / "harness.sqlite3")
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def converse(data: Path, mcp: McpList, reply: str, approvals: list, *,
             lines: list[str] | None = None, interactive: bool = True) -> tuple[str, int]:
    """The plain conversation in this process; the scripted terminal answers the box."""
    from harness.providers.mock import MockProvider

    conn = open_database(data)
    try:
        provider = MockProvider(responses={KEY: reply})
        terminal = ScriptedTerminal(lines or [f"/plan {QUESTION}"], approvals,
                                    interactive=interactive)
        conversation, _, _ = make_conversation(conn, data, terminal, provider,
                                               mcp_config=mcp.load, columns=100)
        asyncio.run(conversation.run())
    finally:
        conn.close()
    print(terminal.text)
    return terminal.text, provider.calls


def demo() -> list[str]:
    header()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        data = work / "data"
        mcp = McpList(work / "mcp")
        responses = work / "respuestas.json"
        responses.write_text(json.dumps({KEY: plan_reply(ALPHA, BETA)}), encoding="utf-8")
        env = base_env(HARNESS_DATA_DIR=str(data), HARNESS_PROVIDER="mock",
                       HARNESS_MOCK_RESPONSES=str(responses), HARNESS_MCP_CONFIG=str(mcp.path))

        step("(a) main.py plan without a terminal: refused before anything is sent")
        session = harness_bounded(env, "session", "create", "Plan sintético").stdout.strip()
        result = harness_bounded(env, "plan", session, QUESTION)
        check(result.returncode == 2 and "interactive terminal" in result.stderr,
              "plan without a terminal should be refused with exit 2")
        check(query(data, "SELECT COUNT(*) FROM requests") == [(0,)], "nothing should be sent")
        check(mcp.starts() == 0, "no server should start")

        step("(b) a terminal that is not interactive: no box to answer, nothing runs")
        text, calls = converse(data, mcp, plan_reply(ALPHA, BETA), [CODE], interactive=False)
        check("Plan approval requested" not in text, "no box should be offered")
        check("was not approved; nothing was run" in text, "the plan should stay unapproved")
        check(calls == 1 and mcp.starts() == 0, "no server should start without an approval")
        check(query(data, "SELECT approval FROM plan_runs") == [("undecided",)],
              "the plan should be recorded as undecided")

        step("(c) a short form never asks for a plan")
        text, calls = converse(data, mcp, plan_reply(ALPHA, BETA), [CODE],
                               lines=[f"/pla {QUESTION}"])
        check("/plan is typed in full" in text and calls == 0 and mcp.starts() == 0,
              "/pla should be refused as a command, with nothing sent")

        step("(d) scripted terminal types the code: the two reads run, once, shown here only")
        text, calls = converse(data, mcp, plan_reply(ALPHA, BETA), [CODE])
        check(calls == 1, f"exactly one question should reach the provider, not {calls}")
        check(mcp.calls() == ["call get_project_metadata"] * 2, "both steps should run once")
        check("Demo Alpha" in text and "Demo Beta" in text, "both results should be shown")
        check("nothing was sent to the provider" in text, "the final line should say so")

        step("(e) negative cases: a write tool in the plan, a foreign nonce")
        for reply, reason in ((plan_reply(ALPHA, WRITE), "write_not_allowed"),
                              (plan_reply(ALPHA, nonce="0123456789abcdef"), "nonce_mismatch")):
            before = len(mcp.calls())
            text, calls = converse(data, mcp, reply, [CODE])
            check(f"plan refused: {reason}" in text and "Plan approval requested" not in text,
                  f"the plan should be refused with {reason} and no box")
            check(calls == 1 and len(mcp.calls()) == before, "nothing should run or be resent")

        step("(f) the audit holds the plan, its steps and the approval, no argument")
        dump = "\n".join(str(row) for table in ("tool_calls", "plan_runs", "audit_events")
                         for row in query(data, f"SELECT * FROM {table}"))  # noqa: S608
        check("demo-alpha" not in dump and "Demo Alpha" not in dump,
              "no argument or result should be stored")
        rows = query(data, "SELECT plan_step, status FROM tool_calls WHERE plan_id IS NOT NULL "
                           "ORDER BY plan_step")
        check(rows == [(1, "completed"), (2, "completed")], f"unexpected tool calls: {rows}")
        print(f"tool_calls of the plan: {rows}")
    return []


if __name__ == "__main__":
    sys.exit(run(demo))
