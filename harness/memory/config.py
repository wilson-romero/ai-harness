"""Vault root and memory limits.

Nothing here is read unless a command needs the memory (`memory ...` or `ask --project`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from harness.core.errors import MemoryNotConfigured

CONTEXT_DEFAULT_BYTES = 8192
CONTEXT_MIN_BYTES = 1024
CONTEXT_MAX_BYTES = 65536

VAULT_ROOT_ENV = "HARNESS_VAULT_ROOT"
CONTEXT_BYTES_ENV = "HARNESS_MEMORY_CONTEXT_MAX_BYTES"


@dataclass(frozen=True)
class MemorySettings:
    vault_root: Path  # the real, resolved root
    context_max_bytes: int


def load_memory_settings(env: Mapping[str, str]) -> MemorySettings:
    """Validate the memory configuration. Raises before any note is read."""
    raw_root = (env.get(VAULT_ROOT_ENV) or "").strip()
    if not raw_root:
        raise MemoryNotConfigured(f"{VAULT_ROOT_ENV} is not set; point it at the vault folder")
    max_bytes = _context_max_bytes(env)
    root = Path(raw_root)
    if not root.is_absolute():
        raise MemoryNotConfigured(f"{VAULT_ROOT_ENV} must be an absolute path")
    if not root.is_dir():
        raise MemoryNotConfigured(f"{VAULT_ROOT_ENV} does not exist or is not a directory")
    return MemorySettings(vault_root=root.resolve(strict=True), context_max_bytes=max_bytes)


def _context_max_bytes(env: Mapping[str, str]) -> int:
    raw = (env.get(CONTEXT_BYTES_ENV) or "").strip()
    if not raw:
        return CONTEXT_DEFAULT_BYTES
    try:
        value = int(raw)
    except ValueError:
        raise MemoryNotConfigured(f"{CONTEXT_BYTES_ENV} must be an integer, got {raw!r}") from None
    if not CONTEXT_MIN_BYTES <= value <= CONTEXT_MAX_BYTES:
        raise MemoryNotConfigured(
            f"{CONTEXT_BYTES_ENV} must be between {CONTEXT_MIN_BYTES} and {CONTEXT_MAX_BYTES}"
        )
    return value
