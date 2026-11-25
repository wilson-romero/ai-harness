"""What the harness needs from a language-model provider."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from harness.core.contracts import LLMRequest


class ProviderError(Exception):
    """The provider reported that it could not process the request.

    The message is printed to the terminal: a provider builds it from fixed text and counts,
    never from page content, URLs or anything the remote side wrote.
    """


class AuthenticationRequired(ProviderError):
    """The provider needs a person to sign in again. Nothing was sent."""


class RemoteConversationLost(ProviderError):
    """The session's remote conversation cannot be found again. Nothing was sent."""


class ProviderUncertain(ProviderError):
    """Something failed after the prompt may have left: it may have reached the provider."""


class ProviderTimeout(ProviderError, TimeoutError):
    """The provider gave up waiting before sending (for example, a page that never loads)."""


class ProviderEvents(Protocol):
    """What a provider may tell the service while it works (design D5)."""

    def bound(self, remote_ref: str) -> None:
        """The remote conversation's identifier is known: store it in the session now."""
        ...

    def warn(self, text: str) -> None:
        """A fixed-text warning for the person; it is printed on stderr."""
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
        """
        ...
