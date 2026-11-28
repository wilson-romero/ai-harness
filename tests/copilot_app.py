"""Local server for the synthetic chat pages in `tests/fixtures/copilot_ui/`.

The server is the oracle: it counts the prompts it receives (the page posts each one) and the
key presses and clicks reported by the sign-in page, independently of the code under test.
The chat is served on the loopback address and the sign-in page on `localhost`, which the
browser treats as another host.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "copilot_ui"
CANARY_REPLY = "ZZ-CANARY-REPLY-9034"
CANARIES = (
    CANARY_REPLY,
    "ZZ-CANARY-ACCOUNT-3391",
    "ZZ-CANARY-ACCOUNT-3392",
    "ZZ-CANARY-TITLE-7783",
    "ZZ-CANARY-TITLE-7784",
    "ZZ-CANARY-PAGE-TITLE-6121",
    "ZZ-CANARY-TITLE-7781",
    "ZZ-CANARY-TITLE-7782",
    "ZZ-CANARY-PAGE-TITLE-6120",
    "ZZ-CANARY-ACCOUNT-3393",
    "ZZ-CANARY-TITLE-7785",
    "ZZ-CANARY-PAGE-TITLE-6123",
)
SESSION_COOKIE = "synthetic_session=ok"
MARKER = re.compile(r"ZQX-END-\d+")
# A prompt carrying ZQX-RICH-<name> gets the reply rendered as the HTML of
# `fixtures/copilot_ui/rich/<name>.html`, in the structure the real page renders Markdown.
RICH = re.compile(r"ZQX-RICH-([a-z]+)")
HUGE_REPLY_CHARS = 250_000


@dataclass
class Received:
    conversation: str
    prompt: str
    mode: str | None = None  # the mode the page was in when it sent it (response-mode)
    list_open: bool | None = None  # whether the list of modes was open when it sent it


@dataclass
class SyntheticCopilot:
    require_login: bool = False
    login_auto_ms: int | None = None
    login_with_editor: bool = False
    prompts: list[Received] = field(default_factory=list)
    login_events: list[str] = field(default_factory=list)
    page_hits: int = 0
    conversations: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    mode_events: list[str] = field(default_factory=list)  # every mode the page switched to
    # Whether each chat page load came from a browser without a window: its User-Agent says
    # `HeadlessChrome` (measured 2026-11-27, Edge 158 with Playwright's `--headless`).
    headless_hits: list[bool] = field(default_factory=list)
    # How a page served to a browser without a window behaves (change copilot-turn-speed):
    # None as any other; "login" sends it to sign in; "other" serves a page of another structure.
    headless_page: str | None = None

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self))
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    # -- lifecycle ------------------------------------------------------------------------

    def start(self) -> SyntheticCopilot:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    # -- addresses ------------------------------------------------------------------------

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def url(self, path: str = "/app", **params: str) -> str:
        query = f"?{urlencode(params)}" if params else ""
        return f"{self.base}{path}{query}"

    def login_url(self, return_to: str) -> str:
        complete = f"{self.base}/auth/complete?return={quote(return_to, safe='')}"
        params = {"complete": complete}
        if self.login_auto_ms is not None:
            params["auto_ms"] = str(self.login_auto_ms)
        if self.login_with_editor:
            params["editor"] = "1"
        return f"http://localhost:{self.port}/login?{urlencode(params)}"

    # -- state ----------------------------------------------------------------------------

    @property
    def prompt_count(self) -> int:
        with self._lock:
            return len(self.prompts)

    def receive(self, conversation: str | None, prompt: str,
                mode: str | None = None, list_open: bool | None = None) -> tuple[str, str]:
        with self._lock:
            if not conversation or conversation not in self.conversations:
                conversation = secrets.token_hex(8)
                self.conversations[conversation] = []
            self.prompts.append(Received(conversation, prompt, mode, list_open))
            reply = make_reply(prompt)
            self.conversations[conversation] += [
                {"role": "user", "text": prompt},
                {"role": "assistant", "text": reply, "html": rich_reply(prompt)},
            ]
            return conversation, reply

    def forget(self, conversation: str) -> None:
        """The conversation is deleted elsewhere (another device): it cannot be loaded again."""
        with self._lock:
            self.conversations.pop(conversation, None)

    def add_elsewhere(self, conversation: str, prompt: str) -> None:
        """A question and its answer added to a conversation from somewhere else. Not counted
        as a prompt the page sent."""
        with self._lock:
            self.conversations[conversation] += [
                {"role": "user", "text": prompt},
                {"role": "assistant", "text": make_reply(prompt), "html": ""},
            ]


LATE_BLOCK_END = "ZZ-LATE-BLOCK-END"


def late_block(chunks: int = 1) -> str:
    """The block app.html appends after the end with late_block_ms (late_chunks parts)."""
    return " ".join(["ZZ-LATE-BLOCK", *(f"late{k}" for k in range(1, chunks + 1)), LATE_BLOCK_END])


async def wait_until(condition, timeout_s: float = 60.0, what: str = "condition") -> None:
    """Poll a synchronous condition from async test code. The limit only bounds a failing
    test; a passing one returns as soon as the condition holds, so it is generous."""
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.05)


def rich_reply(prompt: str) -> str:
    match = RICH.search(prompt)
    return (FIXTURES / "rich" / f"{match.group(1)}.html").read_text(encoding="utf-8") if match else ""


def make_reply(prompt: str) -> str:
    words = " ".join(f"word{n}" for n in range(1, 13))
    parts = [CANARY_REPLY, "synthetic answer", words]
    if "LEN-OK" in prompt:
        parts.append("LEN-OK")
    if "ZQX-HOSTILE" in prompt:
        # Terminal escapes, a bidirectional override, zero-width and other control characters,
        # as a hostile page could render them.
        parts.append("\x1b[2J\x1b]0;ZZ-TITLE\x07 \u202eHOSTILE\u202c \u200bZW\u200b \x08\x00END")
    if "ZQX-HUGE" in prompt:
        parts.append("H" * HUGE_REPLY_CHARS)
    marker = MARKER.search(prompt)
    if marker:
        parts.append(marker.group(0))
    return " ".join(parts)


def _handler(app: SyntheticCopilot) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # keep test output clean

        def _send(self, status: int, body: bytes, kind: str, headers: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: object, status: int = 200) -> None:
            self._send(status, json.dumps(data).encode(), "application/json")

        def _page(self, name: str) -> None:
            self._send(200, (FIXTURES / name).read_bytes(), "text/html; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            path = parts.path
            if path == "/app" or re.fullmatch(r"/c/[^/]+|/chat/conversation/[^/]+|/feed(/thread/[^/]+)?", path):
                headless = "HeadlessChrome" in (self.headers.get("User-Agent") or "")
                with app._lock:
                    app.page_hits += 1
                    app.headless_hits.append(headless)
                signed_in = SESSION_COOKIE in (self.headers.get("Cookie") or "")
                if headless and app.headless_page == "other":
                    self._page("structure.html")
                    return
                if (app.require_login and not signed_in) or (headless and app.headless_page == "login"):
                    self._send(302, b"", "text/plain", {"Location": app.login_url(app.base + self.path)})
                    return
                query = parse_qs(parts.query)
                if path == "/app" and query.get("restore") == ["1"] and app.conversations:
                    last = list(app.conversations)[-1]  # the new-chat address restores it
                    self._send(302, b"", "text/plain", {"Location": f"/c/{last}?{parts.query}"})
                    return
                variant = query.get("ui", [""])[0]
                name = f"app-{variant}.html" if re.fullmatch(r"[a-z]+", variant) else "app.html"
                if path.startswith("/feed"):
                    name = "app-feed.html"  # the shape that lives under its own path
                self._page(name if (FIXTURES / name).is_file() else "app.html")
            elif path == "/guest":
                self._page("app-signedout.html")  # the host's landing page, for anyone
            elif path == "/login":
                self._page("login.html")
            elif path == "/structure":
                self._page("structure.html")
            elif path == "/auth/complete":
                target = parse_qs(parts.query).get("return", [app.url()])[0]
                cookie = f"{SESSION_COOKIE}; Max-Age=86400; Path=/"
                self._send(302, b"", "text/plain", {"Location": target, "Set-Cookie": cookie})
            elif match := re.fullmatch(r"/api/live/([^/]+)", path):
                # What an open tab follows with live=1 (change copilot-turn-speed): a session
                # that ended, a conversation deleted elsewhere, turns added elsewhere.
                signed_in = SESSION_COOKIE in (self.headers.get("Cookie") or "")
                with app._lock:
                    turns = app.conversations.get(match.group(1))
                if app.require_login and not signed_in:
                    self._json({"error": "signed out"}, 401)
                elif turns is None:
                    self._json({"error": "not found"}, 404)
                else:
                    self._json({"turns": [{"role": t["role"], "text": t["text"]} for t in turns]})
            elif match := re.fullmatch(r"/api/conversation/([^/]+)", path):
                with app._lock:
                    turns = app.conversations.get(match.group(1))
                if turns is None:
                    self._json({"error": "not found"}, 404)
                else:
                    self._json({"turns": turns})
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            path = urlsplit(self.path).path
            if path == "/api/send":
                data = json.loads(body)
                conversation, reply = app.receive(data.get("conversation"), data["prompt"],
                                                  data.get("mode"), data.get("list_open"))
                self._json({"conversation": conversation, "reply": reply,
                            "html": rich_reply(data["prompt"])})
            elif path == "/api/mode":
                with app._lock:
                    app.mode_events.append(str(json.loads(body).get("mode")))
                self._json({"ok": True})
            elif path == "/api/login-event":
                with app._lock:
                    app.login_events.append(body.decode() or "unknown")
                self._json({"ok": True})
            else:
                self._send(404, b"not found", "text/plain")

    return Handler
