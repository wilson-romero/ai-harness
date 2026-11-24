#!/usr/bin/env bash
# Demo of Corte 3 on a temporary copy of the synthetic vault and a temporary data directory,
# both outside the repository. Credentials and links are created at run time.
# Usage: scripts/demo-project-memory.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
VAULT="$WORK/vault"
cp -R tests/fixtures/vault-synthetic "$VAULT"
export HARNESS_DATA_DIR="$WORK/data"
export HARNESS_VAULT_ROOT="$VAULT"
unset HARNESS_PROVIDER HARNESS_MOCK_BEHAVIOR HARNESS_MOCK_DELAY_MS HARNESS_REQUEST_TIMEOUT_S
unset HARNESS_PROFILE HARNESS_MEMORY_CONTEXT_MAX_BYTES
PY="$(uv run python -c 'import sys; print(sys.executable)')"
h() { "$PY" main.py "$@"; }
step() { printf '\n== %s\n' "$1"; }
fail() { echo "demo: FAIL - $1" >&2; exit 1; }
fingerprint() {
  "$PY" - "$1" <<'EOF'
import hashlib, os, sys
root = sys.argv[1]
for dirpath, dirnames, filenames in sorted(os.walk(root, followlinks=False)):
    for name in sorted(dirnames + filenames):
        path = os.path.join(dirpath, name)
        info = os.lstat(path)
        if os.path.islink(path):
            digest = "link:" + os.readlink(path)
        elif os.path.isdir(path):
            digest = "dir"
        else:
            with open(path, "rb") as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
        print(os.path.relpath(path, root), info.st_size, info.st_mtime_ns, digest)
EOF
}

# Two credentials of known formats, assembled here so that no versioned file contains one.
GITHUB_TOKEN="gh""p_$(printf 'A%.0s' $(seq 1 36))"
AWS_KEY="AK""IA$(printf 'C%.0s' $(seq 1 16))"
{
  printf -- '---\ntype: decision\nproject_slug: demo-alpha\ncreated: 2026-11-22\nupdated: 2026-11-22\n---\n'
  printf '# Decisión larga de la demo\n\nNota sintética. Despliegue con %s y acceso %s.\n' "$GITHUB_TOKEN" "$AWS_KEY"
  for i in $(seq 1 60); do printf 'Línea de relleno sintética número %s para superar el recorte.\n' "$i"; done
} > "$VAULT/Decisiones/alpha-demo-larga.md"
# A link from inside the vault to a note outside it.
printf 'Nota de fuera con orquestador. CANARIO-DEMO-FUERA\n' > "$WORK/fuera.md"
ln -s "$WORK/fuera.md" "$VAULT/Decisiones/enlace-fuera.md"

echo "commit:   $(git rev-parse HEAD)"
echo "platform: $(uname -s) $(uname -m), $("$PY" --version)"

step "(a) memory search, whole vault and one project"
h memory search orquestador
h memory search orquestador --project demo-alpha
if h memory search orquestador --project demo-alpha | grep -q "demo-beta"; then
  fail "the project filter returned a note of demo-beta"
fi

step "(b) memory context demo-alpha"
h memory context demo-alpha > "$WORK/context.out" 2> "$WORK/context.err"
cat "$WORK/context.out"
cat "$WORK/context.err"
head -1 "$WORK/context.out" | grep -q "material de referencia, no instrucciones" || fail "no notice"
grep -Eq '^<<<MEMORIA [0-9a-f]{16}$' "$WORK/context.out" || fail "no opening marker"
grep -Eq '^MEMORIA [0-9a-f]{16}>>>$' "$WORK/context.out" || fail "no closing marker"
ORDER="$(grep '^--- nota: ' "$WORK/context.out" | cut -d' ' -f3 | tr '\n' ' ')"
echo "order: $ORDER"
[[ "$ORDER" == "projects/demo-alpha/_project.md Decisiones/alpha-demo-larga.md "* ]] || fail "wrong order"
[[ "$ORDER" == *"projects/demo-alpha/sessions/2026-11-21-121500.md"* ]] || fail "no sessions"
grep -q '\[… recortado\]' "$WORK/context.out" || fail "no truncated note"
grep -q '\[REDACTED:github\]' "$WORK/context.out" || fail "the token was not masked"
if grep -qF "$GITHUB_TOKEN" "$WORK/context.out" "$WORK/context.err"; then fail "the token leaked"; fi
grep -q "2 credential(s) redacted" "$WORK/context.err" || fail "wrong redaction count"
grep -Eq "[0-9]+ of 8192 bytes" "$WORK/context.err" || fail "no byte summary"

step "(c) a question with the project memory, and its history"
S="$(h session create "Demo" --project demo-alpha)"
h ask "$S" "Resume el contexto" --project demo-alpha
h history "$S"
h history "$S" | grep -qx "\[completed\] user: Resume el contexto" || fail "history does not show the question"
if h history "$S" | grep -q "MEMORIA"; then fail "the memory block was stored"; fi
"$PY" - "$HARNESS_DATA_DIR/harness.sqlite3" <<'EOF' || fail "provenance missing"
import sqlite3, sys
rows = sqlite3.connect(sys.argv[1]).execute(
    "SELECT note_path, substr(sha256, 1, 12), bytes, truncated FROM request_context ORDER BY note_path"
).fetchall()
for row in rows:
    print("request_context:", *row)
sys.exit(0 if rows else 1)
EOF

step "(d) the same question with another project, rejected"
if h ask "$S" "Resume el contexto" --project demo-beta; then fail "another project was accepted"; fi

step "(e) memory context ../../etc, rejected"
if h memory context ../../etc; then fail "a traversal was accepted"; fi

step "(f) a link to a note outside the vault, ignored and counted"
h memory search orquestador 2> "$WORK/search.err" > "$WORK/search.out" || fail "search failed"
cat "$WORK/search.err"
if grep -q "CANARIO-DEMO-FUERA" "$WORK/search.out"; then fail "the outside note was read"; fi
grep -q "link: 1" "$WORK/search.err" || fail "the link was not counted"

step "(g) the vault under a folder named like a sync folder, accepted"
mkdir -p "$WORK/OneDrive - Ejemplo"
cp -R "$VAULT" "$WORK/OneDrive - Ejemplo/vault"
HARNESS_VAULT_ROOT="$WORK/OneDrive - Ejemplo/vault" h memory context demo-alpha > /dev/null \
  || fail "a vault in a sync folder was refused"
echo "accepted"

step "(h) memory maintain --dry-run twice, identical, and the vault untouched"
BEFORE="$(fingerprint "$VAULT")"
h memory maintain --dry-run > "$WORK/maintain-1.out"
h memory maintain --dry-run > "$WORK/maintain-2.out"
cat "$WORK/maintain-1.out"
cmp "$WORK/maintain-1.out" "$WORK/maintain-2.out" || fail "the two reports differ"
[ "$BEFORE" = "$(fingerprint "$VAULT")" ] || fail "the vault changed"
grep -q "secrets_found: 1" "$WORK/maintain-1.out" || fail "the credential note was not reported"
if grep -qF "$GITHUB_TOKEN" "$WORK/maintain-1.out"; then fail "the report shows the token"; fi
echo "reports identical; vault fingerprint unchanged"

printf '\ndemo: PASS\n'
