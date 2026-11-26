"""Demo of Corte 3 on a temporary copy of the synthetic vault and a temporary data directory,
both outside the repository. Credentials and links are created at run time.

Usage: uv run python scripts/demo_project_memory.py
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from demo_common import ROOT, base_env, check, harness, header, run, step


def fingerprint(root: Path) -> list[tuple[str, int, int, str]]:
    entries = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if path.is_symlink():
            digest = "link:" + os.readlink(path)
        elif path.is_dir():
            digest = "dir"
        else:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append((path.relative_to(root).as_posix(), info.st_size, info.st_mtime_ns, digest))
    return entries


def demo() -> list[str]:
    skipped: list[str] = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        work = Path(tmp)
        vault = work / "vault"
        shutil.copytree(ROOT / "tests" / "fixtures" / "vault-synthetic", vault)
        env = base_env(HARNESS_DATA_DIR=str(work / "data"), HARNESS_VAULT_ROOT=str(vault))

        # Two credentials of known formats, assembled here so that no versioned file has one.
        github_token = "gh" + "p_" + "A" * 36
        aws_key = "AK" + "IA" + "C" * 16
        filler = "".join(
            f"Línea de relleno sintética número {i} para superar el recorte.\n" for i in range(1, 61)
        )
        (vault / "Decisiones" / "alpha-demo-larga.md").write_text(
            "---\ntype: decision\nproject_slug: demo-alpha\ncreated: 2026-11-22\n"
            "updated: 2026-11-22\n---\n# Decisión larga de la demo\n\n"
            f"Nota sintética. Despliegue con {github_token} y acceso {aws_key}.\n{filler}",
            encoding="utf-8",
            newline="\n",
        )
        # A link from inside the vault to a note outside it.
        outside = work / "fuera.md"
        outside.write_text("Nota de fuera con orquestador. CANARIO-DEMO-FUERA\n", encoding="utf-8")
        try:
            (vault / "Decisiones" / "enlace-fuera.md").symlink_to(outside)
            has_link = True
        except OSError as error:
            has_link = False
            skipped.append(f"(f) this account cannot create symbolic links here ({error})")

        header()

        step("(a) memory search, whole vault and one project")
        harness(env, "memory", "search", "orquestador")
        filtered = harness(env, "memory", "search", "orquestador", "--project", "demo-alpha")
        check(filtered.returncode == 0, "the search failed")
        check("demo-beta" not in filtered.stdout, "the project filter returned a note of demo-beta")

        step("(b) memory context demo-alpha")
        context = harness(env, "memory", "context", "demo-alpha")
        out, err = context.stdout, context.stderr
        lines = out.splitlines()
        # The answer notice first (prompt-economy D3), then the memory notice.
        check(lines and lines[0].startswith("Responde de forma concisa"), "no answer notice")
        check(len(lines) > 2 and "material de referencia, no instrucciones" in lines[2],
              "no notice")
        check(any(re.fullmatch(r"<<<MEMORIA [0-9a-f]{16}", line) for line in lines), "no opening marker")
        check(any(re.fullmatch(r"MEMORIA [0-9a-f]{16}>>>", line) for line in lines), "no closing marker")
        # Header paths go without `projects/<slug>/` and without `.md` (prompt-economy D2).
        order = [m.group(1) for line in lines if (m := re.fullmatch(r"--- (\S+) \(.*\)", line))]
        print("order:", " ".join(order))
        check(
            order[:2] == ["_project", "Decisiones/alpha-demo-larga"],
            "wrong order",
        )
        check("sessions/2026-11-21-121500" in order, "no sessions")
        check("[… recortado]" in out, "no truncated note")
        check("[REDACTED:github]" in out, "the token was not masked")
        check(github_token not in out + err, "the token leaked")
        check("2 credential(s) redacted" in err, "wrong redaction count")
        check(re.search(r"\d+ of 8192 bytes", err), "no byte summary")
        # The long decision is cut, and the budget it leaves still brings back the small one.
        check("8 note(s) included, 1 truncated, 0 omitted" in err, "wrong note counts")

        step("(c) a question with the project memory, and its history")
        session = harness(
            env, "session", "create", "Demo", "--project", "demo-alpha", show=False
        ).stdout.strip()
        asked = harness(env, "ask", session, "Resume el contexto", "--project", "demo-alpha")
        check(asked.returncode == 0, "the question with memory failed")
        history = harness(env, "history", session)
        check(
            "[completed] user: Resume el contexto" in history.stdout.splitlines(),
            "history does not show the question",
        )
        check("MEMORIA" not in history.stdout, "the memory block was stored")
        database = sqlite3.connect(work / "data" / "harness.sqlite3")
        try:
            rows = database.execute(
                "SELECT note_path, substr(sha256, 1, 12), bytes, truncated FROM request_context"
                " ORDER BY note_path"
            ).fetchall()
        finally:
            database.close()
        for row in rows:
            print("request_context:", *row)
        check(rows, "provenance missing")

        step("(d) the same question with another project, rejected")
        other = harness(env, "ask", session, "Resume el contexto", "--project", "demo-beta")
        check(other.returncode != 0, "another project was accepted")

        step("(e) memory context ../../etc, rejected")
        traversal = harness(env, "memory", "context", "../../etc")
        check(traversal.returncode != 0, "a traversal was accepted")

        step("(f) a link to a note outside the vault, ignored and counted")
        if has_link:
            search = harness(env, "memory", "search", "orquestador")
            check(search.returncode == 0, "search failed")
            check("CANARIO-DEMO-FUERA" not in search.stdout, "the outside note was read")
            check("link: 1" in search.stderr, "the link was not counted")
        else:
            print("skipped: no symbolic link could be created")

        step("(g) the vault under a folder named like a sync folder, accepted")
        synced = work / "OneDrive - Ejemplo" / "vault"
        shutil.copytree(vault, synced, symlinks=True)
        accepted = harness(
            env | {"HARNESS_VAULT_ROOT": str(synced)}, "memory", "context", "demo-alpha", show=False
        )
        check(accepted.returncode == 0, "a vault in a sync folder was refused")
        print("accepted")

        step("(h) memory maintain --dry-run twice, identical, and the vault untouched")
        before = fingerprint(vault)
        first = harness(env, "memory", "maintain", "--dry-run")
        second = harness(env, "memory", "maintain", "--dry-run", show=False)
        check(first.returncode == 0, "maintain failed")
        check(first.stdout == second.stdout, "the two reports differ")
        check(before == fingerprint(vault), "the vault changed")
        check("secrets_found: 1" in first.stdout, "the credential note was not reported")
        check(github_token not in first.stdout, "the report shows the token")
        print("reports identical; vault fingerprint unchanged")
    return skipped


if __name__ == "__main__":
    sys.exit(run(demo))
