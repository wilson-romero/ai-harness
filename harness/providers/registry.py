"""Providers by name. Names come from local configuration, never from a model."""

from __future__ import annotations

from collections.abc import Callable

from harness.config import Settings
from harness.core.errors import UnknownProvider
from harness.providers.base import LLMProvider
from harness.providers.mock import MockProvider

ProviderFactory = Callable[[str], LLMProvider]


def provider_factory(settings: Settings) -> ProviderFactory:
    builders: dict[str, Callable[[], LLMProvider]] = {
        "mock": lambda: MockProvider(settings.mock_behavior, settings.mock_delay_ms),
    }

    def build(name: str) -> LLMProvider:
        try:
            builder = builders[name]
        except KeyError:
            known = ", ".join(sorted(builders))
            raise UnknownProvider(f"unknown provider {name!r}; available: {known}") from None
        return builder()

    return build
