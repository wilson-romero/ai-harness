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
import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page

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
POLL_S = 0.1
STATE_POLL_S = 0.25
STATE_PERSIST_S = 3.0  # a sign-in or guest page must stay that long (redirects pass through)
SETTLE_S = 2.0  # the page's element count unchanged that long before typing
RESUBMIT_AFTER_S = 4.0  # nothing left the editor and no turn was added: the key press was lost
ID_WAIT_AFTER_END_S = 10.0  # the identifier arrives about 2 s after the reply ends (D6)
CLOSE_RESERVE_S = SHUTDOWN_S  # of the request deadline, kept for putting the browser away

# Characters in the editor: a field's value, else the text content. Zero-width characters do
# not count (a rich editor keeps some as cursor anchors) and neither do line breaks, which a
# rich editor turns into paragraphs.
EDITOR_LENGTH_JS = (
    "el => (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' ? el.value : el.textContent)"
    ".replace(/[\\u200B-\\u200D\\u2060\\uFEFF\\r\\n]/g, '').length"
)
# The reply as a sighted reader sees it, capped in the page: what crosses to Python is never
# larger than the cap. Text of visually hidden elements (a box of at most 1 px or clipped
# away, as screen-reader labels are: on the real page a hidden heading before every reply) is
# taken out, in document order. Read only; nothing is changed in the page.
REPLY_TEXT_JS = r"""
(el, max) => {
  const all = el.innerText || "";
  const hidden = [];
  for (const d of el.querySelectorAll("*")) {
    if (!d.textContent.trim() || hidden.some((h) => h.contains(d))) continue;
    const r = d.getBoundingClientRect(); const s = getComputedStyle(d);
    if (r.width <= 1 || r.height <= 1 || s.clipPath === "inset(50%)" || s.clip.startsWith("rect(0")) {
      hidden.push(d);
    }
  }
  let cursor = 0, out = "";
  for (const d of hidden) {
    const t = d.innerText;
    if (!t) continue;
    const at = all.indexOf(t, cursor);
    if (at < 0) continue;
    out += all.slice(cursor, at);
    cursor = at + t.length;
    if (all[cursor] === "\n") cursor += 1;
  }
  out += all.slice(cursor);
  return [out.length, out.length > max ? out.slice(0, max) : out];
}
"""


class PromptTooLong(InvalidInput):
    pass


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


class _NoEvents:
    def bound(self, remote_ref: str) -> None:
        pass

    def warn(self, text: str) -> None:
        pass


@dataclass(frozen=True)
class _Plan:
    url: str
    measurement: UiMeasurement
    ref: ConversationRef
    limit: int


class CopilotWebProvider:
    name = PROVIDER_NAME
    synthetic_content = False  # D11: nothing of what is asked or answered is stored

    def __init__(self, settings: Settings, launcher: EdgeLauncher | None = None) -> None:
        self._settings = settings
        self._launcher = launcher

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
        reserve = min(CLOSE_RESERVE_S, request.timeout_s * 0.25)
        deadline = time.monotonic() + request.timeout_s - reserve
        launcher = self._launcher or EdgeLauncher.from_settings(self._settings)
        turn = _Turn(self._settings, plan, request, on_sent, events or _NoEvents(), deadline)
        try:
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
        before = await assistants.count()
        self.compare_turns(users_before)
        composer = self.locators.composer.resolve(page).first
        expected = editor_length(self.request.prompt)
        await self.put_prompt(page, composer, expected)
        await self.send(composer)
        self.stage = "while waiting for the answer"
        text, truncated = await self.await_reply(page, composer, users, users_before, assistants, before)
        self.stage = "while waiting for the conversation identifier"
        await self.await_identifier(page)
        if truncated:
            self.events.warn(
                f"the answer was longer than {REPLY_MAX_CHARS} characters; only the first "
                f"{REPLY_MAX_CHARS} were read. The whole answer is in Edge"
            )
        return clean_reply(text)

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
        await self.guard(page)

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
                raise ProviderError("the Edge window was closed before the prompt was sent")
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
            raise ProviderError("the Edge window was closed before the prompt was sent")
        if state is PageState.LOGIN:
            raise _sign_in_needed()
        if state is not PageState.READY or host_of(page.url) != self.host:
            raise ProviderError("the Copilot page stopped being ready before sending; nothing was sent")
        remote = self.request.remote_ref
        if remote is not None and self.plan.ref.identifier_in(page.url) != remote:
            raise RemoteConversationLost(
                "the remote conversation of this session could not be found again, so nothing "
                "was sent and the session is now closed. Create a new session to go on"
            )

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
        users_before: int,
        assistants: Locator,
        before: int,
    ) -> tuple[str, bool]:
        """The new reply (index `before`), once the measured signal holds and its text has
        not changed for the stability window (D8)."""
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
            if not confirmed:
                confirmed = await users.count() > users_before or await _editor_length(composer) == 0
                if (
                    not confirmed
                    and not resubmitted
                    and time.monotonic() - sent_at >= RESUBMIT_AFTER_S
                    and await _editor_length(composer) == expected
                ):
                    resubmitted = True  # the prompt never left: press once more, never again
                    await self.submit(composer)
            if await assistants.count() > before:
                turn = assistants.nth(before)
                length, text = await turn.evaluate(REPLY_TEXT_JS, REPLY_MAX_CHARS)
                now = _digest(text)
                if now != digest:
                    digest, since = now, time.monotonic()
                stable = time.monotonic() - since >= window_s
                if text.strip() and stable and await self.signal_met(page, composer, turn):
                    return text, int(length) > REPLY_MAX_CHARS
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


def _sign_in_needed() -> AuthenticationRequired:
    return AuthenticationRequired(
        "Copilot asks to sign in again; nothing was sent. Run `main.py copilot login`, sign in "
        "in the Edge window, and ask again"
    )


async def _editor_length(composer: Locator) -> int:
    return int(await composer.evaluate(EDITOR_LENGTH_JS))


def _ms(seconds: float) -> float:
    return max(1.0, seconds * 1000)
