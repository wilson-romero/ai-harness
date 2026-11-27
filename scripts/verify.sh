#!/usr/bin/env bash
# Local merge gate: runs every check on a clean tree and prints the SHA they ran on.
# Usage: scripts/verify.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ -n "$(git status --porcelain)" ]; then
  echo "verify: the working tree has uncommitted changes; commit or stash them first" >&2
  exit 1
fi
SHA="$(git rev-parse HEAD)"

step() { printf '\n== %s\n' "$1"; }

# The lock first, before any `uv run`: `uv run` would otherwise rewrite a stale `uv.lock` and
# the check after it would pass (security review 2026-11-27, F-06). From here on every `uv`
# command refuses to change the lock instead of updating it.
step "lockfile: uv.lock matches pyproject.toml"
uv lock --check
export UV_LOCKED=1

step "public repository guard: secrets, runtime data, private details"
uv run python scripts/check_public_safety.py

step "python: version"
uv run python --version

step "tests"
uv run pytest

step "SEC matrix: rows, states, cited tests and requirements exist"
uv run python scripts/check_sec_matrix.py

step "openspec: specs and changes"
openspec validate --all --strict --no-interactive

step "the checks changed nothing in the tree"
if [ -n "$(git status --porcelain)" ]; then
  git status --porcelain >&2
  echo "verify: the checks changed the working tree (above); nothing may rewrite it" >&2
  exit 1
fi

printf '\nverify: PASS on %s\n' "$SHA"
