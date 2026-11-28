"""Local configuration read from environment variables."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from harness.core.answer_style import answer_notice
from harness.core.errors import InvalidInput

# A deep answer reasons before it writes: without a measured duration (the probe sends nothing
# in deep mode), it gets three times the normal deadline by default (response-mode D6).
DEEP_TIMEOUT_FACTOR = 3.0


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    provider: str
    request_timeout_s: float
    mock_behavior: str
    mock_delay_ms: int
    mock_responses: str  # path of the scripted answers of the Mock, or empty
    # Copilot Web and its dedicated Edge profile. Real values live only in the local `.env`.
    copilot_url: str | None = None
    edge_profile: Path | None = None
    copilot_ready_timeout_s: float = 60.0
    # None means "the largest size the probe measured"; the variable can only lower it.
    copilot_max_prompt_chars: int | None = None
    # Automated tests run the browser without a window; real use is always visible.
    browser_headless: bool = False
    # The concise-answer notice of plain questions with `HARNESS_CONCISE_ANSWERS=on`; None
    # (the default) otherwise.
    answer_notice: str | None = None
    # The deadline of a question in `deep` mode (response-mode D6); None: three times the
    # request timeout.
    deep_timeout_s: float | None = None
    # Change copilot-turn-speed: each optimisation can be switched off, and each one runs
    # only when the probe measured it (`tab_reuse`, `fast_end` in ui.json); `copilot_timings`
    # adds a line with the time of each phase to every question's warnings.
    copilot_reuse_tab: bool = True
    copilot_fast_end: bool = True
    copilot_timings: bool = False
    # Questions to Copilot without a window (`HARNESS_COPILOT_HEADLESS=on`), off by default.
    # Signing in and the probe's discovery always use a window (copilot-turn-speed D5).
    copilot_headless: bool = False

    @property
    def deep_request_timeout_s(self) -> float:
        if self.deep_timeout_s is None:
            return DEEP_TIMEOUT_FACTOR * self.request_timeout_s
        return self.deep_timeout_s

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        data_dir = Path(env.get("HARNESS_DATA_DIR") or "./data")
        profile = env.get("HARNESS_EDGE_PROFILE")
        request_timeout_s = _number(env, "HARNESS_REQUEST_TIMEOUT_S", 120.0, deadline=True)
        deep_timeout_s: float | None = None
        if env.get("HARNESS_DEEP_REQUEST_TIMEOUT_S"):
            deep_timeout_s = _number(env, "HARNESS_DEEP_REQUEST_TIMEOUT_S", 0.0, deadline=True)
            if deep_timeout_s < request_timeout_s:
                raise InvalidInput(
                    "HARNESS_DEEP_REQUEST_TIMEOUT_S must not be lower than "
                    "HARNESS_REQUEST_TIMEOUT_S: a deep answer never gets less time"
                )
        return cls(
            data_dir=data_dir,
            provider=env.get("HARNESS_PROVIDER") or "mock",
            request_timeout_s=request_timeout_s,
            deep_timeout_s=deep_timeout_s,
            mock_behavior=env.get("HARNESS_MOCK_BEHAVIOR") or "ok",
            mock_delay_ms=int(_number(env, "HARNESS_MOCK_DELAY_MS", 0)),
            mock_responses=(env.get("HARNESS_MOCK_RESPONSES") or "").strip(),
            copilot_url=env.get("HARNESS_COPILOT_URL") or None,
            edge_profile=Path(profile) if profile else data_dir / "edge-profile",
            copilot_ready_timeout_s=_number(env, "HARNESS_COPILOT_READY_TIMEOUT_S", 60.0),
            copilot_max_prompt_chars=_positive_int(env, "HARNESS_COPILOT_MAX_PROMPT_CHARS"),
            browser_headless=env.get("HARNESS_TEST_HEADLESS") == "1",
            answer_notice=answer_notice(env),
            copilot_reuse_tab=_on_off(env, "HARNESS_COPILOT_REUSE_TAB", True),
            copilot_fast_end=_on_off(env, "HARNESS_COPILOT_FAST_END", True),
            copilot_timings=_on_off(env, "HARNESS_COPILOT_TIMINGS", False),
            copilot_headless=_on_off(env, "HARNESS_COPILOT_HEADLESS", False),
        )

    def require_copilot_url(self) -> str:
        """The Copilot URL, checked only by the commands that open it."""
        if not self.copilot_url:
            raise InvalidInput("HARNESS_COPILOT_URL is not set; put it in your local .env")
        parts = urlsplit(self.copilot_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            # The value itself is not echoed: it may be a real tenant URL.
            raise InvalidInput("HARNESS_COPILOT_URL must be an http or https URL with a host")
        return self.copilot_url


def _on_off(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = (env.get(key) or "").strip().lower()
    if not raw:
        return default
    if raw in ("on", "off"):
        return raw == "on"
    raise InvalidInput(f"{key} must be 'on' or 'off', got {raw!r}")


def _positive_int(env: Mapping[str, str], key: str) -> int | None:
    raw = env.get(key)
    if not raw:
        return None
    if not raw.isdigit() or int(raw) < 1:
        raise InvalidInput(f"{key} must be a whole number of at least 1, got {raw!r}")
    return int(raw)


def _number(env: Mapping[str, str], key: str, default: float, *, deadline: bool = False) -> float:
    """A number of the environment. A `deadline` must be finite and above 0: `nan` or an
    infinity would reach `asyncio.timeout` with the request already recorded (review
    2026-11-27, finding 6)."""
    raw = env.get(key)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise InvalidInput(f"{key} must be a number, got {raw!r}") from None
    if deadline and not (math.isfinite(value) and value > 0):
        raise InvalidInput(f"{key} must be a finite number above 0, got {raw!r}")
    if not math.isfinite(value):
        raise InvalidInput(f"{key} must be a finite number, got {raw!r}")
    if value < 0:
        raise InvalidInput(f"{key} must not be negative")
    return value
