"""Deterministic provider with no network access, for tests and demos."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path

from harness.core.contracts import LLMRequest
from harness.core.errors import InvalidInput
from harness.core.strict_json import loads_strict, read_text_limited
from harness.providers.base import ProviderError

BEHAVIORS = ("ok", "fail", "timeout_before_send", "timeout_after_send")
RESPONSES_ENV = "HARNESS_MOCK_RESPONSES"
RESPONSES_MAX_BYTES = 1024 * 1024
_FOREVER_S = 24 * 60 * 60


def load_responses(raw_path: str) -> dict[str, str]:
    """Scripted answers (skill-engine D15): a local JSON object of text -> answer."""
    path = Path(raw_path)
    what = RESPONSES_ENV
    if not path.is_absolute():
        raise InvalidInput(f"{what} must be an absolute path")
    data = loads_strict(
        read_text_limited(path, max_bytes=RESPONSES_MAX_BYTES, what=what),
        max_bytes=RESPONSES_MAX_BYTES,
        what=what,
    )
    if not isinstance(data, dict) or not all(
        isinstance(key, str) and key and isinstance(value, str) for key, value in data.items()
    ):
        raise InvalidInput(f"{what} must be a JSON object of non-empty texts to texts")
    return data


class MockProvider:
    name = "mock"
    synthetic_content = True

    def __init__(
        self,
        behavior: str = "ok",
        delay_ms: int = 0,
        responses: Mapping[str, str] | None = None,
    ) -> None:
        if behavior not in BEHAVIORS:
            raise InvalidInput(
                f"unknown mock behavior {behavior!r}; expected one of: {', '.join(BEHAVIORS)}"
            )
        self._behavior = behavior
        self._delay_s = delay_ms / 1000
        # Alphabetical order: the first key contained in the prompt wins, whatever the file.
        self._responses = sorted((responses or {}).items())
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
        for key, answer in self._responses:
            if key in request.prompt:
                return answer
        digest = hashlib.sha256(f"{request.session_id}\n{request.prompt}".encode()).hexdigest()
        return f"[mock {digest[:12]}] Received {len(request.prompt)} characters."
