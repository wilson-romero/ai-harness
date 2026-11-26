"""What the harness needs from a language-model provider."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from harness.core.contracts import LLMRequest


class ProviderError(Exception):
    """The provider reported that it could not process the request."""


class LLMProvider(Protocol):
    name: str
    # Prompts and responses are stored only when the provider declares them synthetic.
    synthetic_content: bool

    async def ask(self, request: LLMRequest, on_sent: Callable[[], None]) -> str:
        """Send the prompt and return the response text.

        Call `on_sent()` at the moment the prompt leaves: a deadline that expires before it
        is a clean timeout, one that expires after it leaves the request uncertain.
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
