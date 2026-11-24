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

step "python: version and lockfile"
uv run python --version
uv lock --check

step "tests"
uv run pytest

step "openspec: specs and changes"
openspec validate --all --strict --no-interactive

printf '\nverify: PASS on %s\n' "$SHA"
