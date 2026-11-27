"""Microsoft Copilot Web through the dedicated Edge profile (design D5 to D12).

Everything about the real page comes from the probe's measurement (`ui.json` in the data
directory): the locators, where the conversation identifier sits in the URL, the end-of-reply
signal, the stability window, the size limit and the login hosts. Nothing here names a real
selector or address.

Rules this module keeps:

- It types only into the measured editor, only when the page is `ready` on the configured host,
  and checks that again right before the key press. It never fills, types or clicks anything
  else, and never touches a sign-in page.
- `on_sent` is called just before the key press. From then on every failure is `uncertain` and
  nothing is sent again, with one exception proved on the real page: if after a few seconds no
  user turn was added and the editor still holds exactly the prompt, the key press was lost and
  is repeated once (the prompt cannot leave twice when it never left).
- The remote identifier is learned from the URL when the platform assigns it, reported at once
  with `events.bound`, and checked in the URL before anything is typed when reopening.
- Page text is untrusted: the reply is read with a size cap, cleaned of control, escape and
  invisible characters, and only returned. No message of this module carries page text, a URL
  of the page or an exception's text: they are fixed sentences with counts.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass

from playwright.async_api import BrowserContext, ElementHandle, Locator, Page
from playwright.async_api import Error as PlaywrightError

from harness.browser.edge import SHUTDOWN_S, EdgeLauncher
from harness.browser.login import recorded_ready_path
from harness.browser.page_state import (
    PageState,
    classify,
    guest_page_advice,
    host_of,
    is_target_gone,
)
from harness.config import Settings
from harness.core.contracts import LLMRequest
from harness.core.errors import HarnessError, InvalidInput
from harness.text.safe_text import safe_foreign_text
from harness.providers.base import (
    AuthenticationRequired,
    ProviderError,
    ProviderEvents,
    ProviderTimeout,
    PromptTooLong,
    ProviderUncertain,
    RemoteConversationLost,
)
from harness.providers.copilot_ui import (
    ConversationRef,
    Locators,
    MeasurementError,
    UiMeasurement,
    load_measurement,
)

PROVIDER_NAME = "copilot_web"
REPLY_MAX_CHARS = 200_000  # read at most this much of a reply from the page
REPLY_MAX_NODES = 20_000  # and walk at most this many elements of it
REPLY_MAX_DEPTH = 64  # and this many levels
POLL_S = 0.1
STATE_POLL_S = 0.25
STATE_PERSIST_S = 3.0  # a sign-in or guest page must stay that long (redirects pass through)
SETTLE_S = 2.0  # the page's element count unchanged that long before typing
RESUBMIT_AFTER_S = 4.0  # nothing left the editor and no turn was added: the key press was lost
ID_WAIT_AFTER_END_S = 10.0  # the identifier arrives about 2 s after the reply ends (D6)
CLOSE_RESERVE_S = SHUTDOWN_S  # of the request deadline, kept for putting the browser away
# With the browser held for a conversation a question closes nothing on its way out; the
# reserve only covers handing the answer back.
HELD_RESERVE_S = 2.0
PAGE_CLOSE_S = 5.0  # bound on closing a tab that is no longer trusted
HISTORY_WAIT_S = 15.0  # a reopened conversation shows none of its turns that long: it is gone
RETRY_MIN_S = 10.0  # a lost tab is tried again only with at least this much of the deadline left

# Characters in the editor: a field's value, else the text content. Zero-width characters do
# not count (a rich editor keeps some as cursor anchors) and neither do line breaks, which a
# rich editor turns into paragraphs.
EDITOR_LENGTH_JS = (
    "el => (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' ? el.value : el.textContent)"
    ".replace(/[\\u200B-\\u200D\\u2060\\uFEFF\\r\\n]/g, '').length"
)
# The reply rebuilt as Markdown from the structure of the page, capped in the page: what
# crosses to Python is never larger than the cap. Read only; nothing is changed in the page.
# The page renders the Markdown the model wrote (measured on the real page on 2026-11-26, by
# structure only): headings are H1-H6, lists UL/OL with LI, tables TABLE, inline marks STRONG,
# EM and CODE, and a code block is an editor widget: a short label with the language and
# buttons, then the code inside one `role=textbox`. `innerText` drops what the Skills check
# (`## ` headings, a ```json block), so the reply is rebuilt instead:
#   H1-H6 -> "#" x level; UL/OL -> "- " / "N. " (nested lists indented); TABLE -> "| a | b |"
#   rows with a separator after the first; STRONG/B -> **x**, EM/I -> *x* around inline text
#   only (each line on its own; an empty one gives nothing; one holding blocks is a plain
#   container, as on the real page on 2026-11-26), CODE -> `x`;
#   PRE, a role=textbox, or an element holding one role=textbox whose only other text is
#   the measured language label (`code_language` in ui.json) -> a fenced block. The language
#   is taken only from that label element (or the language-* class of a PRE) and only if it
#   matches LANGUAGE (review 2026-11-26: a prose word next to a code box is not a language;
#   it stays as prose, before the block); BR -> line break; HR -> ---.
# Meaning is kept (review 2026-11-26): a fence is longer than the longest run of backticks in
# the code, and so is an inline code span; a line of plain text that would read as a
# heading, list item, quote, rule or fence (`# x`, `- x`, `1. x`, `> x`, `---`, ```) gets a
# backslash before its marker.
# Anything else gives its text. Left out: visually hidden elements (a box of at most 1 px or
# clipped away, as the screen-reader heading before every real reply) and controls (buttons,
# toolbars, menus: the follow-up suggestions under a real reply, a code block's copy button).
# Bounded: at most 20 000 elements and 64 levels are walked.
REPLY_TEXT_JS = r"""
(root, [max, labelSelector]) => {
  const CONTROLS = "button,[role=button],[role=toolbar],[role=menu],[role=menubar],[role=menuitem]";
  const BLOCKS = new Set(["ADDRESS", "ARTICLE", "ASIDE", "BLOCKQUOTE", "CAPTION", "DD",
    "DETAILS", "DIV", "DL", "DT", "FIELDSET", "SUMMARY", "FIGCAPTION", "FIGURE", "FOOTER", "FORM", "HEADER", "LI", "MAIN", "NAV", "P",
    "SECTION", "TBODY", "THEAD", "TR"]);
  const MARKS = { STRONG: "**", B: "**", EM: "*", I: "*" };
  const BLOCK_SELECTOR = "address,article,aside,blockquote,dd,details,div,dl,dt,fieldset,figure," +
    "footer,form,h1,h2,h3,h4,h5,h6,header,hr,li,main,nav,ol,p,pre,section,table,ul,[role=textbox]";
  const MAX_NODES = 20000, MAX_DEPTH = 64;
  let nodes = 0, cut = false;
  const hidden = (e) => {
    if (!e.textContent.trim()) return false;
    const s = getComputedStyle(e);
    if (s.display === "contents") return false;
    if (s.display === "none" || s.visibility === "hidden") return true;
    const r = e.getBoundingClientRect();
    return r.width <= 1 || r.height <= 1 || s.clipPath === "inset(50%)" || s.clip.startsWith("rect(0");
  };
  const skip = (e) => e.matches(CONTROLS) || e.tagName.toLowerCase() === "svg" || hidden(e);
  const textOf = (n) => {
    const ws = n.parentElement ? getComputedStyle(n.parentElement).whiteSpace : "normal";
    if (ws === "pre" || ws === "pre-wrap" || ws === "break-spaces") return n.textContent;
    if (ws === "pre-line") return n.textContent.replace(/[ \t]+/g, " ");
    return n.textContent.replace(/\s+/g, " ");
  };
  // Text of `e` outside `except` and `also`, controls and hidden elements.
  const labelOf = (e, except, also) => {
    let s = "";
    const go = (n) => {
      if (n === except || n === also) return;
      if (n.nodeType === 3) { s += n.textContent; return; }
      if (n.nodeType !== 1 || skip(n)) return;
      for (const c of n.childNodes) go(c);
    };
    go(e);
    return s.trim();
  };
  const LANGUAGE = /^[A-Za-z0-9][A-Za-z0-9+#._-]{0,19}$/;
  const longestRun = (s) => Math.max(0, ...(s.match(/`+/g) || []).map((r) => r.length));
  const fence = (lang, code) => {
    const body = code.replace(/^\n+|\s+$/g, "");
    const ticks = "`".repeat(Math.max(3, longestRun(body) + 1));
    return ticks + (LANGUAGE.test(lang) ? lang : "") + "\n" + body + "\n" + ticks;
  };
  const inlineCode = (s) => {
    const ticks = "`".repeat(longestRun(s) + 1);
    const pad = /^[` ]|[` ]$/.test(s) ? " " : "";
    return ticks + pad + s + pad + ticks;
  };
  // A line of plain text that Markdown would read as a block marker gets a backslash.
  const escapeLine = (l) => {
    const n = l.match(/^(\s*)(\d{1,9})([.)])(\s|$)/);
    if (n) return n[1] + n[2] + "\\" + l.slice(n[1].length + n[2].length);
    if (/^\s*(#{1,6}(\s|$)|>|[-+*](\s|$)|=+\s*$|-+\s*$|(\*\s*){3,}$|(_\s*){3,}$|`{3,}[^`]*$|~{3,})/.test(l))
      return l.replace(/^(\s*)/, "$1\\");
    return l;
  };
  const codeBlock = (e) => {
    if (e.tagName === "PRE") {
      const code = e.querySelector("code") || e;
      const cls = [...code.classList, ...e.classList].find((c) => /^lang(uage)?-/.test(c)) || "";
      return fence(cls.replace(/^lang(uage)?-/, ""), code.textContent);
    }
    if (e.matches("[role=textbox]")) return fence("", e.innerText || "");
    const boxes = e.querySelectorAll("[role=textbox]");
    if (boxes.length !== 1) return null;
    const box = boxes[0];
    let label = null;
    if (labelSelector) {
      for (const l of e.querySelectorAll(labelSelector)) {
        if (!box.contains(l) && !l.contains(box)) { label = l; break; }
      }
    }
    // Only the measured label (or nothing) around the code: any other text is prose that
    // holds the block, and is walked instead, so no text is lost and no word becomes a
    // language.
    if (labelOf(e, box, label)) return null;
    return fence(label ? labelOf(label, null, null) : "", box.innerText || "");
  };
  const line = (s) => s.replace(/\s*\n\s*/g, " ").trim();
  // Markdown of the children of `e`: blocks separated by `sep`.
  const render = (e, depth, sep) => {
    const out = [];
    let para = "";
    const flush = () => {
      const t = para.trim();
      if (t) out.push(t.split("\n").map(escapeLine).join("\n"));
      para = "";
    };
    const walk = (n, d) => {
      if (++nodes > MAX_NODES || d > MAX_DEPTH) { cut = true; return; }
      if (n.nodeType === 3) { para += textOf(n); return; }
      if (n.nodeType !== 1 || skip(n)) return;
      const tag = n.tagName;
      const code = codeBlock(n);
      if (code !== null) { flush(); out.push(code); return; }
      if (/^H[1-6]$/.test(tag)) {
        flush();
        const text = line(render(n, d + 1, " "));
        if (text) out.push("#".repeat(Number(tag[1])) + " " + text);
        return;
      }
      if (tag === "BR") { para += "\n"; return; }
      if (tag === "HR") { flush(); out.push("---"); return; }
      if (tag === "UL" || tag === "OL") {
        flush();
        let number = Number(n.getAttribute("start") || 1);
        const items = [];
        for (const li of n.children) {
          if (li.tagName !== "LI" || skip(li)) continue;
          const marker = tag === "OL" ? (number++) + ". " : "- ";
          const body = render(li, d + 1, "\n").split("\n");
          items.push(marker + body[0] + body.slice(1).map((l) => "\n" + " ".repeat(marker.length) + l).join(""));
        }
        if (items.length) out.push(items.join("\n"));
        return;
      }
      if (tag === "TABLE") {
        flush();
        const rows = [];
        for (const tr of n.querySelectorAll("tr")) {
          if (tr.closest("table") !== n) continue;
          const cells = [...tr.children].filter((c) => c.tagName === "TD" || c.tagName === "TH")
            .map((c) => line(render(c, d + 1, " ")).replace(/\|/g, "\\|"));
          rows.push("| " + cells.join(" | ") + " |");
          if (rows.length === 1) rows.push("|" + cells.map(() => " --- |").join(""));
        }
        if (rows.length) out.push(rows.join("\n"));
        return;
      }
      const mark = MARKS[tag];
      if (mark !== undefined) {
        // Emphasis wraps inline text only. Around blocks (seen on the real page: a STRONG
        // holding a heading and a list) it is a plain container; empty, it gives nothing.
        if (n.querySelector(BLOCK_SELECTOR)) {
          flush();
          for (const c of n.childNodes) walk(c, d + 1);
          flush();
          return;
        }
        const lines = render(n, d + 1, "\n").split("\n").map((l) => l.trim());
        if (!lines.some((l) => l)) return;
        if (/^\s/.test(n.textContent) && para && !/\s$/.test(para)) para += " ";
        para += lines.map((l) => (l ? mark + l + mark : "")).join("\n");
        if (/\s$/.test(n.textContent)) para += " ";
        return;
      }
      if (tag === "CODE") { if (n.textContent) para += inlineCode(n.textContent); return; }
      if (tag === "BLOCKQUOTE") {
        flush();
        out.push(render(n, d + 1, "\n\n").split("\n").map((l) => (l ? "> " + l : ">")).join("\n"));
        return;
      }
      const block = BLOCKS.has(tag);
      if (block) flush();
      for (const c of n.childNodes) walk(c, d + 1);
      if (block) flush();
    };
    for (const c of e.childNodes) walk(c, depth);
    flush();
    return out.join(sep);
  };
  const text = render(root, 0, "\n\n").replace(/\n{3,}/g, "\n\n").trim();
  return [text.length, text.length > max ? text.slice(0, max) : text, cut];
}
"""


async def read_reply(turn: Locator, code_label: str) -> tuple[str, bool]:
    """The text of one assistant turn as the page renders it, and whether it was cut.

    The cap is applied again here (security review 2026-11-27, F-05): REPLY_TEXT_JS runs in
    the page, and a hostile page could return more than it was asked for, or under-report its
    length. What Python keeps is at most REPLY_MAX_CHARS characters, and a reply cut here is
    reported as cut, like one the page cut.
    """
    length, text, walk_cut = await turn.evaluate(REPLY_TEXT_JS, [REPLY_MAX_CHARS, code_label])
    text = text if isinstance(text, str) else ""
    cut_here = len(text) > REPLY_MAX_CHARS
    return text[:REPLY_MAX_CHARS], cut_here or int(length) > REPLY_MAX_CHARS or bool(walk_cut)


def editor_length(text: str) -> int:
    """`EDITOR_LENGTH_JS` for a Python string."""
    return sum(1 for c in text if c not in "​‌‍⁠﻿\r\n")


def clean_reply(text: str) -> str:
    """Untrusted page text made safe to print: whole terminal escape sequences, control,
    bidirectional and invisible characters removed (line breaks kept), credentials of known
    formats redacted, no surrounding blank space."""
    return safe_foreign_text(text).text.strip()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


class _TabGone(ProviderError):
    """The question's tab or window was gone before anything was typed."""


class _NoEvents:
    def bound(self, remote_ref: str) -> None:
        pass

    def warn(self, text: str) -> None:
        pass

    def truncated(self) -> None:
        pass


@dataclass(frozen=True)
class _Plan:
    url: str
    measurement: UiMeasurement
    ref: ConversationRef
    limit: int


class _Held:
    """The browser a conversation keeps open between its questions (design D3, revised
    2026-11-26). The `browser` lock is held as long as this lives."""

    def __init__(self, stack: AsyncExitStack, context: BrowserContext) -> None:
        self.stack = stack
        self.context = context
        self.page: Page | None = None
        # True after a question that did not end with an answer (an error, a deadline,
        # Ctrl+C): the tab may still be typing, sending or rendering, so it is not used again.
        self.untrusted = False
        self.gone = False
        context.on("close", lambda _context: self._lost())

    def _lost(self) -> None:
        self.gone = True

    async def page_for_question(self) -> Page:
        """The tab the next question uses. An untrusted tab is replaced by a new one in the
        same browser (opened first, so the window never loses its last tab) and closed without
        running the page's unload handlers. The question then loads its own conversation, as
        every question does."""
        old = self.page
        if old is None or old.is_closed() or self.untrusted:
            self.page = await self.context.new_page()
            self.untrusted = False
            if old is not None and not old.is_closed():
                with contextlib.suppress(PlaywrightError, asyncio.TimeoutError):
                    await asyncio.wait_for(old.close(run_before_unload=False), PAGE_CLOSE_S)
        return self.page


class CopilotWebProvider:
    name = PROVIDER_NAME
    synthetic_content = False  # D11: nothing of what is asked or answered is stored

    def __init__(self, settings: Settings, launcher: EdgeLauncher | None = None) -> None:
        self._settings = settings
        self._launcher = launcher
        self._held: _Held | None = None

    # -- resources for a conversation (interactive-shell D5; this change's D3) --------------

    async def open_resources(self) -> None:
        """Launch Edge on the dedicated profile once for a whole conversation and keep it,
        with the `browser` lock, until `close_resources`. Nothing is loaded yet: the sign-in
        state is judged by the first question, which never types into a sign-in page. A
        browser that is busy fails at once with the usual message."""
        if self._held is None:
            self._held = await self._launch_held(None)

    async def close_resources(self) -> None:
        held, self._held = self._held, None
        if held is not None:
            await held.stack.aclose()

    async def _launch_held(self, wait_s: float | None) -> _Held:
        launcher = self._launcher or EdgeLauncher.from_settings(self._settings)
        stack = AsyncExitStack()
        try:
            context = await stack.enter_async_context(launcher.open(wait_s=wait_s))
        except BaseException:
            await stack.aclose()
            raise
        return _Held(stack, context)

    async def _held_page(self, deadline: float) -> Page:
        held = self._held
        assert held is not None
        if held.gone:  # the window was closed by hand: put it away and launch again
            self._held = None
            await held.stack.aclose()
            held = self._held = await self._launch_held(max(0.0, deadline - time.monotonic()))
        return await held.page_for_question()

    # -- before anything is recorded --------------------------------------------------------

    def check(self, prompt: str) -> None:
        """Configuration, measurement and size, without opening anything (D2, D12)."""
        plan = self._plan()
        if len(prompt) > plan.limit:
            raise PromptTooLong(
                f"the prompt has {len(prompt)} characters; the most Copilot takes here is "
                f"{plan.limit} (the largest size the probe measured, or "
                "HARNESS_COPILOT_MAX_PROMPT_CHARS if lower). Nothing was sent"
            )

    def _plan(self) -> _Plan:
        url = self._settings.require_copilot_url()
        measurement = load_measurement(self._settings.data_dir)
        ref = measurement.conversation_ref
        assert ref is not None and measurement.max_prompt_chars is not None  # complete
        if ref.url_for(url, "probe") is None:
            raise MeasurementError(
                "the measured conversation reference has no fixed path before the identifier, "
                "so a conversation cannot be reopened; run the probe's measure step again"
            )
        limit = measurement.max_prompt_chars
        if self._settings.copilot_max_prompt_chars is not None:
            limit = min(limit, self._settings.copilot_max_prompt_chars)
        return _Plan(url, measurement, ref, limit)

    # -- one question -----------------------------------------------------------------------

    async def ask(
        self,
        request: LLMRequest,
        on_sent: Callable[[], None],
        *,
        events: ProviderEvents | None = None,
    ) -> str:
        plan = self._plan()
        if len(request.prompt) > plan.limit:  # the service checked; never type an over-long one
            raise PromptTooLong(f"the prompt is longer than {plan.limit} characters")
        held = self._held is not None
        reserve = min(HELD_RESERVE_S if held else CLOSE_RESERVE_S, request.timeout_s * 0.25)
        deadline = time.monotonic() + request.timeout_s - reserve
        turn = _Turn(self._settings, plan, request, on_sent, events or _NoEvents(), deadline)
        try:
            if held:
                return await self._ask_held(turn, deadline)
            launcher = self._launcher or EdgeLauncher.from_settings(self._settings)
            # Session lock (held by the service) first, then the browser lock: same order in
            # every command, and a bounded wait.
            async with launcher.open(wait_s=max(0.0, deadline - time.monotonic())) as context:
                page = context.pages[0] if context.pages else await context.new_page()
                text = await turn.run(page)
            return text  # the browser is closed before the answer is handed back
        except ProviderUncertain:
            raise
        except (ProviderError, HarnessError):
            if turn.sent:
                raise ProviderUncertain(turn.uncertain_reason()) from None
            raise
        except PlaywrightError as exc:
            if turn.sent:
                raise ProviderUncertain(turn.uncertain_reason(exc)) from None
            if is_target_gone(exc):
                raise ProviderError("the Edge window was closed before the prompt was sent") from None
            raise ProviderError(
                f"the browser failed before the prompt was sent ({type(exc).__name__})"
            ) from None
        except Exception as exc:
            if turn.sent:
                raise ProviderUncertain(turn.uncertain_reason(exc)) from None
            raise ProviderError(
                f"the Copilot provider failed before the prompt was sent ({type(exc).__name__})"
            ) from None


    async def _ask_held(self, turn: _Turn, deadline: float) -> str:
        """One question in the conversation's browser. Only a question that ends with an
        answer leaves its tab trusted; any other end (an error, a deadline, Ctrl+C, which
        arrives here as a cancellation) marks it, and the next question gets a new tab."""
        for attempt in (1, 2):
            page = await self._held_page(deadline)
            answered = False
            try:
                text = await turn.run(page)
                answered = True
                return text
            except (_TabGone, PlaywrightError) as exc:
                # Seen once on the real page (2026-11-26, not reproduced): the first question
                # of a conversation ended with the window reported closed before typing.
                # Nothing was typed, so one more try in a new tab (or a new Edge, if the
                # whole browser went) cannot send anything twice. After the send, never.
                lost = isinstance(exc, _TabGone) or is_target_gone(exc)
                if turn.sent or not lost or attempt == 2 or turn.remaining() < RETRY_MIN_S:
                    raise
                turn.events.warn("the Edge tab was lost before anything was typed; "
                                 "trying once more in a new tab")
            finally:
                if not answered and self._held is not None:
                    self._held.untrusted = True
        raise AssertionError("unreachable")


class _Turn:
    """The work of one question on an open page."""

    def __init__(
        self,
        settings: Settings,
        plan: _Plan,
        request: LLMRequest,
        on_sent: Callable[[], None],
        events: ProviderEvents,
        deadline: float,
    ) -> None:
        self.settings = settings
        self.plan = plan
        self.request = request
        self.on_sent = on_sent
        self.events = events
        self.deadline = deadline
        self.host = host_of(plan.url)
        self.locators: Locators = plan.measurement.locators
        label = self.locators.code_language
        self.code_label = label.css_selector() if label is not None else None
        self.assistants_at_send = 0
        self.sent = False
        self.bound = request.remote_ref is not None
        self.stage = "before sending"

    def uncertain_reason(self, exc: BaseException | None = None) -> str:
        kind = f" ({type(exc).__name__})" if exc is not None else ""
        if exc is not None and isinstance(exc, PlaywrightError) and is_target_gone(exc):
            return f"the Edge window was closed {self.stage} after the prompt was sent"
        return f"the Copilot provider failed {self.stage} after the prompt was sent{kind}"

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    async def run(self, page: Page) -> str:
        await self.open_conversation(page)
        users = self.locators.user_turn.resolve(page)
        assistants = self.locators.assistant_turn.resolve(page)
        users_before = await users.count()
        self.compare_turns(users_before)
        # The last user turn before sending: the new one comes after it, and the answer after
        # the new one. Indices computed before sending are not used: a history that arrives
        # late is inserted above and moves them (review 2026-11-26, defect 2).
        last_user = await users.last.element_handle() if users_before else None
        self.assistants_at_send = await assistants.count()
        composer = self.locators.composer.resolve(page).first
        expected = editor_length(self.request.prompt)
        await self.put_prompt(page, composer, expected)
        await self.send(composer)
        self.stage = "while waiting for the answer"
        text, cut = await self.await_reply(page, composer, users, last_user, assistants)
        self.stage = "while waiting for the conversation identifier"
        await self.await_identifier(page)
        self.still_this_conversation(page)
        if cut:
            self.events.truncated()
            self.events.warn(
                f"the answer was longer than what is read from the page (at most "
                f"{REPLY_MAX_CHARS} characters, {REPLY_MAX_NODES} elements and "
                f"{REPLY_MAX_DEPTH} levels); only the first part was read. The whole answer "
                "is in Edge"
            )
        return clean_reply(text)

    def still_this_conversation(self, page: Page) -> None:
        """When the answer ends, the address must still name the session's conversation: if
        the platform filed the prompt in another one, the answer belongs to that one."""
        remote = self.request.remote_ref
        if remote is not None and self.plan.ref.identifier_in(page.url) != remote:
            raise ProviderUncertain(
                "the answer ended in another remote conversation than this session's, so it "
                "is not shown and the session keeps its own; the prompt was not resent"
            )

    # -- before sending ---------------------------------------------------------------------

    async def open_conversation(self, page: Page) -> None:
        ref, remote = self.plan.ref, self.request.remote_ref
        target = self.plan.url if remote is None else ref.url_for(self.plan.url, remote)
        assert target is not None
        ready_by = min(self.deadline, time.monotonic() + self.settings.copilot_ready_timeout_s)
        try:
            await page.goto(target, wait_until="commit", timeout=_ms(ready_by - time.monotonic()))
        except PlaywrightError as exc:
            if page.is_closed() or is_target_gone(exc):
                raise
            # A slow or failed load is judged below, by what the page shows in time.
        await self.wait_ready(page, ready_by)
        await self.settle(page, ready_by)
        await self.wait_history(page, ready_by)
        await self.guard(page)

    async def wait_history(self, page: Page, ready_by: float) -> None:
        """When reopening, wait (at most HISTORY_WAIT_S) until the conversation shows the
        turns this session completed in it: a history can arrive after the page stopped
        changing (review 2026-11-26, defect 2). It may show fewer and stay so (the real list
        is virtualized, D6): some turns, unchanged for SETTLE_S, are enough. None at all is a
        conversation that is gone, even if the address kept its identifier (defect 3)."""
        need = self.request.completed_turns if self.request.remote_ref is not None else 0
        if need == 0:
            return
        users = self.locators.user_turn.resolve(page)
        until = min(ready_by, time.monotonic() + HISTORY_WAIT_S)
        seen, changed = await users.count(), time.monotonic()
        while seen < need and time.monotonic() < until:
            if seen > 0 and time.monotonic() - changed >= SETTLE_S:
                break  # a part of a long conversation, shown and stable
            await asyncio.sleep(STATE_POLL_S)
            now = await users.count()
            if now != seen:
                seen, changed = now, time.monotonic()
        if seen == 0:
            raise _lost()

    async def wait_ready(self, page: Page, ready_by: float) -> None:
        measurement = self.plan.measurement
        state, since = PageState.UNKNOWN, time.monotonic()
        while True:
            now_state = await classify(page, measurement, self.host)
            if now_state is not state:
                state, since = now_state, time.monotonic()
            held = time.monotonic() - since
            if state is PageState.READY:
                return
            if state is PageState.CLOSED:
                raise _TabGone("the Edge window was closed before the prompt was sent")
            if state is PageState.LOGIN and held >= STATE_PERSIST_S:
                raise _sign_in_needed()
            if time.monotonic() >= ready_by:
                if state is PageState.LOGIN:
                    raise _sign_in_needed()
                if state is PageState.GUEST:
                    raise ProviderError(
                        guest_page_advice(self.plan.url, recorded_ready_path(self.settings.data_dir))
                        + ". Nothing was sent"
                    )
                raise ProviderTimeout(
                    "the Copilot page was not ready in time "
                    f"(HARNESS_COPILOT_READY_TIMEOUT_S is {self.settings.copilot_ready_timeout_s:g} s, "
                    "within HARNESS_REQUEST_TIMEOUT_S); nothing was sent"
                )
            await asyncio.sleep(STATE_POLL_S)

    async def settle(self, page: Page, ready_by: float) -> None:
        """Wait until the page stops adding elements: a key press on a page still rendering
        was lost on the real page. Bounded; a page that keeps changing is used as it is."""
        last, same_since = -1, time.monotonic()
        while time.monotonic() < ready_by:
            count = await page.locator("*").count()
            if count != last:
                last, same_since = count, time.monotonic()
            elif time.monotonic() - same_since >= SETTLE_S:
                return
            await asyncio.sleep(STATE_POLL_S)

    async def guard(self, page: Page) -> None:
        """Right before typing and again before sending: the chat, on the configured host,
        and when reopening, the session's own conversation (D6, D7)."""
        state = await classify(page, self.plan.measurement, self.host)
        if state is PageState.CLOSED:
            raise _TabGone("the Edge window was closed before the prompt was sent")
        if state is PageState.LOGIN:
            raise _sign_in_needed()
        if state is not PageState.READY or host_of(page.url) != self.host:
            raise ProviderError("the Copilot page stopped being ready before sending; nothing was sent")
        remote = self.request.remote_ref
        users = await self.locators.user_turn.resolve(page).count()
        if remote is None:
            # A new conversation only: an address with an identifier, or turns already on the
            # page, is some other conversation (the new-chat address can restore the last
            # one), and typing there would mix two sessions (review 2026-11-26, SEC-02).
            if self.plan.ref.identifier_in(page.url) is not None or users:
                raise ProviderError(
                    "the new-chat address showed an existing conversation instead of a new "
                    "one, so nothing was typed; open a new chat in the Edge window and ask again"
                )
            return
        if self.plan.ref.identifier_in(page.url) != remote:
            raise _lost()
        if users == 0 and self.request.completed_turns > 0:
            raise _lost()  # an empty chat that kept the address (review 2026-11-26, defect 3)

    def compare_turns(self, users_visible: int) -> None:
        completed = self.request.completed_turns
        if self.request.remote_ref is None:
            if completed:
                self.events.warn(
                    f"this session completed {completed} question(s) but has no remote "
                    "conversation reference; this question starts a new remote conversation "
                    "without the earlier context"
                )
            return
        if users_visible > completed:
            extra = users_visible - completed
            self.events.warn(
                f"the remote conversation has {extra} more turn(s) than the harness completed; "
                "an uncertain request may have reached it (it stays uncertain and was not resent)"
            )

    async def put_prompt(self, page: Page, composer: Locator, expected: int) -> None:
        for _ in range(2):  # a page that resets its editor while loading gets one more fill
            await composer.fill(self.request.prompt, timeout=_ms(self.remaining()))
            got = await _editor_length(composer)
            if got == expected:
                await self.guard(page)  # still the chat, still this conversation
                return
        raise ProviderError(
            f"the editor held {got} of the prompt's {expected} characters, so the prompt "
            "would have been cut; nothing was sent"
        )

    async def send(self, composer: Locator) -> None:
        self.sent = True
        self.on_sent()  # just before the key press: a failure during it counts as sent
        await self.submit(composer)

    async def submit(self, composer: Locator) -> None:
        if self.locators.send_with == "enter":
            await composer.press("Enter", timeout=_ms(self.remaining()))
        else:
            assert self.locators.send is not None  # the schema requires it
            page = composer.page
            await self.locators.send.resolve(page).first.click(timeout=_ms(self.remaining()))

    # -- after sending ----------------------------------------------------------------------

    async def await_reply(
        self,
        page: Page,
        composer: Locator,
        users: Locator,
        last_user: ElementHandle | None,
        assistants: Locator,
    ) -> tuple[str, bool]:
        """The new reply, once the measured signal holds and its text has not changed for the
        stability window (D8). The new reply is the first assistant turn after the new user
        turn, which is the last user turn and comes after `last_user` (the last one before
        sending), in document order."""
        signal = self.plan.measurement.end_signal
        assert signal is not None
        window_s = max(
            self.plan.measurement.stability_window_ms or 0, signal.window_ms or 0
        ) / 1000
        sent_at = time.monotonic()
        confirmed = resubmitted = False
        expected = editor_length(self.request.prompt)
        digest, since = None, time.monotonic()
        while True:
            if self.remaining() <= 0:
                raise ProviderUncertain(
                    "the answer did not finish before the deadline (HARNESS_REQUEST_TIMEOUT_S)"
                )
            self.try_bind(page)
            new_user = await _new_user_turn(users, last_user)
            answer = await _answer_after(assistants, new_user) if new_user is not None else None
            if not confirmed:
                confirmed = new_user is not None or await _editor_length(composer) == 0
                if (
                    not confirmed
                    and not resubmitted
                    and answer is None
                    # The thread did not change at all: a page that shows an error or a usage
                    # notice as a turn and puts the prompt back is never sent to twice.
                    and await assistants.count() == self.assistants_at_send
                    and time.monotonic() - sent_at >= RESUBMIT_AFTER_S
                    and await _editor_length(composer) == expected
                ):
                    resubmitted = True  # the prompt never left: press once more, never again
                    await self.submit(composer)
            if answer is not None:
                turn = assistants.nth(answer)
                text, cut = await read_reply(turn, self.code_label)
                now = _digest(text)
                if now != digest:
                    digest, since = now, time.monotonic()
                stable = time.monotonic() - since >= window_s
                if text.strip() and stable and await self.signal_met(page, composer, turn):
                    return text, cut
            await asyncio.sleep(POLL_S)

    async def signal_met(self, page: Page, composer: Locator, turn: Locator) -> bool:
        signal = self.plan.measurement.end_signal
        assert signal is not None
        loc = self.locators
        if signal.name == "stop_hidden" and loc.stop is not None:
            stop = loc.stop.resolve(page)
            return await stop.count() == 0 or not await stop.first.is_visible()
        if signal.name == "done_control" and loc.response_done_control is not None:
            return await loc.response_done_control.resolve(turn).count() > 0
        if signal.name == "aria_busy":
            region = loc.busy_region.resolve(page).last if loc.busy_region else turn
            return await region.get_attribute("aria-busy") != "true"
        if signal.name == "send_ready":
            send_ok = loc.send is None or await loc.send.resolve(page).first.is_visible()
            return send_ok and await composer.is_editable()
        return True  # text_stable: the stability window is the signal

    def try_bind(self, page: Page) -> None:
        """Report the identifier as soon as the platform puts it in the URL (D6)."""
        if self.bound:
            return
        identifier = self.plan.ref.identifier_in(page.url)
        if identifier is not None:
            self.bound = True
            self.events.bound(identifier)

    async def await_identifier(self, page: Page) -> None:
        """The reply is complete; the identifier may still be on its way (D6, window 3)."""
        until = min(self.deadline, time.monotonic() + ID_WAIT_AFTER_END_S)
        while not self.bound and time.monotonic() < until:
            self.try_bind(page)
            await asyncio.sleep(POLL_S)
        if not self.bound:
            self.events.warn(
                "Copilot answered, but the conversation identifier did not reach the address "
                "in time, so this session has no remote conversation reference; the next "
                "question starts a new remote conversation without this context"
            )


def _lost() -> RemoteConversationLost:
    return RemoteConversationLost(
        "the remote conversation of this session could not be found again, so nothing "
        "was sent and the session is now closed. Create a new session to go on"
    )


def _sign_in_needed() -> AuthenticationRequired:
    return AuthenticationRequired(
        "Copilot asks to sign in again; nothing was sent. Run `main.py copilot login`, sign in "
        "in the Edge window, and ask again"
    )


# Index of the last user turn if it comes after `previous` (or `previous` is None and there is
# one): the user turn of the prompt just sent. -1 otherwise.
NEW_USER_JS = """(turns, previous) => {
  const last = turns.length - 1;
  if (last < 0) return -1;
  if (previous === null) return last;
  if (turns[last] === previous) return -1;
  return previous.compareDocumentPosition(turns[last]) & Node.DOCUMENT_POSITION_FOLLOWING ? last : -1;
}"""
# Index of the first assistant turn after `user` in document order; -1 if none yet.
ANSWER_AFTER_JS = """(turns, user) => turns.findIndex(
  (t) => user.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING)"""


async def _new_user_turn(users: Locator, previous: ElementHandle | None) -> ElementHandle | None:
    index = await users.evaluate_all(NEW_USER_JS, previous)
    return None if index < 0 else await users.nth(index).element_handle()


async def _answer_after(assistants: Locator, user: ElementHandle) -> int | None:
    index = await assistants.evaluate_all(ANSWER_AFTER_JS, user)
    return None if index < 0 else int(index)


async def _editor_length(composer: Locator) -> int:
    return int(await composer.evaluate(EDITOR_LENGTH_JS))


def _ms(seconds: float) -> float:
    return max(1.0, seconds * 1000)
