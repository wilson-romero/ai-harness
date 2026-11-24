#!/usr/bin/env bash
# Demo of Corte 1 on a temporary data directory with synthetic content.
# Usage: scripts/demo-session-core.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export HARNESS_DATA_DIR="$(mktemp -d)"
unset HARNESS_PROVIDER HARNESS_MOCK_BEHAVIOR HARNESS_MOCK_DELAY_MS HARNESS_REQUEST_TIMEOUT_S
PY="$(uv run python -c 'import sys; print(sys.executable)')"
h() { "$PY" main.py "$@"; }
step() { printf '\n== %s\n' "$1"; }
fail() { echo "demo: FAIL - $1" >&2; exit 1; }

echo "commit:   $(git rev-parse HEAD)"
echo "platform: $(uname -s) $(uname -m), $("$PY" --version)"

step "(a) three sessions"
A="$(h session create "Arquitectura WhatsApp")"
B="$(h session create "Migracion de pagos")"
C="$(h session create "Revision HLS")"
h session list

step "(b) one question in each"
h ask "$A" "Pregunta sintetica de la sesion A"
h ask "$B" "Pregunta sintetica de la sesion B"
h ask "$C" "Pregunta sintetica de la sesion C"

step "(c) history from new processes, without mixing"
for S in "$A" "$B" "$C"; do echo "-- $S"; h history "$S"; done
h history "$A" | grep -q "sesion A" || fail "session A lost its own history"
if h history "$A" | grep -q "sesion B"; then fail "session A shows data of session B"; fi

step "(d) kill a question half way"
HARNESS_MOCK_DELAY_MS=60000 "$PY" main.py ask "$A" "Pregunta que se interrumpe" &
PID=$!
for _ in $(seq 1 100); do
  h history "$A" 2>/dev/null | grep -q "^\[running\]" && break
  sleep 0.1
done
kill -9 "$PID"
wait "$PID" 2>/dev/null || true
h session list
h history "$A"
h history "$A" | grep -q "^\[uncertain\] user: Pregunta que se interrumpe" || fail "the killed request is not uncertain"
h session list | grep "$A" | grep -q "uncertain" || fail "the session is not uncertain"

step "(e) malformed identifier"
if h history "no-es-un-uuid"; then fail "a malformed identifier was accepted"; fi

printf '\ndemo: PASS\n'
