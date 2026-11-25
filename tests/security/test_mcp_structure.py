"""Structure of `harness/mcp/` (mcp-gateway D9, D13, task 4.4).

Two ways to a process, each in one place (D4 as revised on 2026-11-24): `client.py` starts the
session process with the SDK's helper (its own process group or Job Object), and `transport.py`
starts the server inside it with `anyio.open_process` (no new group: the harness's kill of the
session process's group reaches the server). There is no shell, no `subprocess`, no listening socket, no HTTP transport and no import of the
Enterprise Architect package. What this proves: the source of `harness/mcp/` contains none of
those forms. What it does not prove: what the SDK does inside (the audit-hook test in
`tests/integration/test_mcp_cli.py` covers sockets at run time).
"""

from __future__ import annotations

import ast
import subprocess
import sys

import pytest

from tests.conftest import REPO_ROOT

PACKAGE = REPO_ROOT / "harness" / "mcp"
FORBIDDEN_MODULES = (
    "subprocess", "socket", "socketserver", "http.server", "multiprocessing",
    "harness.enterprise_architect", "mcp.server", "mcp.client.sse",
    "mcp.client.streamable_http", "mcp.client.session_group", "uvicorn", "starlette",
)
FORBIDDEN_CALLS = {"system", "popen", "start_server", "listen", "serve", "serve_forever",
                   "create_subprocess_exec", "create_subprocess_shell", "open_process", "Popen",
                   "streamable_http_client", "exec", "eval"}


def problems(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
        else:
            names = []
        for name in names:
            if any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN_MODULES):
                found.append(f"import {name}")
        if isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if called in FORBIDDEN_CALLS:
                found.append(f"call {called}")
            for keyword in node.keywords:
                if keyword.arg == "shell":
                    found.append("shell=")
    return found


# The one allowed start of the server process, and only in this module.
ALLOWED = {("transport.py", "call open_process")}


def test_the_mcp_package_has_no_other_way_to_a_process_or_a_socket():
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        offenders += [f"{path.name}: {p}" for p in problems(path.read_text(encoding="utf-8"))
                      if (path.name, p) not in ALLOWED]
    assert offenders == []


def test_the_server_is_started_exactly_once_in_the_transport():
    source = (PACKAGE / "transport.py").read_text(encoding="utf-8")
    assert problems(source).count("call open_process") == 1
    assert "start_new_session" not in source and "creationflags" not in source


SAMPLES = [
    "import subprocess",
    "from subprocess import run",
    "import socket",
    "import socketserver",
    "from http.server import HTTPServer",
    "import os\nos.system('x')",
    "import os\nos.popen('x')",
    "import asyncio\nasyncio.start_server(h)",
    "s.listen(1)",
    "run(cmd, shell=True)",
    "from harness.enterprise_architect import server",
    "from mcp.client.streamable_http import streamable_http_client",
    "import anyio\nanyio.open_process(['x'])",
    "from mcp.server.mcpserver import MCPServer",
]


@pytest.mark.parametrize("sample", SAMPLES)
def test_each_forbidden_form_is_found(sample):
    assert problems(sample), sample


def test_the_package_is_where_the_check_looks():
    assert {p.name for p in PACKAGE.glob("*.py")} >= {
        "config.py", "policy.py", "client.py", "transport.py", "render.py", "audit.py",
        "commands.py", "worker.py",
    }


def test_only_the_supervisor_starts_a_process_in_its_own_kill_scope():
    users = [p.name for p in PACKAGE.rglob("*.py")
             if "_create_platform_compatible_process" in p.read_text(encoding="utf-8")]
    assert users == ["client.py"]


def test_the_cli_does_not_import_the_sdk_for_other_commands():
    code = ("import sys, harness.cli; "
            "print(any(m == 'mcp' or m.startswith('mcp.') for m in sys.modules))")
    done = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True,
                          text=True, timeout=60)
    assert done.stdout.strip() == "False", done.stderr
