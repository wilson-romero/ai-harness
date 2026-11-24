"""Deterministic provider with no network access, for tests and demos."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable

from harness.core.contracts import LLMRequest
from harness.core.errors import InvalidInput
from harness.providers.base import ProviderError

BEHAVIORS = ("ok", "fail", "timeout_before_send", "timeout_after_send")
_FOREVER_S = 24 * 60 * 60


class MockProvider:
    name = "mock"
    synthetic_content = True

    def __init__(self, behavior: str = "ok", delay_ms: int = 0) -> None:
        if behavior not in BEHAVIORS:
            raise InvalidInput(
                f"unknown mock behavior {behavior!r}; expected one of: {', '.join(BEHAVIORS)}"
            )
        self._behavior = behavior
        self._delay_s = delay_ms / 1000
        self.calls = 0

    async def ask(self, request: LLMRequest, on_sent: Callable[[], None]) -> str:
        self.calls += 1
        if self._behavior == "timeout_before_send":
            await asyncio.sleep(_FOREVER_S)
        on_sent()
        if self._behavior == "fail":
            raise ProviderError("the mock provider was configured to fail")
        if self._behavior == "timeout_after_send":
            await asyncio.sleep(_FOREVER_S)
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        digest = hashlib.sha256(f"{request.session_id}\n{request.prompt}".encode()).hexdigest()
        return f"[mock {digest[:12]}] Received {len(request.prompt)} characters."
