"""Vault root and memory limits.

Nothing here is read unless a command needs the memory (`memory ...` or `ask --project`).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from harness.core.errors import DataDirInsideVault, MemoryNotConfigured
from harness.memory.paths import is_within

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


def ensure_data_dir_outside_vault(data_dir: Path, vault_root: Path) -> None:
    """Refuse a data directory inside the vault: the harness never writes in the vault.

    `vault_root` is the resolved root. The data directory may not exist yet, so it is
    resolved without `strict`, and each existing ancestor is also compared by identity with
    the root (`samefile`), which catches a path that differs only in case or goes through a
    link. The vault inside the data directory is fine.
    """
    resolved = data_dir.resolve()
    inside = is_within(resolved, vault_root)
    for candidate in (resolved, *resolved.parents):
        if inside:
            break
        try:
            inside = candidate.exists() and os.path.samefile(candidate, vault_root)
        except OSError:
            continue
    if inside:
        raise DataDirInsideVault(
            f"HARNESS_DATA_DIR is inside {VAULT_ROOT_ENV}; the harness never writes in the "
            "vault, so point HARNESS_DATA_DIR at a folder outside it"
        )
