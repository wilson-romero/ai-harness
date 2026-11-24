#!/usr/bin/env python3
"""Copilot Web probe: measure the real interface with fixed synthetic prompts, by hand.

Usage (see docs/runbook/copilot.md):

    uv run python scripts/copilot_probe.py login        # open the dedicated profile, sign in
    uv run python scripts/copilot_probe.py measure      # finds the controls if needed, then
                                                        # 12 timed sends, reopen, prompt sizes
    uv run python scripts/copilot_probe.py login-state  # what an expired login looks like
    uv run python scripts/copilot_probe.py discover     # only find the controls (2 sends)
    uv run python scripts/copilot_probe.py structure    # sanitised page structure, no sends

The probe sends only the fixed prompts below and accepts no prompt of its own from arguments,
environment or standard input. It writes its measurements only under
`HARNESS_DATA_DIR/copilot/`, and refuses a destination that Git could version. It stores
locators, the shape of a conversation reference (never its value), login host names, counts,
times and booleans: never the URL, account names, titles or response text. It records no
screenshots, traces, HAR, video or storage state.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parent.parent
for _path in (ROOT, ROOT / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from playwright.async_api import BrowserContext, Locator, Page  # noqa: E402
from playwright.async_api import Error as PlaywrightError  # noqa: E402

from harness.browser.edge import EdgeLauncher, edge_version  # noqa: E402
from harness.browser.login import recorded_ready_path  # noqa: E402
from harness.browser.page_state import (  # noqa: E402
    guest_page_advice,
    host_of,
    ready_path,
    signed_out_hints,
)
from harness.browser.runner import run_browser  # noqa: E402
from harness.browser.structure import structure_dump  # noqa: E402
from harness.config import Settings  # noqa: E402
from harness.core.errors import HarnessError  # noqa: E402
from copilot_discovery import ASK, Timing, discover, js  # noqa: E402

from harness.providers.copilot_ui import (  # noqa: E402
    CANDIDATES_FILE,
    MEASUREMENT_DIR,
    MEASUREMENT_FILE,
    SCHEMA_VERSION,
    ConversationRef,
    EndSignal,
    Locators,
    LoginShape,
    MeasurementError,
    UiMeasurement,
)
from pydantic import ValidationError  # noqa: E402

DISCOVERED_FILE = "discovered.json"
REQUIRED_LOCATORS = ("composer", "new_conversation", "user_turn", "assistant_turn")

# -- what the probe sends: fixed, synthetic, nothing else ---------------------------------------

PROMPTS = (
    "Responde solo con la palabra OK y, al final, repite exactamente este marcador: ZQX-END-1",
    "Cuenta de 1 a 60 en una sola linea separando los numeros con comas y, al final, repite "
    "exactamente este marcador: ZQX-END-2",
    "Cuenta de 1 a 300 en una sola linea separando los numeros con comas y, al final, repite "
    "exactamente este marcador: ZQX-END-3",
    "Escribe una lista de tres frutas y un bloque de codigo Python que imprima hola y, al final, "
    "repite exactamente este marcador: ZQX-END-4",
)
SIZE_PROMPT_HEAD = "Responde solo con LEN-OK. Relleno sintetico sin significado: "
SIZE_MARKER = "LEN-OK"
SIZES = (2000, 8000, 16000, 32000)
CONVERSATIONS = 3

SAMPLE_INTERVAL_S = 0.1
STABLE_WINDOWS_MS = (1000, 2000, 4000)
SETTLE_MS = 3000  # after the longest window, how long to wait for a late structural signal
SEND_DEADLINE_S = 300.0
RESUBMIT_AFTER_MS = 4000  # no turn added and the editor still full: the key press was lost
TURNS_SETTLE_S = 5.0
LOGIN_HOST_SETTLE_S = 3.0
STRUCTURAL = ("stop_hidden", "send_ready", "done_control", "aria_busy")
ID_LIKE = re.compile(r"(?=.*\d)[A-Za-z0-9_-]{8,}")

EXIT_OK, EXIT_ERROR, EXIT_INTERRUPTED = 0, 1, 130


def marker_of(index: int) -> str:
    return f"ZQX-END-{index + 1}"


def size_prompt(chars: int) -> str:
    filler = ("abcde " * (chars // 6 + 1))[: chars - len(SIZE_PROMPT_HEAD)]
    return SIZE_PROMPT_HEAD + filler


def all_prompts() -> tuple[str, ...]:
    return PROMPTS + tuple(size_prompt(n) for n in SIZES)


class ProbeFailure(HarnessError):
    pass


# -- output -------------------------------------------------------------------------------------


def setup_output() -> None:
    """Print UTF-8 whatever the console or the redirection is."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)  # absent on captured streams
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def sanitise_error(text: str) -> str:
    """The first line of a browser error without URLs, quoted strings or long tokens: those
    can carry page text, a tenant or a conversation id. What is left names the failed call."""
    first = text.splitlines()[0] if text else ""
    first = re.sub(r"[a-z][a-z0-9+.-]*://\S+", "<url>", first, flags=re.I)
    first = re.sub(r"\"[^\"]*\"|'[^']*'|`[^`]*`", "<quoted>", first)
    first = re.sub(r"\S{40,}", "<long>", first)
    return first[:160]


def say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def environment() -> dict[str, str]:
    return {
        "platform": f"{platform.platform(terse=True)} {platform.machine()}",
        "python": platform.python_version(),
    }


# -- where results may go (design D2) ------------------------------------------------------------


def ensure_unversionable(directory: Path) -> None:
    """Refuse a destination inside a Git work tree that is not ignored by it."""
    anchor = directory.resolve()
    while not anchor.exists():
        anchor = anchor.parent
    try:
        inside = subprocess.run(
            ["git", "-C", str(anchor), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return  # no Git on this machine: nothing can version the file
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return
    probe_file = directory.resolve().relative_to(anchor) / "probe-check.json"
    ignored = subprocess.run(
        ["git", "-C", str(anchor), "check-ignore", "-q", probe_file.as_posix()],
        capture_output=True,
    )
    if ignored.returncode != 0:
        raise ProbeFailure(
            f"{directory} is inside a Git work tree and not ignored: the measurement could be "
            "committed. Point HARNESS_DATA_DIR at an ignored or external directory"
        )


def write_json(directory: Path, name: str, data: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def latest(directory: Path, step: str) -> dict | None:
    files = sorted(directory.glob(f"probe-{step}-[0-9]*.json"))  # not login-state for login
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


# -- page helpers -------------------------------------------------------------------------------


def first_page(context: BrowserContext) -> Page:
    pages = [p for p in context.pages if not p.is_closed()]
    if not pages:
        raise ProbeFailure("the Edge window was closed")
    return pages[-1]


async def wait_ready(page: Page, locators: Locators, probe: Probe) -> None:
    composer = locators.composer.resolve(page).first
    copilot_host = probe.copilot_host
    deadline = time.monotonic() + probe.settings.copilot_ready_timeout_s
    while time.monotonic() < deadline:
        try:
            if host_of(page.url) == copilot_host and await composer.is_visible() and (
                await composer.is_enabled()
            ):
                if await signed_out_hints(page):
                    raise ProbeFailure(probe.guest_advice())  # a guest prompt box is not the chat
                return
        except PlaywrightError:
            if page.is_closed():
                raise ProbeFailure("the Edge window was closed") from None
        await asyncio.sleep(0.25)
    raise ProbeFailure(
        "the Copilot page was not ready in time (composer not visible). Signed out? Run "
        "`probe login` first; check `composer` in candidates.json"
    )


async def open_new_conversation(page: Page, locators: Locators) -> bool:
    try:
        await locators.new_conversation.resolve(page).first.click(timeout=5000)
        return True
    except PlaywrightError:
        return False


LENGTH_JS = (
    "el => (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' ? el.value : el.textContent)"
    ".replace(/[\\u200B-\\u200D\\u2060\\uFEFF]/g, '').length"
)  # zero-width characters do not count: a rich editor may keep some as cursor anchors (seen
#    on the real page: U+200B and U+200C after the text)


DIFF_JS = r"""
(el, expected) => {
  const got = el.tagName === "TEXTAREA" || el.tagName === "INPUT" ? el.value : el.textContent;
  const out = [];
  let i = 0, j = 0;
  while ((i < got.length || j < expected.length) && out.length < 6) {
    if (got[i] === expected[j]) { i += 1; j += 1; continue; }
    if (got[i + 1] === expected[j]) { out.push(["extra", i, got.codePointAt(i)]); i += 1; continue; }
    if (got[i] === expected[j + 1]) { out.push(["missing", j, expected.codePointAt(j)]); j += 1; continue; }
    out.push(["changed", i, got.codePointAt(i) ?? -1]); i += 1; j += 1;
  }
  return out;
}
"""


async def read_length(composer: Locator) -> int:
    """Characters in the editor: a field's value, else the text content, which (unlike the
    rendered text) gains no line breaks from the paragraphs of a rich editor."""
    return int(await composer.evaluate(LENGTH_JS))


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# -- one timed send -----------------------------------------------------------------------------


@dataclass
class Sample:
    t_ms: float
    turn: bool
    digest: str | None
    content_digest: str | None
    has_text: bool
    has_marker: bool
    stop_visible: bool | None
    send_ready: bool
    done: bool | None
    busy: str | None
    new_path: bool = False  # the address changed since the prompt was sent (id assigned)
    resubmitted: bool = False  # set on the last sample: the first key press was lost
    confirmed: bool = False  # set on the last sample: the prompt left the editor


async def sample_send(
    page: Page, locators: Locators, prompt: str, marker: str, *, filled: bool = False
) -> list[Sample]:
    """Send one prompt and sample the page every SAMPLE_INTERVAL_S until it settles.

    Only hashes, lengths and booleans are kept; the text itself is never stored.
    """
    assistant = locators.assistant_turn.resolve(page)
    composer = locators.composer.resolve(page).first
    send = locators.send.resolve(page).first if locators.send else None
    stop = locators.stop.resolve(page).first if locators.stop else None
    region = locators.busy_region.resolve(page) if locators.busy_region else None
    users = locators.user_turn.resolve(page)
    before = await assistant.count()
    users_before = await users.count()
    path_before = urlsplit(page.url).path
    expected = len(prompt) if not filled else await read_length(composer)
    if not filled:
        await composer.fill(prompt)
        if await read_length(composer) != expected:  # the page reset the editor: once more
            await composer.fill(prompt)
    started = time.monotonic()
    await submit(composer, send, locators)
    samples: list[Sample] = []
    resubmitted = confirmed = False
    while True:
        t_ms = (time.monotonic() - started) * 1000
        if not confirmed:
            confirmed = await users.count() > users_before or await read_length(composer) == 0
            if not confirmed and not resubmitted and t_ms >= RESUBMIT_AFTER_MS:
                # Nothing left the editor and no turn was added: the key press was lost (the
                # page was still rendering). Pressing again cannot send the prompt twice.
                if await read_length(composer) == expected:
                    resubmitted = True
                    started, samples = time.monotonic(), []
                    await submit(composer, send, locators)
                    continue
        turn = digest = content_digest = busy = done = None
        text = ""
        if await assistant.count() > before:
            turn = assistant.nth(before)
            text = await turn.inner_text()  # read first: a signal seen after it is not early
            digest = text_hash(text)
            content_digest = text_hash(content_up_to(text, marker))
            busy = await turn.get_attribute("aria-busy") if region is None else None
            if locators.response_done_control:
                done = await locators.response_done_control.resolve(turn).count() > 0
        samples.append(
            Sample(
                t_ms=t_ms,
                turn=turn is not None,
                digest=digest,
                content_digest=content_digest,
                has_text=bool(text.strip()),
                has_marker=marker in text,
                stop_visible=await stop.is_visible() if stop else None,
                send_ready=(send is None or await send.is_visible()) and await composer.is_editable(),
                done=done,
                busy=busy if region is None else await region_busy(region),
                new_path=urlsplit(page.url).path != path_before,
            )
        )
        if settled(samples, locators) or t_ms > SEND_DEADLINE_S * 1000:
            if samples:
                samples[-1].resubmitted = resubmitted
                samples[-1].confirmed = confirmed
            return samples
        await asyncio.sleep(SAMPLE_INTERVAL_S)


async def submit(composer: Locator, send: Locator | None, locators: Locators) -> None:
    if locators.send_with == "enter":
        await composer.press("Enter")
    else:
        assert send is not None  # the schema requires it for button sends
        await send.click()


async def region_busy(region: Locator) -> str | None:
    if await region.count() == 0:
        return None
    return await region.last.get_attribute("aria-busy")


def content_up_to(text: str, marker: str) -> str:
    """The reply up to and including the requested marker. What follows the marker is page
    decoration (a copy button's label, for instance) that may appear with the end signal."""
    end = text.rfind(marker)
    return text if end < 0 else text[: end + len(marker)]


def stable_since(samples: list[Sample], key: str = "digest") -> float:
    last = samples[-1]
    since = last.t_ms
    for sample in reversed(samples):
        if getattr(sample, key) != getattr(last, key):
            break
        since = sample.t_ms
    return since


def settled(samples: list[Sample], locators: Locators) -> bool:
    last = samples[-1]
    if not last.has_marker:
        return False
    stable_for = last.t_ms - stable_since(samples)
    if stable_for < max(STABLE_WINDOWS_MS):
        return False
    fired = fire_times(samples, locators)
    pending = [name for name in STRUCTURAL if applicable(name, locators) and fired[name] is None]
    return not pending or stable_for >= max(STABLE_WINDOWS_MS) + SETTLE_MS


def applicable(signal: str, locators: Locators) -> bool:
    if signal == "stop_hidden":
        return locators.stop is not None
    if signal == "done_control":
        return locators.response_done_control is not None
    return True


def fire_times(samples: list[Sample], locators: Locators) -> dict[str, float | None]:
    """When each candidate end-of-response signal was first met."""
    fired: dict[str, float | None] = {}

    def after_seen(seen: Callable[[Sample], bool], met: Callable[[Sample], bool]) -> float | None:
        was_seen = False
        for s in samples:
            if seen(s):
                was_seen = True
            elif was_seen and met(s):
                return s.t_ms
        return None

    fired["stop_hidden"] = (
        after_seen(lambda s: bool(s.stop_visible), lambda s: s.stop_visible is False)
        if locators.stop
        else None
    )
    fired["send_ready"] = after_seen(lambda s: not s.send_ready, lambda s: s.send_ready)
    fired["done_control"] = next((s.t_ms for s in samples if s.done), None)
    fired["aria_busy"] = after_seen(lambda s: s.busy == "true", lambda s: s.turn and s.busy != "true")
    for window in STABLE_WINDOWS_MS:
        fired[f"text_stable_{window}"] = None
        run_start, previous = 0.0, object()
        for s in samples:
            if s.digest != previous:
                run_start, previous = s.t_ms, s.digest
            if s.has_text and s.t_ms - run_start >= window:
                fired[f"text_stable_{window}"] = s.t_ms
                break
    return fired


def analyse(samples: list[Sample], locators: Locators) -> dict:
    """Compare each signal with the truth: the reply holds its marker and, up to the marker,
    stops changing. A signal met before that instant is early."""
    last = samples[-1] if samples else None
    truth = stable_since(samples, "content_digest") if last and last.has_marker else None
    signals = {}
    for name, fired in fire_times(samples, locators).items():
        signals[name] = {
            "met": fired is not None and truth is not None,
            "early": fired is not None and truth is not None and fired < truth,
            "delay_ms": round(fired - truth) if fired is not None and truth is not None else None,
        }
    path_at = next((s.t_ms for s in samples if s.new_path), None)
    text_at = next((s.t_ms for s in samples if s.has_text), None)
    return {
        "truth_ms": round(truth) if truth is not None else None,
        "signals": signals,
        "id_in_url_ms": round(path_at) if path_at is not None else None,
        "resubmitted": bool(last and last.resubmitted),
        "sent_confirmed": bool(last and last.confirmed),
        "first_text_ms": round(text_at) if text_at is not None else None,
    }


def signal_names() -> list[str]:
    return [*STRUCTURAL, *(f"text_stable_{w}" for w in STABLE_WINDOWS_MS)]


def summarise_signals(sends: list[dict], planned: int) -> dict:
    summary = {}
    for name in signal_names():
        results = [send["signals"][name] for send in sends]
        delays = [r["delay_ms"] for r in results if r["met"] and not r["early"]]
        met = sum(r["met"] for r in results)
        early = sum(r["early"] for r in results)
        summary[name] = {
            "met": met,
            "early": early,
            "sends": len(results),
            "valid": len(results) == planned and met == planned and early == 0,
            "mean_delay_ms": round(statistics.fmean(delays)) if delays else None,
        }
    return summary


def choose_signal(summary: dict) -> tuple[EndSignal | None, int | None]:
    windows = [w for w in STABLE_WINDOWS_MS if summary[f"text_stable_{w}"]["valid"]]
    stability = min(windows) if windows else None
    structural = [n for n in STRUCTURAL if summary[n]["valid"]]
    if structural:
        best = min(structural, key=lambda n: summary[n]["mean_delay_ms"] or 0)
        return EndSignal(name=best), stability
    if stability is not None:
        return EndSignal(name="text_stable", window_ms=stability), stability
    return None, None


# -- conversation reference (design D6) ----------------------------------------------------------


PLAIN_WORD = re.compile(r"[a-z][a-z-]{0,30}")


def _segments(url: str) -> list[str]:
    return urlsplit(url).path.split("/")[1:]


def locate_reference(before: list[str], after: list[str]) -> ConversationRef | None:
    """Where the conversation identifier sits: a URL place that holds an id-like value after
    the first send, distinct across conversations, absent before. Never stores the values."""
    if not after:
        return None
    segment_counts = {len(_segments(url)) for url in after}
    for index in range(min(segment_counts)):
        values = [_segments(url)[index] for url in after]
        prior = {(_segments(url) + [None] * (index + 1))[index] for url in before}
        if all(ID_LIKE.fullmatch(v) for v in values) and len(set(values)) == len(values) and not (
            prior & set(values)
        ):
            return ConversationRef(kind="path_segment", index=index, prefix=fixed_prefix(after, index))
    params = set.intersection(*(set(dict(parse_qsl(urlsplit(u).query))) for u in after))
    for name in sorted(params):
        values = [dict(parse_qsl(urlsplit(u).query))[name] for u in after]
        prior = {dict(parse_qsl(urlsplit(u).query)).get(name) for u in before}
        if all(ID_LIKE.fullmatch(v) for v in values) and len(set(values)) == len(values) and not (
            prior & set(values)
        ):
            return ConversationRef(kind="query_param", param=name)
    return None


def fixed_prefix(urls: list[str], index: int) -> list[str] | None:
    """The path segments before the identifier when every URL shares them and they are plain
    words (`chat`, `conversation`); None otherwise. Never an identifier."""
    prefixes = {tuple(_segments(url)[:index]) for url in urls}
    if len(prefixes) != 1:
        return None
    prefix = list(prefixes.pop())
    return prefix if all(PLAIN_WORD.fullmatch(part) for part in prefix) else None


def extract_reference(url: str, ref: ConversationRef) -> str | None:
    return ref.identifier_in(url)


# -- steps --------------------------------------------------------------------------------------


@dataclass
class Probe:
    settings: Settings
    url: str
    out_dir: Path

    @property
    def copilot_host(self) -> str:
        return host_of(self.url)

    def launcher(self, profile: Path | None = None) -> EdgeLauncher:
        if profile is None:
            return EdgeLauncher.from_settings(self.settings)
        return EdgeLauncher(self.settings.data_dir, profile, headless=self.settings.browser_headless)

    def overrides(self) -> dict:
        """Locators written by hand in candidates.json: all of them, or only the ones that
        discovery could not find. They win over discovered ones."""
        path = self.out_dir / CANDIDATES_FILE
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProbeFailure(f"{CANDIDATES_FILE} is not valid JSON (line {exc.lineno})") from None
        if not isinstance(data, dict):
            raise ProbeFailure(f"{CANDIDATES_FILE} must hold a JSON object")
        return data

    def discovered(self) -> dict:
        path = self.out_dir / DISCOVERED_FILE
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8")).get("locators", {})

    def guest_advice(self) -> str:
        """What to say when the configured address shows Copilot's guest page. The chat path
        comes from the probe's last login step, else from the last `copilot login`."""
        login = latest(self.out_dir, "login") or {}
        chat_path = login.get("ready_path") or recorded_ready_path(self.settings.data_dir)
        return (f"{ASK['signed_in']}. If this profile is already signed in: "
                + guest_page_advice(self.url, chat_path))

    def locators(self) -> tuple[Locators | None, list[str]]:
        """Discovered locators with the hand-written ones on top, and what is still missing."""
        return merge_locators(self.discovered(), self.overrides())


def merge_locators(discovered: dict, overrides: dict) -> tuple[Locators | None, list[str]]:
    data = discovered | overrides
    missing = [name for name in REQUIRED_LOCATORS if name not in data]
    if data.get("send_with", "button") == "button" and "send" not in data:
        missing.append("send")
    if missing:
        return None, missing
    try:
        return Locators.model_validate(data), []
    except ValidationError as exc:
        names = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})
        raise ProbeFailure(
            f"{CANDIDATES_FILE}: invalid locator(s): {', '.join(names) or 'unknown'}"
        ) from None


def ask_for(missing: list[str], out_dir: Path) -> str:
    """One line per missing control: what to record and where to put it."""
    lines = [f"discovery could not find: {', '.join(missing)}. For each, record it with codegen "
             f"and put only that entry in {out_dir / CANDIDATES_FILE} (runbook, appendix):"]
    lines += [f"  {name}: {ASK.get(name, name)}" for name in missing]
    return "\n".join(lines)


async def wait_for_person(context: BrowserContext) -> bool:
    """True when the person pressed Enter, False when every window was closed."""
    loop = asyncio.get_running_loop()
    pressed = loop.create_future()

    def read() -> None:
        sys.stdin.readline()  # the content is ignored: it is never a prompt
        loop.call_soon_threadsafe(lambda: pressed.done() or pressed.set_result(True))

    threading.Thread(target=read, daemon=True).start()
    while not pressed.done():
        pages = [p for p in context.pages if not p.is_closed()]
        if not pages:
            return False
        try:
            await pages[-1].locator("html").count()  # fails once the browser or driver is gone
        except PlaywrightError:
            return False
        await asyncio.sleep(0.25)
    return True


async def step_login(probe: Probe, result: dict) -> None:
    launcher = probe.launcher()
    result["controllable"] = None  # not measured until the page answered; Ctrl+C keeps it so
    started = time.monotonic()
    async with launcher.open() as context:
        result["edge_version"] = edge_version(context)
        result["launch_ms"] = round((time.monotonic() - started) * 1000)
        page = first_page(context)
        loaded = time.monotonic()
        try:
            await page.goto(probe.url, wait_until="load")
            result["first_load_ms"] = round((time.monotonic() - loaded) * 1000)
        except PlaywrightError:
            result["first_load_ms"] = None
        result["controllable"] = await page.locator("body").count() == 1
        say("Edge is open with the dedicated profile. Sign in by hand (password, MFA).")
        say("When you see Copilot ready to chat, come back here and press Enter.")
        result["confirmed_by_person"] = await wait_for_person(context)
        if result["confirmed_by_person"]:
            await describe_ready_page(context, probe, result)


async def describe_ready_page(context: BrowserContext, probe: Probe, result: dict) -> None:
    """Where the person saw Copilot ready: same host as the configured URL or not, how deep
    the path is and whether the page still offers to sign in. The host is kept only in the
    data directory; the summary says yes or no."""
    pages = [p for p in context.pages if not p.is_closed()]
    if not pages:
        return
    page = pages[-1]
    try:
        result["ready_host"] = host_of(page.url)
        result["ready_on_configured_host"] = result["ready_host"] == probe.copilot_host
        result["ready_path_segments"] = len([s for s in _segments(page.url) if s])
        result["ready_path"] = ready_path(page.url)  # `/chat`-like shape, or None: never an id
        result["ready_signed_out_hints"] = await signed_out_hints(page)
    except PlaywrightError:
        pass


async def step_discover(probe: Probe, result: dict) -> None:
    """Find the controls by behaviour with two fixed sends. Writes discovered.json."""
    started = time.monotonic()
    async with probe.launcher().open() as context:
        result.setdefault("edge_version", edge_version(context))
        page = first_page(context)
        await page.goto(probe.url)
        timeout = probe.settings.copilot_ready_timeout_s
        if not await settle_page(page, probe.copilot_host, timeout):
            result["discovery"] = {"stopped": "not on the Copilot host (sign-in page?)"}
            raise ProbeFailure("the Copilot page did not open (signed out?): run `probe login`")
        result["startup_ms"] = [round((time.monotonic() - started) * 1000)]
        timing = Timing(
            stable_ms=max(STABLE_WINDOWS_MS), settle_ms=SETTLE_MS, deadline_s=SEND_DEADLINE_S
        )
        found = await discover(
            page, (PROMPTS[0], PROMPTS[1]), (marker_of(0), marker_of(1)), timing, locate_reference
        )
    result["discovery"] = found.facts | {"missing": found.missing}
    if "signed_in" in found.missing:
        raise ProbeFailure(probe.guest_advice())  # nothing typed, nothing saved
    if found.structure:
        name = f"discovery-structure-{stamp()}.txt"
        probe.out_dir.mkdir(parents=True, exist_ok=True)
        (probe.out_dir / name).write_text("\n".join(found.structure) + "\n", encoding="utf-8")
        result["discovery"]["structure_file"] = name
    write_json(probe.out_dir, DISCOVERED_FILE, {
        "measured_at": now_iso(),
        "locators": found.locators,
        "facts": found.facts,
        "missing": found.missing,
    })


async def measure_locators(probe: Probe, result: dict) -> Locators:
    """The locators to measure with: hand-written and earlier discovered ones if they are
    complete. Discovery (two sends) runs first only when it never ran: after a discovery that
    left gaps, the probe asks for those items instead of sending again (`discover` reruns it)."""
    locators, missing = probe.locators()
    if locators is None and not (probe.out_dir / DISCOVERED_FILE).is_file():
        say("finding the Copilot controls (two fixed sends)")
        await step_discover(probe, result)
        locators, missing = probe.locators()
    if locators is None:
        result["missing_locators"] = missing
        raise ProbeFailure(ask_for(missing, probe.out_dir))
    return locators


async def step_measure(probe: Probe, result: dict) -> None:
    locators = await measure_locators(probe, result)
    timeout = probe.settings.copilot_ready_timeout_s
    result["locators"] = locators.model_dump(mode="json", exclude_none=True)
    result["startup_ms"] = []  # discovery's own start-up is not part of the measurement
    result["sends_planned"] = CONVERSATIONS * len(PROMPTS)
    result["turns_sent_per_conversation"] = len(PROMPTS)
    sends, startups, before, after = result["sends"], result["startup_ms"], [], []
    conversations: list[str] = []  # full URLs, in memory only: never written

    for number in range(CONVERSATIONS):
        say(f"conversation {number + 1}/{CONVERSATIONS}: opening Edge")
        started = time.monotonic()
        async with probe.launcher().open() as context:
            result.setdefault("edge_version", edge_version(context))
            page = first_page(context)
            await page.goto(probe.url)
            await wait_ready(page, locators, probe)
            startups.append(round((time.monotonic() - started) * 1000))
            if await open_new_conversation(page, locators):
                await settle_page(page, probe.copilot_host, probe.settings.copilot_ready_timeout_s)
                await wait_ready(page, locators, probe)
            before.append(page.url)
            for index, prompt in enumerate(PROMPTS):
                say(f"  send {index + 1}/{len(PROMPTS)}")
                samples = await sample_send(page, locators, prompt, marker_of(index))
                sends.append({"conversation": number + 1, "prompt": index + 1}
                             | analyse(samples, locators))
            after.append(page.url)
            conversations.append(page.url)

    ref = locate_reference(before, after)
    result["conversation_ref"] = ref.model_dump(mode="json", exclude_none=True) if ref else None
    reopened, visible = [], result["turns_visible_after_reopen"]
    built = 0
    for number, url in enumerate(conversations):
        say(f"reopening conversation {number + 1}/{len(conversations)} in a new Edge")
        # Reopen as the provider will: configured scheme and host + measured fixed segments
        # + the identifier alone. Only when the shape cannot build an address, the URL itself.
        identifier = extract_reference(url, ref) if ref else None
        target = ref.url_for(probe.url, identifier) if ref and identifier else None
        built += target is not None
        started = time.monotonic()
        async with probe.launcher().open() as context:
            page = first_page(context)
            await page.goto(target or url)
            await wait_ready(page, locators, probe)
            startups.append(round((time.monotonic() - started) * 1000))
            visible.append(await settled_count(locators.user_turn.resolve(page), len(PROMPTS)))
            same = ref is not None and extract_reference(page.url, ref) == extract_reference(url, ref)
            reopened.append(same and visible[-1] > 0)
    result["identity_recoverable"] = bool(reopened) and all(reopened) and ref is not None
    result["reopened_from_identifier"] = built

    startups.append(await measure_sizes(probe, locators, result))


async def measure_sizes(probe: Probe, locators: Locators, result: dict) -> int:
    """P6 in a new conversation: the largest synthetic prompt the editor holds whole and the
    reply acknowledges. Stops at the first size that fails. Returns the start-up time."""
    say("prompt sizes: opening Edge")
    started = time.monotonic()
    async with probe.launcher().open() as context:
        result.setdefault("edge_version", edge_version(context))
        page = first_page(context)
        await page.goto(probe.url)
        await wait_ready(page, locators, probe)
        startup = round((time.monotonic() - started) * 1000)
        if await open_new_conversation(page, locators):
            await settle_page(page, probe.copilot_host, probe.settings.copilot_ready_timeout_s)
            await wait_ready(page, locators, probe)
        composer = locators.composer.resolve(page).first
        for chars in SIZES:
            say(f"  size {chars}")
            await composer.fill(size_prompt(chars))
            in_editor = await read_length(composer)
            entry = {"chars": chars, "editor_chars": in_editor, "accepted": False}
            result["sizes"].append(entry)
            if in_editor != chars:
                # where the editor's copy of our own synthetic prompt differs: positions and
                # code points only, never text
                entry["differences"] = await composer.evaluate(DIFF_JS, size_prompt(chars))
                await composer.fill("")
                break
            samples = await sample_send(page, locators, "", SIZE_MARKER, filled=True)
            entry["accepted"] = samples[-1].has_marker
            if not entry["accepted"]:
                break
    return startup


def max_accepted(sizes: list[dict]) -> int | None:
    accepted = []
    for entry in sizes:
        if not entry["accepted"]:
            break
        accepted.append(entry["chars"])
    return max(accepted) if accepted else None


async def step_sizes(probe: Probe, result: dict) -> None:
    """Only P6, with the locators already measured: for when `measure` left it unmeasured,
    without repeating the 12 timed sends."""
    locators, missing = probe.locators()
    if locators is None:
        raise ProbeFailure(f"no locators for: {', '.join(missing)}; run `probe measure` first")
    result["sizes"] = []
    await measure_sizes(probe, locators, result)


async def settled_count(locator: Locator, expected: int) -> int:
    deadline = time.monotonic() + TURNS_SETTLE_S
    count = await locator.count()
    while count < expected and time.monotonic() < deadline:
        await asyncio.sleep(0.25)
        count = await locator.count()
    return count


async def step_login_state(probe: Probe, result: dict) -> None:
    locators, missing = probe.locators()
    if locators is None:
        raise ProbeFailure(f"no locators for: {', '.join(missing)}; run `probe measure` first")
    hosts: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ai-harness-login-state-") as tmp:
        async with probe.launcher(Path(tmp) / "profile").open() as context:
            result["edge_version"] = edge_version(context)
            page = first_page(context)

            def navigated(frame) -> None:
                host = host_of(frame.url)
                if frame == page.main_frame and host and host not in hosts:
                    hosts.append(host)

            page.on("framenavigated", navigated)
            try:
                await page.goto(probe.url)
            except PlaywrightError:
                pass
            result["state"] = await classify_empty_profile(
                page, locators, probe.copilot_host, probe.settings.copilot_ready_timeout_s
            )
    result["login_hosts"] = [h for h in hosts if h != probe.copilot_host]
    result["indicator_seen"] = result["state"] == "login_indicator"


async def classify_empty_profile(
    page: Page, locators: Locators, copilot_host: str, timeout_s: float
) -> str:
    deadline = time.monotonic() + timeout_s
    composer = locators.composer.resolve(page).first
    indicator = locators.login_indicator.resolve(page).first if locators.login_indicator else None
    other_host_since: float | None = None
    while time.monotonic() < deadline:
        try:
            host = host_of(page.url)
            if host == copilot_host and await composer.is_visible():
                return "ready"
            if indicator is not None and await indicator.is_visible():
                return "login_indicator"
            if host and host != copilot_host:
                other_host_since = other_host_since or time.monotonic()
                if time.monotonic() - other_host_since >= LOGIN_HOST_SETTLE_S:
                    return "login_host"
            else:
                other_host_since = None
        except PlaywrightError:
            if page.is_closed():
                return "closed"
        await asyncio.sleep(0.25)
    return "unknown"


COUNT_JS = r"""
() => {
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none"; };
  const all = (sel) => [...document.querySelectorAll(sel)].filter(visible).length;
  let shadows = 0;
  for (const el of document.querySelectorAll("*")) if (el.shadowRoot) shadows += 1;
  return {
    editables: all('textarea, [contenteditable="true"], [contenteditable=""], [contenteditable="plaintext-only"], [role="textbox"]'),
    buttons: all('button, [role="button"]'),
    dialogs: all('dialog[open], [role="dialog"], [role="alertdialog"]'),
    iframes: all("iframe"),
    shadow_roots: shadows,
  };
}
"""


async def settle_page(page: Page, copilot_host: str, timeout_s: float) -> bool:
    """Wait until the page is on the Copilot host and its element count stops changing."""
    deadline = time.monotonic() + timeout_s
    last, same_since = -1, time.monotonic()
    while time.monotonic() < deadline:
        try:
            count = await page.locator("*").count()
        except PlaywrightError:
            count = -1
        if count != last:
            last, same_since = count, time.monotonic()
        elif host_of(page.url) == copilot_host and time.monotonic() - same_since >= 2.0:
            return True
        await asyncio.sleep(0.25)
    return host_of(page.url) == copilot_host


async def step_structure(probe: Probe, result: dict) -> None:
    """Sanitised structure of the Copilot page as it opens. Sends nothing."""
    started = time.monotonic()
    async with probe.launcher().open() as context:
        result["edge_version"] = edge_version(context)
        page = first_page(context)
        await page.goto(probe.url)
        on_copilot = await settle_page(page, probe.copilot_host, probe.settings.copilot_ready_timeout_s)
        result["startup_ms"] = round((time.monotonic() - started) * 1000)
        result["on_copilot_host"] = on_copilot
        if not on_copilot:
            result["stopped"] = "not on the Copilot host (sign-in page?)"
            return
        result["counts"] = await page.evaluate(COUNT_JS)
        result["signed_out_hints"] = await signed_out_hints(page)
        if result["signed_out_hints"]:
            say(probe.guest_advice())
        result["path_segments"] = len([p for p in _segments(page.url) if p])
        lines = await structure_dump(page)
    name = f"structure-{stamp()}.txt"
    probe.out_dir.mkdir(parents=True, exist_ok=True)
    (probe.out_dir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    result["structure_file"] = name
    result["structure_lines"] = len(lines)


# -- results ------------------------------------------------------------------------------------


def finish_measure(result: dict) -> None:
    planned = result.get("sends_planned") or CONVERSATIONS * len(PROMPTS)
    summary = summarise_signals(result["sends"], planned)
    result["signals"] = summary
    signal, stability = choose_signal(summary)
    result["end_signal"] = signal.model_dump(mode="json", exclude_none=True) if signal else None
    result["stability_window_ms"] = stability
    truths = [s["truth_ms"] for s in result["sends"] if s["truth_ms"] is not None]
    result["longest_response_ms"] = max(truths) if truths else None
    result["max_prompt_chars"] = max_accepted(result["sizes"])
    if result["startup_ms"] and result["longest_response_ms"]:
        seconds = max(result["startup_ms"]) / 1000 + 2 * result["longest_response_ms"] / 1000
        result["recommended_timeout_s"] = math.ceil(seconds)
    else:
        result["recommended_timeout_s"] = None
    missing = []
    if len(result["sends"]) < planned:
        missing.append("sends")
    if signal is None:
        missing.append("end_signal")
    if stability is None:
        missing.append("stability_window_ms")
    if result.get("conversation_ref") is None:
        missing.append("conversation_ref")
    if result.get("identity_recoverable") is None or len(result["turns_visible_after_reopen"]) < CONVERSATIONS:
        missing.append("identity_recoverable")
    if result["max_prompt_chars"] is None:
        missing.append("max_prompt_chars")
    result["missing"] = missing
    result["complete"] = not missing


def finish_login_state(result: dict) -> None:
    measured = result.get("state") in ("login_host", "login_indicator") and (
        result.get("login_hosts") or result.get("indicator_seen")
    )
    result["missing"] = [] if measured else ["login"]
    result["complete"] = bool(measured)


def assemble(out_dir: Path) -> tuple[UiMeasurement | None, str]:
    """Build `ui.json` from the latest measure and login-state results; write it if complete."""
    measure, login_state = latest(out_dir, "measure"), latest(out_dir, "login-state")
    if measure is None or "locators" not in measure:
        return None, "no measure result yet"
    sizes = latest(out_dir, "sizes")
    max_chars = measure.get("max_prompt_chars")
    if max_chars is None and sizes and sizes.get("complete"):
        max_chars = sizes.get("max_prompt_chars")  # measured alone, with the same locators
    login = None
    if login_state and login_state.get("complete"):
        login = LoginShape(
            hosts=tuple(login_state.get("login_hosts") or ()),
            indicator_seen=bool(login_state.get("indicator_seen")),
        )
    data = {
        "schema_version": SCHEMA_VERSION,
        "complete": False,
        "missing": [p for p in measure.get("missing", []) if p == "sends"],
        "measured_at": measure["measured_at"],
        "edge_version": measure.get("edge_version"),
        "platform": measure.get("platform"),
        "locators": measure["locators"],
        "conversation_ref": measure.get("conversation_ref"),
        "identity_recoverable": measure.get("identity_recoverable"),
        "turns_visible_after_reopen": measure.get("turns_visible_after_reopen", []),
        "turns_sent_per_conversation": measure.get("turns_sent_per_conversation"),
        "end_signal": measure.get("end_signal"),
        "stability_window_ms": measure.get("stability_window_ms"),
        "max_prompt_chars": max_chars,
        "startup_ms": measure.get("startup_ms", []),
        "longest_response_ms": measure.get("longest_response_ms"),
        "recommended_timeout_s": measure.get("recommended_timeout_s"),
        "login": login.model_dump(mode="json") if login else None,
    }
    draft = UiMeasurement.model_validate(data)
    missing = draft.missing_parts()
    if missing:
        return draft, f"not written: missing {', '.join(missing)}"
    final = UiMeasurement.model_validate(data | {"complete": True, "missing": []})
    target = out_dir / MEASUREMENT_FILE
    if target.exists():
        dated = datetime.fromtimestamp(target.stat().st_mtime, UTC).strftime("%Y%m%dT%H%M%SZ")
        target.replace(out_dir / f"ui-{dated}.json")
    write_json(out_dir, MEASUREMENT_FILE, final.model_dump(mode="json"))
    return final, "written"


# -- summary: the only thing to paste back -------------------------------------------------------


def discovery_lines(d: dict) -> list[str]:
    """Discovery facts: methods, booleans, counts and kinds of locator, never a selector."""
    if "stopped" in d:
        return [f"discovery: stopped ({d['stopped']})"]
    ref = d.get("conversation_ref")
    shape = f"{ref['kind']} {ref.get('index', ref.get('param'))}" if ref else "none"
    kinds = d.get("locator_kinds") or {}
    return [
        f"discovery: sends {d.get('sends')}  send_with: {d.get('send_with')}  "
        f"send button: {yes_no(d.get('send_button_found'))}  "
        f"editor: {d.get('editor_kind')}{' with paragraph' if d.get('editor_has_paragraph') else ''}"
        f" (visible editors {d.get('editors_visible')})",
        f"  user echo: {yes_no(d.get('user_echo_found'))}  user turn level: "
        f"{d.get('user_turn_level')}  assistant turn level: {d.get('assistant_turn_level')}  "
        f"echo_ms: {d.get('echo_ms')}  answer_seen_ms: {d.get('answer_seen_ms')}",
        f"  end candidates: stop {yes_no(d.get('stop_found'))}, done control "
        f"{yes_no(d.get('done_control_found'))}, aria-busy {yes_no(d.get('busy_found'))}  "
        f"controls appeared: {d.get('controls_appeared')}",
        f"  new conversation: candidates {d.get('new_chat_candidates')}, verified "
        f"{yes_no(d.get('new_chat_verified'))}  conversation ref: {shape}",
        "  locator kinds: " + (", ".join(f"{k} {v}" for k, v in kinds.items()) or "none"),
        f"  user hits per send: {d.get('user_hits')}  user levels: {d.get('user_levels')}  "
        f"matches per level after send two: {d.get('user_level_counts')}",
        f"  new conversation tried: {d.get('new_chat_tried')}",
        f"  conversation id in URL after send: {d.get('id_in_url_after_send_ms')} ms  "
        f"reply start (stop shown): {d.get('reply_start_after_send_ms')} ms  "
        f"reply end: {d.get('reply_end_after_send_ms')} ms",
        f"  missing: {', '.join(d.get('missing') or []) or 'nothing'}",
    ]


def size_line(result: dict) -> str:
    def one(entry: dict) -> str:
        if entry["accepted"]:
            return f"{entry['chars']}:ok"
        if entry["editor_chars"] != entry["chars"]:
            return f"{entry['chars']}:editor {entry['editor_chars']}"
        return f"{entry['chars']}:no reply"

    sizes = ", ".join(one(entry) for entry in result.get("sizes", []))
    return f"P6 prompt sizes: {sizes or 'none'}  max accepted: {result.get('max_prompt_chars')}"


def yes_no(value: bool | None) -> str:
    return "not measured" if value is None else ("yes" if value else "no")


def print_summary(step: str, result: dict, ui_status: str | None) -> None:
    lines = [
        "",
        "---- copilot probe summary (paste only this) ----",
        f"step: {step}  complete: {'yes' if result.get('complete') else 'no'}"
        + (f"  missing: {', '.join(result['missing'])}" if result.get("missing") else "")
        + ("  INTERRUPTED" if result.get("interrupted") else "")
        + (f"  error: {result['error']}" if result.get("error") else ""),
        f"edge: {result.get('edge_version') or '?'}  platform: {result['platform']}  "
        f"python: {result['python']}",
    ]
    if step == "login":
        lines.append(
            f"P1 controllable: {yes_no(result.get('controllable'))}  "
            f"launch_ms: {result.get('launch_ms')}  first_load_ms: {result.get('first_load_ms')}  "
            f"confirmed_by_person: {result.get('confirmed_by_person')}"
        )
        if "ready_on_configured_host" in result:
            lines.append(
                f"ready page: on configured host {yes_no(result['ready_on_configured_host'])}  "
                f"path segments {result.get('ready_path_segments')}  "
                f"ready path {result.get('ready_path') or 'not a plain word'}  "
                f"signed-out hints {result.get('ready_signed_out_hints')}"
            )
    if result.get("discovery"):
        lines += discovery_lines(result["discovery"])
    if result.get("missing_locators"):
        lines.append(f"locators missing: {', '.join(result['missing_locators'])}")
    if step == "measure":
        lines.append(f"sends measured: {len(result['sends'])}/{result.get('sends_planned')}  "
                     f"key press lost and repeated: {sum(1 for s in result['sends'] if s.get('resubmitted'))}  "
                     f"never left the editor: {sum(1 for s in result['sends'] if not s.get('sent_confirmed', True))}")
        for name, s in (result.get("signals") or {}).items():
            lines.append(
                f"  {name}: {'VALID' if s['valid'] else 'not valid'} "
                f"(met {s['met']}/{s['sends']}, early {s['early']}, mean delay {s['mean_delay_ms']} ms)"
            )
        lines.append(f"P4 chosen end signal: {result.get('end_signal')}  "
                     f"stability window: {result.get('stability_window_ms')} ms")
        ref = result.get("conversation_ref")
        lines.append(f"P2 reference in URL: {'yes (' + ref['kind'] + ')' if ref else 'no'}  "
                     f"identity recoverable: {result.get('identity_recoverable')}  "
                     f"reopened from the id alone: {result.get('reopened_from_identifier')}"
                     f"/{len(result.get('turns_visible_after_reopen') or [])}")
        firsts = [s for s in result["sends"] if s.get("prompt") == 1]
        lines.append(
            "P2 id in URL after first send (ms): "
            f"{[s.get('id_in_url_ms') for s in firsts]}  first reply text (ms): "
            f"{[s.get('first_text_ms') for s in firsts]}"
        )
        lines.append(f"P3 user turns visible after reopen: {result.get('turns_visible_after_reopen')} "
                     f"of {result.get('turns_sent_per_conversation')} sent")
        startups = result.get("startup_ms") or []
        if startups:
            lines.append(f"P7 start-up to composer ready: median {round(statistics.median(startups))} ms, "
                         f"max {max(startups)} ms (n={len(startups)})")
        lines.append(f"longest response: {result.get('longest_response_ms')} ms  "
                     f"recommended HARNESS_REQUEST_TIMEOUT_S: {result.get('recommended_timeout_s')}")
        lines.append(size_line(result))
    if step == "sizes":
        lines.append(size_line(result))
    if step == "login-state":
        lines.append(f"P5 empty profile ends as: {result.get('state')}  "
                     f"login hosts seen: {len(result.get('login_hosts') or [])}  "
                     f"indicator seen: {result.get('indicator_seen')}")
    if step == "structure":
        lines.append(f"signed-out hints: {result.get('signed_out_hints')}  "
                     f"on Copilot host: {yes_no(result.get('on_copilot_host'))}  "
                     f"startup_ms: {result.get('startup_ms')}  "
                     f"path segments: {result.get('path_segments')}  "
                     f"structure lines: {result.get('structure_lines')}")
        counts = result.get("counts") or {}
        lines.append("visible: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    if ui_status is not None:
        lines.append(f"ui.json: {ui_status}")
    lines.append("---- end of summary ----")
    print("\n".join(lines), flush=True)


# -- entry point --------------------------------------------------------------------------------

STEPS: dict[str, Callable] = {
    "login": step_login,
    "measure": step_measure,
    "login-state": step_login_state,
    "structure": step_structure,
    "discover": step_discover,
    "sizes": step_sizes,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="copilot_probe.py",
        description="Measure Copilot Web with fixed synthetic prompts. Accepts no prompt.",
    )
    steps = parser.add_subparsers(dest="step", required=True)
    steps.add_parser("login", help="open the dedicated profile and sign in by hand")
    steps.add_parser("measure", help="timed sends, reopening and prompt sizes")
    steps.add_parser("login-state", help="what an expired login looks like (empty profile)")
    steps.add_parser("structure", help="sanitised page structure, no text; sends nothing")
    steps.add_parser("discover", help="find the controls by behaviour (two fixed sends)")
    steps.add_parser("sizes", help="only the prompt sizes (P6), with the measured locators")
    return parser


def new_result(step: str) -> dict:
    result = {"step": step, "schema_version": SCHEMA_VERSION, "measured_at": now_iso()}
    result |= environment()
    if step == "measure":
        result |= {"sends": [], "startup_ms": [], "turns_visible_after_reopen": [], "sizes": []}
    return result


def main(argv: list[str] | None = None) -> int:
    setup_output()
    args = build_parser().parse_args(argv)  # anything extra is refused here, before a browser
    result = new_result(args.step)
    try:
        settings = Settings.from_env(os.environ)
        probe = Probe(settings, settings.require_copilot_url(), settings.data_dir / MEASUREMENT_DIR)
        ensure_unversionable(probe.out_dir)
    except HarnessError as exc:
        say(f"probe: error: {exc}")
        return EXIT_ERROR

    code = EXIT_OK
    try:
        run_browser(STEPS[args.step](probe, result))
    except KeyboardInterrupt:
        result["interrupted"] = True
        code = EXIT_INTERRUPTED
    except (HarnessError, MeasurementError) as exc:
        result["error"] = type(exc).__name__
        say(f"probe: error: {exc}")
        code = EXIT_ERROR
    except PlaywrightError as exc:
        result["error"] = type(exc).__name__
        say(f"probe: browser error: {sanitise_error(str(exc))}")
        code = EXIT_ERROR

    if args.step == "measure":
        finish_measure(result)
    elif args.step == "login-state":
        finish_login_state(result)
    elif args.step == "discover":
        missing = (result.get("discovery") or {}).get("missing")
        result["missing"] = list(missing) if missing is not None else ["discovery"]
        result["complete"] = not result["missing"]
        if result["missing"] and missing is not None and code == EXIT_OK:
            say(ask_for(result["missing"], probe.out_dir))
    elif args.step == "sizes":
        result["max_prompt_chars"] = max_accepted(result.get("sizes") or [])
        result["complete"] = result["max_prompt_chars"] is not None
        result["missing"] = [] if result["complete"] else ["max_prompt_chars"]
    elif args.step == "structure":
        result["complete"] = bool(result.get("structure_file"))
        result["missing"] = [] if result["complete"] else ["structure"]
    else:
        result["complete"] = result.get("controllable") is True and bool(result.get("confirmed_by_person"))
        result["missing"] = [] if result["complete"] else ["login"]
    write_json(probe.out_dir, f"probe-{args.step}-{stamp()}.json", result)
    ui_status = None
    if args.step in ("measure", "login-state", "sizes"):
        _, ui_status = assemble(probe.out_dir)
    print_summary(args.step, result, ui_status)
    if code == EXIT_OK and not result["complete"]:
        code = EXIT_ERROR
    return code


if __name__ == "__main__":
    sys.exit(main())
