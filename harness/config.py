"""Local configuration read from environment variables."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from harness.core.answer_style import answer_notice
from harness.core.errors import InvalidInput


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
    # The concise-answer notice of plain questions, or None (`HARNESS_CONCISE_ANSWERS=off`).
    answer_notice: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        data_dir = Path(env.get("HARNESS_DATA_DIR") or "./data")
        profile = env.get("HARNESS_EDGE_PROFILE")
        return cls(
            data_dir=data_dir,
            provider=env.get("HARNESS_PROVIDER") or "mock",
            request_timeout_s=_number(env, "HARNESS_REQUEST_TIMEOUT_S", 120.0),
            mock_behavior=env.get("HARNESS_MOCK_BEHAVIOR") or "ok",
            mock_delay_ms=int(_number(env, "HARNESS_MOCK_DELAY_MS", 0)),
            mock_responses=(env.get("HARNESS_MOCK_RESPONSES") or "").strip(),
            copilot_url=env.get("HARNESS_COPILOT_URL") or None,
            edge_profile=Path(profile) if profile else data_dir / "edge-profile",
            copilot_ready_timeout_s=_number(env, "HARNESS_COPILOT_READY_TIMEOUT_S", 60.0),
            copilot_max_prompt_chars=_positive_int(env, "HARNESS_COPILOT_MAX_PROMPT_CHARS"),
            browser_headless=env.get("HARNESS_TEST_HEADLESS") == "1",
            answer_notice=answer_notice(env),
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


def _positive_int(env: Mapping[str, str], key: str) -> int | None:
    raw = env.get(key)
    if not raw:
        return None
    if not raw.isdigit() or int(raw) < 1:
        raise InvalidInput(f"{key} must be a whole number of at least 1, got {raw!r}")
    return int(raw)


def _number(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise InvalidInput(f"{key} must be a number, got {raw!r}") from None
    if value < 0:
        raise InvalidInput(f"{key} must not be negative")
    return value
