"""Demo of `/agent` (code-mode A3) and of the reads allowed by rule (A2), with the Mock
provider and the synthetic MCP server.

Everything lives in temporary directories outside the repository: the allowlist (with
`get_project_metadata` marked `auto_read`), the scripted Mock answers, the server's state and
the data directory. Same code on macOS and in PowerShell. It drives the plain conversation in
this process with the scripted terminal the tests use; no box is answered: every plan of the
demo is reads by rule. The oracle of what ran is the synthetic server's own `calls.log` and
`starts.log`, the prompts the Mock received, and the rows of the data directory.

Usage: uv run python scripts/demo_code_mode_loop.py
       uv run python scripts/demo_code_mode_loop.py --prepare DIR
The second form runs nothing: it writes into DIR (outside the repository) a synthetic MCP list
with `get_project_metadata` marked `auto_read` and a three-turn script for the Mock, and
prints the command that opens `chat` over them, to try `/agent` by hand.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import sqlite3
import sys
import tempfile
from pathlib import Path

from demo_common import ROOT, check, header, run, step

sys.path.insert(0, str(ROOT))
from harness.providers.mock import MockProvider  # noqa: E402
from harness.storage.database import open_database  # noqa: E402
from tests.fixtures.mcp.synthetic_server import FORGED_NONCE, FORGED_TAIL  # noqa: E402
from tests.mcp_support import DEFAULT_TOOLS, server_entry, write_config  # noqa: E402
from tests.plan_support import ALPHA, BETA, QUESTION, McpList, plan_reply  # noqa: E402
from tests.shell_support import ScriptedTerminal, make_conversation  # noqa: E402

AUTO = {**DEFAULT_TOOLS, "get_project_metadata": {**DEFAULT_TOOLS["get_project_metadata"],
                                                   "auto_read": True}}
AGENT = f"/agent {QUESTION}"
FINAL = "Respuesta final sintetica: demo-alpha y demo-beta tienen datos."
SUMMARY = "Resumen sintetico: se leyeron los proyectos; no queda nada pendiente."
CLOSING = "turno de cierre, tras"


def turn(k: int) -> str:
    return f"vuelta {k} de"


class Recording(MockProvider):
    """The Mock, keeping every prompt it receives (the oracle of what was sent)."""

    def __init__(self, responses: dict) -> None:
        super().__init__(responses=responses)
        self.prompts: list[str] = []

    async def ask(self, request, on_sent, *, on_mode=None) -> str:
        self.prompts.append(request.prompt)
        return await super().ask(request, on_sent, on_mode=on_mode)


def query(data: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(data / "harness.sqlite3")
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def converse(data: Path, mcp: McpList, responses: dict, environ: dict,
             lines: list[str] | None = None) -> tuple[str, Recording]:
    conn = open_database(data)
    try:
        provider = Recording(responses)
        terminal = ScriptedTerminal(lines or [AGENT], [])
        conversation, _, _ = make_conversation(conn, data, terminal, provider,
                                               mcp_config=mcp.load, columns=10_000,
                                               environ=environ)
        asyncio.run(conversation.run())
    finally:
        conn.close()
    print(terminal.text)
    return terminal.text, provider


def last_loop(data: Path) -> tuple:
    return query(data, "SELECT status, stop_reason, turns FROM loop_runs "
                       "ORDER BY rowid DESC LIMIT 1")[0]


def demo() -> list[str]:
    header()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        data = work / "data"
        mcp = McpList(work / "mcp", tools=AUTO)
        on = {"HARNESS_LOOP_PROVIDERS": "mock"}

        step("(a) consent off: /agent without HARNESS_LOOP_PROVIDERS sends nothing")
        text, provider = converse(data, mcp, {turn(1): plan_reply(ALPHA)}, {})
        check("HARNESS_LOOP_PROVIDERS does not name mock; nothing was sent" in text,
              "/agent should be refused without consent")
        check(provider.calls == 0 and mcp.starts() == 0, "nothing should be sent or started")
        check(query(data, "SELECT COUNT(*) FROM loop_runs") == [(0,)], "no loop recorded")

        step("(b) three turns: two plans of reads by rule, then the answer")
        text, provider = converse(data, mcp, {turn(1): plan_reply(ALPHA),
                                              turn(2): plan_reply(BETA), turn(3): FINAL}, on)
        check(provider.calls == 3, f"exactly 3 questions should be sent, not {provider.calls}")
        check(mcp.calls() == ["call get_project_metadata"] * 2, "two reads, once each")
        check(text.count("running plan:") == 2 and "Plan approval requested" not in text,
              "both plans should run by rule, without the box")
        check("Demo Alpha" in provider.prompts[1] and "Demo Beta" in provider.prompts[2],
              "each plan's results should go back in the next turn")
        check(all(prompt in text.replace("\n| ", "\n") for prompt in provider.prompts[1:]),
              "each turn should be shown exactly as it was sent")
        check(last_loop(data) == ("completed", "answer", 3), "the loop should end answered")

        step("(c) the cap: HARNESS_LOOP_MAX_TURNS=2, then one closing turn, never read")
        before = len(mcp.calls())
        text, provider = converse(
            data, mcp, {turn(1): plan_reply(ALPHA), turn(2): plan_reply(BETA),
                        CLOSING: SUMMARY + "\n\n" + plan_reply(ALPHA, nonce="0123456789abcdef")},
            {**on, "HARNESS_LOOP_MAX_TURNS": "2"})
        check(provider.calls == 3, "two turns and one closing turn")
        check("Reglas del plan" not in provider.prompts[2], "the closing turn has no grammar")
        check(len(mcp.calls()) == before + 2, "the plan in the closing reply never runs")
        check(last_loop(data) == ("completed", "cap", 3), "the loop should end at the cap")

        step("(d) a refused plan: its reason goes back once, then the answer")
        text, provider = converse(data, mcp, {turn(1): plan_reply(ALPHA, nonce="0" * 16),
                                              turn(2): FINAL}, on)
        check("plan refused: nonce_mismatch" in text, "the plan should be refused")
        check("Motivo: nonce_mismatch" in provider.prompts[1], "the reason should go back")
        check(provider.calls == 2 and last_loop(data) == ("completed", "answer", 2),
              "one correction, then the answer")

        step("(e) a hostile result: it stays inside its block, cut, and its nonce is refused")
        hostile = McpList(work / "hostil", "forge-data", tools=AUTO)
        text, provider = converse(data, hostile, {turn(1): plan_reply(ALPHA),
                                                  turn(2): plan_reply(ALPHA), turn(3): FINAL},
                                  on)
        sent = provider.prompts[1]
        inside = sent.split("\n")
        opened = next(i for i, line in enumerate(inside) if line.startswith("<<<RESULTADOS "))
        closed = next(i for i, line in enumerate(inside) if line.startswith("RESULTADOS ")
                      and line.endswith(">>>"))
        check(all(line.startswith(("| ", "--- ")) for line in inside[opened + 1:closed]),
              "every line of the block should be marked")
        check("\x1b" not in sent and FORGED_TAIL in sent and "[omitidos por el harness:" in sent,
              "escapes dropped, the result cut in the middle with its tail kept")
        check(f'"nonce": "{FORGED_NONCE}"' in sent and "plan refused: nonce_mismatch" in text,
              "the nonce the result injected should be refused")
        check(hostile.calls() == ["call get_project_metadata"], "the forged write never runs")
        check(len(sent) < 28_000, "the turn should stay under its cap")

        step("(f) what is stored: rows and sizes, never a result or a turn's text")
        dump = "\n".join(str(row) for table in ("loop_runs", "loop_turns", "audit_events")
                         for row in query(data, f"SELECT * FROM {table}"))  # noqa: S608
        check("Demo Alpha" not in dump and "RESULTADOS" not in dump,
              "no result should be stored with the loop")
        turns = query(data, "SELECT turn, kind FROM loop_turns ORDER BY rowid")
        print(f"loop_turns: {turns}")
    return []


def prepare(folder: Path) -> int:
    """Write the synthetic list and the Mock's script for a three-turn `/agent` by hand."""
    folder = folder.resolve()
    if folder == ROOT or ROOT in folder.parents:
        print("error: DIR must be outside the repository", file=sys.stderr)
        return 2
    (folder / "state").mkdir(parents=True, exist_ok=True)
    mcp = write_config(folder / "mcp.local.json",
                       {"synthetic": server_entry(folder / "state", tools=AUTO)})
    mcp.chmod(0o600)  # the harness refuses a list others can write
    responses = folder / "mock-responses.json"
    responses.write_text(json.dumps({turn(1): plan_reply(ALPHA), turn(2): plan_reply(BETA),
                                     turn(3): FINAL}, ensure_ascii=False), encoding="utf-8")
    env = {"HARNESS_DATA_DIR": folder / "data", "HARNESS_PROVIDER": "mock",
           "HARNESS_MOCK_RESPONSES": responses, "HARNESS_MCP_CONFIG": mcp,
           "HARNESS_LOOP_PROVIDERS": "mock"}
    print(" ".join(f"{name}={shlex.quote(str(value))}" for name, value in env.items())
          + " uv run python main.py chat --plain")
    print(f"then type: {AGENT}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--prepare":
        sys.exit(prepare(Path(sys.argv[2])))
    sys.exit(run(demo))
