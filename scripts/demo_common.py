"""Helpers shared by the demo scripts. Standard library only; same code on every platform."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS_VARS = [
    "HARNESS_DATA_DIR",
    "HARNESS_VAULT_ROOT",
    "HARNESS_PROVIDER",
    "HARNESS_MOCK_BEHAVIOR",
    "HARNESS_MOCK_DELAY_MS",
    "HARNESS_REQUEST_TIMEOUT_S",
    "HARNESS_MEMORY_CONTEXT_MAX_BYTES",
    "HARNESS_MOCK_RESPONSES",
    "HARNESS_SKILLS_DIR",
    "HARNESS_APPROVAL_TTL_S",
    "HARNESS_MCP_CONFIG",
    "AI_HARNESS_MCP_CHILD",
]


class DemoFailure(Exception):
    pass


def setup_output() -> None:
    """Print UTF-8 whatever the console or the redirection is."""
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")


def base_env(**values: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in HARNESS_VARS}
    env["PYTHONUTF8"] = "1"  # the child's output is read back as UTF-8
    env.update(values)
    return env


def harness(env: dict[str, str], *args: str, show: bool = True) -> subprocess.CompletedProcess[str]:
    """Run `main.py` as a separate process and echo what it printed."""
    result = subprocess.run(
        [sys.executable, "main.py", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if show:
        sys.stdout.write(result.stdout)
        sys.stdout.write(result.stderr)
        sys.stdout.flush()
    return result


def spawn(env: dict[str, str], *args: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "main.py", *args],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def step(title: str) -> None:
    print(f"\n== {title}", flush=True)


def check(condition: object, message: str) -> None:
    if not condition:
        raise DemoFailure(message)


def header() -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    print(f"commit:   {commit or 'unknown'}")
    print(f"platform: {platform.system()} {platform.machine()}, Python {platform.python_version()}")


def run(demo) -> int:
    """Run a demo function and turn its outcome into the final line and the exit code."""
    setup_output()
    try:
        skipped = demo() or []
    except DemoFailure as failure:
        print(f"\ndemo: FAIL - {failure}", file=sys.stderr)
        return 1
    for item in skipped:
        print(f"demo: SKIPPED - {item}")
    print("\ndemo: PASS" + (f" ({len(skipped)} step(s) skipped)" if skipped else ""))
    return 0
