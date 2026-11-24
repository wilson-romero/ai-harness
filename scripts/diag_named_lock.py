#!/usr/bin/env python3
"""Diagnose the cross-process browser lock: one process holds it, another waits for it.

Usage: uv run python scripts/diag_named_lock.py

Reproduces `test_second_process_waits_for_the_named_lock_and_gets_it` with a timestamp for
every attempt and every SQLite error, in two phases: raw `sqlite3` calls, then the harness's
own `NamedLock.acquire_within`. Standard library and the harness lock module only. Bounded:
each phase is killed after PHASE_LIMIT_S, the whole run takes at most about 40 seconds.
Prints a short block to paste back; it contains timings and SQLite error names, no paths.
"""

from __future__ import annotations

import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOLD_S = 1.5
WAIT_S = 12.0
PHASE_LIMIT_S = 18.0
GAP_WARNING_S = 2.0

HOLDER = r"""
import json, sqlite3, sys, time
path, hold_s = sys.argv[1], float(sys.argv[2])
t0 = time.monotonic()
def say(event, **extra):
    print(json.dumps({"who": "holder", "event": event, "t": round(time.monotonic() - t0, 3)} | extra), flush=True)
say("started")
conn = sqlite3.connect(path, timeout=0, autocommit=True)
conn.execute("BEGIN EXCLUSIVE")
say("held")
time.sleep(hold_s)
conn.execute("ROLLBACK")
conn.close()
say("released")
"""

RAW_WAITER = r"""
import json, sqlite3, sys, time
path, wait_s = sys.argv[1], float(sys.argv[2])
t0 = time.monotonic()
def say(event, **extra):
    print(json.dumps({"who": "waiter", "event": event, "t": round(time.monotonic() - t0, 3)} | extra), flush=True)
say("started")
deadline = time.monotonic() + wait_s
attempt = 0
while True:
    attempt += 1
    began = time.monotonic()
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=0, autocommit=True)
        conn.execute("BEGIN EXCLUSIVE")
        say("attempt", n=attempt, ok=True, took=round(time.monotonic() - began, 3))
        conn.execute("ROLLBACK")
        conn.close()
        say("done", acquired=True)
        break
    except sqlite3.Error as exc:
        if conn is not None:
            conn.close()
        say("attempt", n=attempt, ok=False, took=round(time.monotonic() - began, 3),
            error=getattr(exc, "sqlite_errorname", None) or type(exc).__name__, text=str(exc)[:80])
    if time.monotonic() >= deadline:
        say("done", acquired=False)
        break
    time.sleep(0.25)
"""

HARNESS_WAITER = r"""
import json, sys, time
t0 = time.monotonic()
def say(event, **extra):
    print(json.dumps({"who": "waiter", "event": event, "t": round(time.monotonic() - t0, 3)} | extra), flush=True)
say("started")
import asyncio
from pathlib import Path
from harness.storage.locks import NamedLock
say("imported")

class Traced(NamedLock):
    attempts = 0
    def acquire(self):
        Traced.attempts += 1
        began = time.monotonic()
        try:
            ok = super().acquire()
        except Exception as exc:
            say("attempt", n=Traced.attempts, ok=False, took=round(time.monotonic() - began, 3),
                error=type(exc).__name__, text=str(exc)[:80])
            raise
        say("attempt", n=Traced.attempts, ok=ok, took=round(time.monotonic() - began, 3),
            error=None if ok else self.last_error)
        return ok

async def main():
    say("loop-ready", loop=type(asyncio.get_running_loop()).__name__)
    return await Traced(Path(sys.argv[1]), "browser").acquire_within(float(sys.argv[2]))

try:
    acquired = asyncio.run(main())
    say("done", acquired=acquired)
except Exception as exc:
    say("done", acquired=False, error=type(exc).__name__, text=str(exc)[:80])
"""


def setup_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def spawn(code: str, *args: str) -> subprocess.Popen[str]:
    env = dict(os.environ)  # copied, never built from scratch
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUTF8"] = "1"
    return subprocess.Popen(
        [sys.executable, "-c", code, *args],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def collect(proc: subprocess.Popen[str], sink: list, origin: float, label: str) -> threading.Thread:
    def read() -> None:
        for line in proc.stdout:
            arrived = round(time.monotonic() - origin, 3)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"who": label, "event": "output", "text": line.strip()[:120]}
            event["at"] = arrived
            sink.append(event)

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    return thread


def reap(proc: subprocess.Popen[str]) -> str:
    if proc.poll() is None:
        proc.kill()
        state = "killed"
    else:
        state = f"exit {proc.returncode}"
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        state += ", did not die"
    return state


def run_phase(name: str, waiter_code: str, workdir: Path) -> dict:
    # The harness lock lives at <data dir>/locks/browser.lock; the raw phase uses the same file.
    data_dir = workdir / name
    lock_file = data_dir / "locks" / "browser.lock"
    lock_file.parent.mkdir(parents=True)
    waiter_arg = str(data_dir) if waiter_code is HARNESS_WAITER else str(lock_file)
    path = str(lock_file)
    events: list[dict] = []
    origin = time.monotonic()
    wall_origin = time.time()
    holder = spawn(HOLDER, path, str(HOLD_S))
    readers = [collect(holder, events, origin, "holder")]
    waiter = None
    deadline = origin + PHASE_LIMIT_S
    max_gap = 0.0
    last = time.monotonic()
    while time.monotonic() < deadline:
        now = time.monotonic()
        max_gap = max(max_gap, now - last)
        last = now
        if waiter is None and any(e.get("event") == "held" for e in events):
            waiter = spawn(waiter_code, waiter_arg, str(WAIT_S))
            readers.append(collect(waiter, events, origin, "waiter"))
        if waiter is not None and waiter.poll() is not None and holder.poll() is not None:
            break
        time.sleep(0.05)
    states = {"holder": reap(holder), "waiter": reap(waiter) if waiter else "never started"}
    for reader in readers:
        reader.join(2)
    for event in events:  # no local path ever reaches the pasted block
        if "text" in event:
            event["text"] = event["text"].replace(str(workdir), "<tmp>")
    elapsed_mono = time.monotonic() - origin
    elapsed_wall = time.time() - wall_origin
    return summarise(name, events, states, max_gap, elapsed_mono, elapsed_wall)


def summarise(name, events, states, max_gap, elapsed_mono, elapsed_wall) -> dict:
    def first(who: str, event: str):
        return next((e for e in events if e.get("who") == who and e.get("event") == event), None)

    attempts = [e for e in events if e.get("who") == "waiter" and e.get("event") == "attempt"]
    times = [e["t"] for e in attempts]
    gaps = [b - a for a, b in zip(times, times[1:])]
    errors: dict[str, int] = {}
    for e in attempts:
        if not e.get("ok"):
            key = f"{e.get('error')}: {e.get('text', '')}".strip(": ")
            errors[key] = errors.get(key, 0) + 1
    done = first("waiter", "done")
    held, released = first("holder", "held"), first("holder", "released")
    success = next((e for e in attempts if e.get("ok")), None)
    return {
        "phase": name,
        "verdict": "acquired" if done and done.get("acquired") else "NOT acquired",
        "holder held at": held and held["at"],
        "holder released at": released and released["at"],
        "waiter started at": (first("waiter", "started") or {}).get("at"),
        "waiter imported at": (first("waiter", "imported") or {}).get("at"),
        "waiter loop": (first("waiter", "loop-ready") or {}).get("loop"),
        "attempts": len(attempts),
        "first success at": success and success["at"],
        "slowest attempt s": max((e.get("took", 0) for e in attempts), default=None),
        "largest gap between attempts s": round(max(gaps), 3) if gaps else None,
        "errors": errors or None,
        "waiter end": done and {k: done[k] for k in ("error", "text") if k in done} or None,
        "processes": states,
        "parent largest pause s": round(max_gap, 3),
        "elapsed monotonic s": round(elapsed_mono, 3),
        "elapsed wall s": round(elapsed_wall, 3),
        "other output": [e.get("text") for e in events if e.get("event") == "output"][:5] or None,
    }


def main() -> int:
    setup_output()
    print("Diagnosing the named lock: two phases, about 40 seconds at most...", flush=True)
    with tempfile.TemporaryDirectory(prefix="ai-harness-diag-") as tmp:
        phases = [
            run_phase("raw-sqlite", RAW_WAITER, Path(tmp)),
            run_phase("harness-lock", HARNESS_WAITER, Path(tmp)),
        ]
    base = getattr(sys, "_base_executable", sys.executable)
    lines = [
        "",
        "---- named lock diagnosis (paste only this) ----",
        f"python {platform.python_version()} on {platform.platform(terse=True)} {platform.machine()}",
        f"sqlite {sqlite3.sqlite_version}; venv launcher in between: {base != sys.executable}",
    ]
    for phase in phases:
        lines.append(f"[{phase.pop('phase')}]")
        lines += [f"  {key}: {value}" for key, value in phase.items() if value is not None]
        if phase["parent largest pause s"] > GAP_WARNING_S:
            lines.append("  NOTE: this process was paused for seconds (sleep, suspend or starvation)")
    lines.append("---- end ----")
    print("\n".join(lines), flush=True)
    return 0 if all(p["verdict"] == "acquired" for p in phases) else 1


if __name__ == "__main__":
    sys.exit(main())
