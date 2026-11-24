"""Local configuration read from environment variables."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from harness.core.errors import InvalidInput


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    provider: str
    request_timeout_s: float
    mock_behavior: str
    mock_delay_ms: int
    mock_responses: str  # path of the scripted answers of the Mock, or empty

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        return cls(
            data_dir=Path(env.get("HARNESS_DATA_DIR") or "./data"),
            provider=env.get("HARNESS_PROVIDER") or "mock",
            request_timeout_s=_number(env, "HARNESS_REQUEST_TIMEOUT_S", 120.0),
            mock_behavior=env.get("HARNESS_MOCK_BEHAVIOR") or "ok",
            mock_delay_ms=int(_number(env, "HARNESS_MOCK_DELAY_MS", 0)),
            mock_responses=(env.get("HARNESS_MOCK_RESPONSES") or "").strip(),
        )


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
