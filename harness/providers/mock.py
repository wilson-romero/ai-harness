"""Deterministic provider with no network access, for tests and demos."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Callable, Mapping
from pathlib import Path

from harness.core.contracts import LLMRequest
from harness.core.response_mode import ResponseMode
from harness.core.errors import InvalidInput
from harness.core.strict_json import loads_strict, read_text_limited
from harness.providers.base import ProviderError

BEHAVIORS = ("ok", "fail", "timeout_before_send", "timeout_after_send")
RESPONSES_ENV = "HARNESS_MOCK_RESPONSES"
RESPONSES_MAX_BYTES = 1024 * 1024
# In a scripted answer, replaced by the nonce of the `/plan` question being answered (the one
# the harness writes in its plan example), so that a script can answer a plan the way a model
# that follows the instructions would (code-mode slice 2). Only the Mock does this.
PLAN_NONCE_TOKEN = "{{plan_nonce}}"
_PLAN_NONCE = re.compile(r'"nonce": "([0-9a-f]{16})"')
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
        self.modes: list[ResponseMode] = []  # the mode of every question received

    def check_mode(self, mode: ResponseMode) -> None:
        """The Mock sets every mode (response-mode D1)."""

    async def ask(
        self,
        request: LLMRequest,
        on_sent: Callable[[], None],
        *,
        on_mode: Callable[[ResponseMode], None] | None = None,
    ) -> str:
        self.calls += 1
        self.modes.append(request.mode)
        if on_mode is not None:
            on_mode(request.mode)  # "set" before sending, as a page would confirm it
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
                return _with_plan_nonce(answer, request.prompt)
        digest = hashlib.sha256(f"{request.session_id}\n{request.prompt}".encode()).hexdigest()
        # The answers of the default mode stay as they always were; the others say their mode,
        # so that a test sees the mode reached the provider.
        mode = "" if request.mode is ResponseMode.AUTO else f" in mode {request.mode}"
        return f"[mock {digest[:12]}] Received {len(request.prompt)} characters{mode}."


def _with_plan_nonce(answer: str, prompt: str) -> str:
    if PLAN_NONCE_TOKEN not in answer:
        return answer
    found = _PLAN_NONCE.search(prompt)
    return answer.replace(PLAN_NONCE_TOKEN, found.group(1)) if found else answer
