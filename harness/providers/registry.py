"""Providers by name. Names come from local configuration, never from a model."""

from __future__ import annotations

from collections.abc import Callable

from harness.config import Settings
from harness.core.errors import UnknownProvider
from harness.providers.base import LLMProvider
from harness.providers.mock import MockProvider, load_responses

ProviderFactory = Callable[[str], LLMProvider]


def provider_factory(settings: Settings) -> ProviderFactory:
    builders: dict[str, Callable[[], LLMProvider]] = {
        "mock": lambda: MockProvider(
            settings.mock_behavior,
            settings.mock_delay_ms,
            load_responses(settings.mock_responses) if settings.mock_responses else None,
        ),
        "copilot_web": lambda: _copilot(settings),
    }

    def build(name: str) -> LLMProvider:
        try:
            builder = builders[name]
        except KeyError:
            known = ", ".join(sorted(builders))
            raise UnknownProvider(f"unknown provider {name!r}; available: {known}") from None
        return builder()

    return build


def _copilot(settings: Settings) -> LLMProvider:
    # Playwright is imported only when a Copilot provider is actually built. Building it opens
    # nothing: the browser starts in `ask`, after `check` passed.
    from harness.providers.copilot_web import CopilotWebProvider

    return CopilotWebProvider(settings)
