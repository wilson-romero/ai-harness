"""Configuration of the skill commands, read only when a `skill` command runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from harness.core.errors import InvalidInput

SKILLS_DIR_ENV = "HARNESS_SKILLS_DIR"
APPROVAL_TTL_ENV = "HARNESS_APPROVAL_TTL_S"
DEFAULT_APPROVAL_TTL_S = 900
APPROVAL_TTL_MIN_S = 60
APPROVAL_TTL_MAX_S = 3600
# The repository's own `skills/` folder, found from the package, not from the current directory.
DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"


@dataclass(frozen=True)
class SkillSettings:
    skills_dir: Path
    approval_ttl_s: int


def load_skill_settings(env: Mapping[str, str]) -> SkillSettings:
    raw_dir = (env.get(SKILLS_DIR_ENV) or "").strip()
    skills_dir = Path(raw_dir) if raw_dir else DEFAULT_SKILLS_DIR
    if not skills_dir.is_absolute():
        raise InvalidInput(f"{SKILLS_DIR_ENV} must be an absolute path")
    return SkillSettings(skills_dir=skills_dir, approval_ttl_s=_ttl(env))


def _ttl(env: Mapping[str, str]) -> int:
    raw = (env.get(APPROVAL_TTL_ENV) or "").strip()
    if not raw:
        return DEFAULT_APPROVAL_TTL_S
    if not raw.isdigit() or not APPROVAL_TTL_MIN_S <= int(raw) <= APPROVAL_TTL_MAX_S:
        raise InvalidInput(
            f"{APPROVAL_TTL_ENV} must be a whole number of seconds between "
            f"{APPROVAL_TTL_MIN_S} and {APPROVAL_TTL_MAX_S}"
        )
    return int(raw)
