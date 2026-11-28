"""Demo of workspace-tools slice B1: the work folder, its confinement and `read`/`list` by CLI.

Usage: uv run python scripts/demo_workspace.py

Standard library only; same code on every platform. The synthetic work folder is built in a
temporary directory from `tests/fixtures/workspace/` (no real project content), with its own
data directory; nothing outside them is read or written. Every refusal case must say NO.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path

from demo_common import ROOT, base_env, check, harness, header, run, step

BUILD = ROOT / "tests" / "fixtures" / "workspace" / "build.py"


def _builder():
    spec = importlib.util.spec_from_file_location("workspace_fixture_build", BUILD)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _foreign_only(stdout: str) -> bool:
    return all(line.startswith("|") for line in stdout.splitlines())


def demo() -> list[str]:
    header()
    builder = _builder()
    skipped: list[str] = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work:
        base = Path(work)
        built = builder.build(base / "base")
        data = base / "data"
        env = base_env(HARNESS_DATA_DIR=str(data))
        folder = str(built.root)

        step("(a) the synthetic folder is accepted")
        result = harness(env, "workspace", "check", "--root", folder)
        check(result.returncode == 0 and "workspace: accepted" in result.stderr,
              "the synthetic folder was not accepted")

        step("(b) read a range of src/app.py: file text after '| ', summary on stderr")
        result = harness(env, "workspace", "read", "src/app.py", "--root", folder,
                         "--offset", "4", "--limit", "2")
        check(result.returncode == 0 and _foreign_only(result.stdout)
              and "lines 4-5 of 9" in result.stderr, "the range was not read as expected")

        step("(c) list two levels: links and denied entries are marked, never entered")
        result = harness(env, "workspace", "list", "--root", folder, "--depth", "2")
        check(result.returncode == 0 and "| .git [denied: denied_component]" in result.stdout
              and not any(line.startswith("| .git/") for line in result.stdout.splitlines()),
              "the listing did not mark .git")

        step("(d) a hostile file cannot imitate a harness line")
        result = harness(env, "workspace", "read", "hostile.txt", "--root", folder)
        check(result.returncode == 0 and _foreign_only(result.stdout)
              and "\x1b" not in result.stdout and "<U+001B>" in result.stdout
              and "<U+202E>" in result.stdout, "the hostile file was not made visible")
        check(result.stderr.count("\n") == 1, "file text reached stderr")

        cases = [
            ("a path outside", "../outside/secret.txt", "dot_component"),
            ("an absolute path", "/etc/hosts", "absolute"),
            (".env", ".env", "denied_name"),
            (".git/config", ".git/config", "denied_component"),
            ("a key file", "deploy.pem", "denied_name"),
            ("a credential inside a file", "config/settings.py", "credential_in_file"),
            ("a binary", "image.bin", "binary"),
            ("an over-size file", "big.txt", "too_large"),
            ("a case-variant name", "src/App.py", "name_not_exact"),
            ("a reserved Windows name", "NUL", "reserved_name"),
            ("an alternate data stream", "README.md:hidden", "colon"),
        ]
        if built.links:
            cases.append(("a symlink out", "src/escape.py", "link"))
        else:
            skipped.append("symlink out: this account cannot create symbolic links")
        if built.hard_link:
            cases.append(("a hard link", "notes.txt", "hard_link"))
        else:
            skipped.append("hard link: this file system has none")
        for title, relative, code in cases:
            step(f"(NO) {title}: {relative}")
            result = harness(env, "workspace", "read", relative, "--root", folder)
            check(result.returncode == 1 and result.stdout == ""
                  and result.stderr.startswith(f"error: refused: {code}"),
                  f"{title} was not refused with {code}")

        for title, target, code in [("the harness repository as root", str(ROOT),
                                     "harness_repo"),
                                    ("the data dir as root", str(data), "data_dir")]:
            step(f"(NO) {title}")
            result = harness(env, "workspace", "read", "README.md", "--root", target)
            check(result.returncode == 1 and result.stderr.startswith(f"error: refused: {code}"),
                  f"{title} was not refused")

        step("(e) the audit: one row per call, no path and no file text")
        conn = sqlite3.connect(data / "harness.sqlite3")
        try:
            rows = conn.execute("SELECT count(*) FROM tool_calls WHERE server = 'workspace'"
                                ).fetchone()[0]
            events = dict(conn.execute("SELECT code, count(*) FROM workspace_events "
                                       "GROUP BY code").fetchall())
            values = [str(v) for table in ("tool_calls", "workspace_events")
                      for row in conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
                      for v in row]
        finally:
            conn.close()
        print(f"tool_calls rows: {rows}; codes: {events}")
        check(rows == 3 + len(cases) + 2,  # `check` is not a tool call
              "not one audit row per call")
        check(not any(word in v for v in values
                      for word in ("hostile", "settings.py", "secret", builder.SENTINEL)),
              "the audit holds a path or file text")
        stored = b"".join(p.read_bytes() for p in data.rglob("*") if p.is_file())
        check(builder.SENTINEL.encode() not in stored, "file text was saved in the data dir")
    return skipped


if __name__ == "__main__":
    sys.exit(run(demo))
