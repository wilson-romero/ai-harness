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
