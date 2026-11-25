"""Stands in for the harness's MCP session process and hangs in C code holding the GIL.

Used to prove that the harness's deadline does not depend on the session process cooperating
(independent review of 2026-11-24, finding 1). Before hanging it starts a grandchild that
rewrites `heartbeat-grandchild` under STATE_DIR every 100 ms, so the test can see whether the
whole process tree was killed without sending any signal itself.

Usage: python stuck_worker.py STATE_DIR
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic_server import GRANDCHILD  # noqa: E402

state = Path(sys.argv[1])
state.mkdir(parents=True, exist_ok=True)
grandchild = subprocess.Popen(
    [sys.executable, "-c", GRANDCHILD, str(state / "heartbeat-grandchild")],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
# Pids for the test's cleanup only (it kills them if a heartbeat still moves).
(state / "stuck.log").write_text(f"stuck {os.getpid()} {grandchild.pid}\n", encoding="utf-8")
while True:  # catastrophic backtracking in the C regex engine: the GIL is never released
    re.match(r"^(a+)+$", "a" * 40 + "!")
