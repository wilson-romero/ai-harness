"""What the harness needs from a language-model provider."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from harness.core.contracts import LLMRequest
from harness.core.errors import InvalidInput


class ModeUnavailable(InvalidInput):
    """The provider cannot set this response mode now (response-mode D1). Nothing was sent,
    and nothing is recorded: the message says why and what to do."""


class ProviderError(Exception):
    """The provider reported that it could not process the request.

    The message is printed to the terminal: a provider builds it from fixed text and counts,
    never from page content, URLs or anything the remote side wrote.
    """


class PromptTooLong(InvalidInput):
    """The whole text the provider would receive is over its limit. Nothing was sent.

    The provider measures everything it would type; the service, which composed that text,
    adds how much of it is the person's and how much the harness's own."""


class AuthenticationRequired(ProviderError):
    """The provider needs a person to sign in again. Nothing was sent."""


class RemoteConversationLost(ProviderError):
    """The session's remote conversation cannot be found again. Nothing was sent."""


class ProviderUncertain(ProviderError):
    """Something failed after the prompt may have left: it may have reached the provider."""


class RemoteConversationTaken(ProviderUncertain):
    """The prompt went into a remote conversation that another session owns (SEC-02): the
    answer mixes two sessions, so it is neither shown nor bound."""


class ProviderTimeout(ProviderError, TimeoutError):
    """The provider gave up waiting before sending (for example, a page that never loads)."""


def timeout_on_its_way(exc: BaseException) -> ProviderTimeout | None:
    """The provider's own ProviderTimeout behind `exc`, if the request's deadline fired while
    it was on its way out (the provider closing its browser after giving up). The deadline's
    TimeoutError is raised from the cancellation, and the cancellation, raised during the
    close, keeps the provider's error as its context (Windows parity 3)."""
    seen: set[int] = set()
    link: BaseException | None = exc
    while link is not None and id(link) not in seen:
        if isinstance(link, ProviderTimeout):
            return link
        seen.add(id(link))
        link = link.__cause__ or link.__context__
    return None


class ProviderEvents(Protocol):
    """What a provider may tell the service while it works (design D5)."""

    def bound(self, remote_ref: str) -> None:
        """The remote conversation's identifier is known: store it in the session now."""
        ...

    def warn(self, text: str) -> None:
        """A fixed-text warning for the person; it is printed on stderr."""
        ...

    def truncated(self) -> None:
        """Only part of the answer was read (a size or structure bound was hit)."""
        ...


class LLMProvider(Protocol):
    name: str
    # Prompts and responses are stored only when the provider declares them synthetic.
    synthetic_content: bool

    async def ask(self, request: LLMRequest, on_sent: Callable[[], None]) -> str:
        """Send the prompt and return the response text.

        Call `on_sent()` at the moment the prompt leaves: a deadline that expires before it
        is a clean timeout, one that expires after it leaves the request uncertain.

        A provider may also accept a keyword argument `events` (a `ProviderEvents`) and a
        method `check(prompt)`, a validation without effects that the service calls before
        anything is recorded. Both are optional: the Mock has neither.

        Response modes (response-mode D1), also optional: a method `check_mode(mode)`, without
        effects, that raises `ModeUnavailable` when the provider cannot set that mode (without
        it only `auto` is accepted), and a keyword argument `on_mode(mode)` with which `ask`
        reports the mode it confirmed for `request.mode`: before sending, and again if the
        provider sees it change during the answer.
        """
        ...


class ConversationResources(Protocol):
    """Optional (interactive-shell D5): resources a provider keeps for a whole conversation.

    A conversation calls `open_resources()` once when it starts and `close_resources()` once
    when it ends, also after a failed or uncertain question. Single commands never call them:
    a provider that has them still manages its resources per question when they are not
    called. Every question between the two keeps its own states and the no-resend rule.
    """

    async def open_resources(self) -> None: ...

    async def close_resources(self) -> None: ...


async def open_resources(provider: object) -> None:
    """Open the provider's conversation resources, if it has any; a no-op otherwise."""
    operation = getattr(provider, "open_resources", None)
    if operation is not None:
        await operation()


async def close_resources(provider: object) -> None:
    """Close what `open_resources` opened, if the provider has anything to close."""
    operation = getattr(provider, "close_resources", None)
    if operation is not None:
        await operation()
