"""How long each phase of a Copilot Web question took (change copilot-turn-speed, D1).

Durations only: milliseconds per phase, which path the question took, how its end was decided
and how it ended. Never a prompt, a reply, a URL or page text. One JSON line per question in
`HARNESS_DATA_DIR/copilot/timings.jsonl`, keyed by the request id that SQLite already holds;
`main.py history <session> --timings` shows them. The file is trimmed to its last lines when it
grows, so it never needs looking after.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

TIMINGS_FILE = "timings.jsonl"
KEEP_LINES = 1000  # after trimming
TRIM_AT_BYTES = 512_000

# The phases in the order a question goes through them. `read` is inside `reply_end` (the
# last read of the reply, the one returned); the others do not overlap.
PHASES = (
    "reuse_check",  # is the held tab still showing this session's conversation? (D2)
    "navigate",  # load the conversation's address
    "ready",  # wait for the chat to be ready
    "settle",  # wait for the page to stop adding elements
    "history",  # wait for a reopened conversation's turns
    "guard",  # the checks right before typing
    "mode",  # set and confirm the response mode
    "type",  # fill the editor and check its length
    "send",  # the key press or click
    "reply_start",  # from the send to the first text of the new reply
    "reply_end",  # from that first text to the end of the reply
    "read",  # the last read of the reply (within reply_end)
    "identifier",  # wait for the conversation identifier after the reply
    "post",  # the checks after the reply (address, mode read again)
)
OUTCOMES = ("answered", "failed", "uncertain", "cancelled")
PATHS = ("reload", "reuse")
ENDS = ("signal", "window", "none")
# Why a held tab was not asked again without reloading (D2): fixed words only.
DECLINED = (
    "new tab",  # the question runs in a tab that answered nothing yet
    "other session",  # the tab last answered another session or conversation
    "no conversation",  # the session has no remote conversation yet
    "idle",  # the last answer is older than the reuse limit
    "address",  # the address does not name the session's conversation
    "page state",  # the page is not the ready chat on the configured host
    "turns",  # the turns are not those the tab showed after its last answer
    "busy",  # a reply is in progress or the editor is not empty
    "error",  # the page did not answer the checks
)
LABELS = {
    "reuse_check": "reuse check",
    "reply_start": "reply start",
    "reply_end": "reply end",
}


@dataclass
class TurnTimings:
    request_id: str
    session_id: str
    path: str = "reload"  # "reload" or "reuse" (the held tab was asked again, D2)
    declined: str | None = None  # why the held tab was not reused: a fixed word
    end: str = "none"  # "signal" (fast end, D3), "window" (stability window) or "none"
    attempts: int = 0
    outcome: str = "failed"
    phases_ms: dict[str, int] = field(default_factory=dict)
    total_ms: int = 0
    at: str = ""

    @contextlib.contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started = time.monotonic()
        try:
            yield
        finally:
            self.add(name, time.monotonic() - started)

    def add(self, name: str, seconds: float) -> None:
        assert name in PHASES, name
        self.phases_ms[name] = self.phases_ms.get(name, 0) + max(0, round(seconds * 1000))

    def line(self) -> str:
        """One line for the person: path, end, outcome and the phases that took any time."""
        phases = ", ".join(f"{LABELS.get(name, name)} {self.phases_ms[name] / 1000:.2f}"
                           for name in PHASES if self.phases_ms.get(name))
        why = f" ({self.declined})" if self.declined else ""
        return (f"timings (s): {self.outcome}, path {self.path}{why}, end {self.end}, "
                f"total {self.total_ms / 1000:.2f}" + (f"; {phases}" if phases else ""))


def timings_path(data_dir: Path) -> Path:
    return data_dir / "copilot" / TIMINGS_FILE


def record(data_dir: Path, timings: TurnTimings) -> None:
    """Append one question's timings. Never fails the question: an error here is dropped."""
    timings.at = datetime.now(UTC).isoformat(timespec="seconds")
    path = timings_path(data_dir)
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(asdict(timings), sort_keys=True) + "\n")
        if path.stat().st_size > TRIM_AT_BYTES:
            lines = path.read_text(encoding="utf-8").splitlines()[-KEEP_LINES:]
            tmp = path.with_suffix(".tmp")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            tmp.replace(path)


def read_for(data_dir: Path, request_ids: Iterable[str]) -> dict[str, TurnTimings]:
    """The recorded timings of these requests (the last line of each wins). Lines that are
    not ours (malformed, other fields) are skipped: the file only holds numbers and words."""
    wanted = set(request_ids)
    found: dict[str, TurnTimings] = {}
    path = timings_path(data_dir)
    if not wanted or not path.is_file():
        return found
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            data = json.loads(raw)
            if data.get("request_id") not in wanted:
                continue
            item = TurnTimings(**data)
            if item.outcome not in OUTCOMES or item.path not in PATHS or item.end not in ENDS \
                    or (item.declined is not None and item.declined not in DECLINED) or not all(
                    name in PHASES and isinstance(ms, int) for name, ms in item.phases_ms.items()):
                continue
        except (ValueError, TypeError, AttributeError):
            continue
        found[item.request_id] = item
    return found
