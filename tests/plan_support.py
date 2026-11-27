"""Helpers for the tests of `/plan` (code-mode slice 2): a synthetic MCP list, scripted Mock
replies that hold a plan, and the rows a plan leaves. Everything is synthetic."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from harness.mcp.config import load_config
from harness.providers.mock import PLAN_NONCE_TOKEN, MockProvider
from tests.mcp_support import DEFAULT_TOOLS, Server, server_entry, write_config

QUESTION = "¿qué proyectos de demo tienen la etiqueta alpha?"
KEY = "etiqueta alpha"  # what the scripted Mock looks for in the prompt
ALPHA = {"id": "a", "server": "synthetic", "tool": "get_project_metadata",
         "args": {"project": "demo-alpha"}}
BETA = {"id": "b", "server": "synthetic", "tool": "get_project_metadata",
        "args": {"project": "demo-beta"}}


def plan_object(*steps: dict, nonce: str = PLAN_NONCE_TOKEN, **extra) -> dict:
    return {"format": "ai-harness/plan/1", "nonce": nonce, "steps": list(steps), **extra}


def plan_reply(*steps: dict, nonce: str = PLAN_NONCE_TOKEN, prose: str = "Propongo este plan:",
               **extra) -> str:
    body = json.dumps(plan_object(*steps, nonce=nonce, **extra), ensure_ascii=False)
    return f"{prose}\n\n```json\n{body}\n```\n"


class McpList:
    """A synthetic allowlist on disk, read the way the harness reads it."""

    def __init__(self, root: Path, mode: str = "ok", *, tools: dict | None = None,
                 call: int = 5, startup: int = 5) -> None:
        self.path = root / "mcp.local.json"
        self.server = Server(root / "state")
        self.server.state.mkdir(parents=True, exist_ok=True)
        self.write(mode, tools=tools, call=call, startup=startup)

    def write(self, mode: str = "ok", *, tools: dict | None = None, call: int = 5,
              startup: int = 5) -> None:
        write_config(self.path, {"synthetic": server_entry(
            self.server.state, mode, tools=DEFAULT_TOOLS if tools is None else tools,
            call=call, startup=startup)})

    def load(self):
        return load_config({"HARNESS_MCP_CONFIG": str(self.path)})

    def calls(self) -> list[str]:
        return self.server.calls()

    def starts(self) -> int:
        return self.server.starts()


def scripted_mock(reply: str, key: str = KEY, **options) -> MockProvider:
    return MockProvider(responses={key: reply}, **options)


def rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[tuple]:
    return [tuple(row) for row in conn.execute(sql, params)]
