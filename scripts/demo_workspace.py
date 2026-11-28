"""Demo of workspace-tools slices B1 and B2: the work folder, its confinement, `read`/`list`
by CLI (B1), and `/workspace` with its reads in `/plan` and `/agent` (B2).

Usage: uv run python scripts/demo_workspace.py
       uv run python scripts/demo_workspace.py --prepare DIR

Same code on every platform. The synthetic work folder is built in a temporary directory from
`tests/fixtures/workspace/` (no real project content), with its own data directory; nothing
outside them is read or written. B1 runs `main.py workspace` as a subprocess; B2 drives the
plain conversation in this process with the scripted Mock and the scripted terminal the tests
use (a Mock marked not synthetic stands for a provider outside the machine: no real provider
is contacted). Every refusal case must say NO. The second form runs nothing: it builds the
synthetic folder and a Mock script in DIR (outside the repository) and prints the command
that opens `chat` over them, to try `/workspace`, `/plan` and `/agent` by hand.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path

from demo_common import ROOT, base_env, check, harness, header, run, step

sys.path.insert(0, str(ROOT))

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

        demo_b2(base, built)
    return skipped


# -- B2: /workspace, /plan and /agent with the scripted Mock -------------------------------------

QUESTION = "¿qué hace el módulo de demo?"
FINAL = "Respuesta final sintetica: greet saluda y add suma."


def _step(sid: str, tool: str, **args) -> dict:
    return {"id": sid, "server": "workspace", "tool": tool, "args": args}


def _turn(k: int) -> str:
    return f"vuelta {k} de"


def demo_b2(base: Path, built) -> None:
    import asyncio

    from harness.mcp.config import LoadedConfig
    from harness.providers.mock import MockProvider
    from harness.storage.database import open_database
    from tests.plan_support import plan_reply
    from tests.shell_support import CODE, ScriptedTerminal, make_conversation

    class Recording(MockProvider):
        """The Mock, keeping every prompt (the oracle of what was sent)."""

        def __init__(self, responses: dict, synthetic: bool = True) -> None:
            super().__init__(responses=responses)
            self.synthetic_content = synthetic
            self.prompts: list[str] = []

        async def ask(self, request, on_sent, *, on_mode=None) -> str:
            self.prompts.append(request.prompt)
            return await super().ask(request, on_sent, on_mode=on_mode)

    data = base / "data-b2"
    folder = str(built.root)

    def converse(lines, responses, *, synthetic=True, approvals=()):
        conn = open_database(data)
        try:
            provider = Recording(responses, synthetic)
            terminal = ScriptedTerminal([f"/workspace {folder}", *lines], list(approvals))
            conversation, _, _ = make_conversation(
                conn, data, terminal, provider, columns=10_000,
                environ={"HARNESS_LOOP_PROVIDERS": "mock"},
                mcp_config=lambda: LoadedConfig(None))
            asyncio.run(conversation.run())
        finally:
            conn.close()
        print(terminal.text)
        return terminal.text, provider

    def query(sql: str) -> list[tuple]:
        conn = sqlite3.connect(data / "harness.sqlite3")
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def last_loop() -> tuple:
        return query("SELECT status, stop_reason, turns FROM loop_runs ORDER BY rowid DESC "
                     "LIMIT 1")[0]

    app, util = _step("a", "read", path="src/app.py"), _step("b", "read", path="src/util.py")

    step("(B2-a) /workspace: set and shown; the repository and the data dir refused")
    text, _ = converse(["/workspace", f"/workspace {ROOT}", f"/workspace {data}", "/status"], {})
    check("/plan and /agent can now read it" in text and "/workspace refused: harness_repo"
          in text and "/workspace refused: data_dir" in text,
          "the folder was not set, or a protected folder was accepted")
    check(text.count(f"workspace: {Path(folder).resolve()}") >= 2, "the folder is not shown")

    step("(B2-b) /plan reads two files by rule, shown only here")
    text, provider = converse([f"/plan {QUESTION}"], {QUESTION: plan_reply(app, util)})
    check("running plan:" in text and "Plan approval requested" not in text,
          "the reads did not run by rule")
    check("def greet(name: str) -> str:" in text and "def add(a: int, b: int)" in text,
          "the two files were not shown")
    check(len(provider.prompts) == 1 and "workspace.read(" in provider.prompts[0]
          and folder not in provider.prompts[0], "the catalogue named the path or more was sent")
    check(query("SELECT COUNT(*) FROM tool_calls WHERE server = 'workspace' AND plan_id IS NOT "
                "NULL AND status = 'completed'") == [(2,)], "not two audited plan reads")

    step("(B2-c) /agent: list, then read, then the answer, in two turns with results")
    text, provider = converse([f"/agent {QUESTION}"], {
        _turn(1): plan_reply(_step("l", "list")), _turn(2): plan_reply(app), _turn(3): FINAL})
    check(len(provider.prompts) == 3 and "| src/" in provider.prompts[1]
          and "def greet(name: str) -> str:" in provider.prompts[2],
          "the listing and the file did not go back turn by turn")
    check("Plan approval requested" not in text and "every argument is bounded" in text,
          "a bounded path should run by rule inside /agent")
    check(all(prompt in text.replace("\n| ", "\n") for prompt in provider.prompts[1:]),
          "a turn was not shown exactly as sent")
    check(last_loop() == ("completed", "answer", 3), "the loop did not end answered")

    refusals = [("(NO) .env", _step("e", "read", path=".env"), "refused: denied_name"),
                ("(NO) .git/config", _step("g", "read", path=".git/config"),
                 "refused: denied_component"),
                ("(NO) a key file", _step("k", "read", path="deploy.pem"), "refused: denied_name"),
                ("(NO) a case-variant name", _step("c", "read", path="src/App.py"),
                 "refused: name_not_exact"),
                ("(NO) a binary", _step("i", "read", path="image.bin"), "refused: binary"),
                ("(NO) ../ outside", _step("o", "read", path="../outside/secret.txt"),
                 "plan refused: argument_invalid"),
                ("(NO) a path with a space", _step("s", "read", path="a b.txt"),
                 "plan refused: argument_invalid")]
    if built.links:
        refusals.append(("(NO) a symlink out", _step("y", "read", path="src/escape.py"),
                         "refused: link"))
    for title, plan_step, said in refusals:
        step(f"(B2) {title} in a /plan")
        text, _ = converse([f"/plan {QUESTION}"], {QUESTION: plan_reply(plan_step)})
        check(said in text and "secret" not in text.replace("../outside/secret.txt", ""),
              f"{title} was not refused with {said}")

    step("(B2-d) consent off: a provider outside the machine gets nothing of the folder")
    text, provider = converse([f"/agent {QUESTION}"], {_turn(1): plan_reply(app),
                                                       _turn(2): FINAL}, synthetic=False)
    check("not sent: no consent for this folder" in text and len(provider.prompts) == 1,
          "file content went without the folder's consent")
    check(last_loop() == ("stopped", "send_not_approved", 1), "the loop did not stop")

    step("(B2-e) consent on through the box, then the loop's own first-send box; then revoked")
    text, provider = converse(["/workspace send on", f"/agent {QUESTION}"],
                              {_turn(1): plan_reply(app), _turn(2): FINAL}, synthetic=False,
                              approvals=[CODE, CODE])
    check("Send consent requested" in text and text.count("Send approval requested") == 1
          and len(provider.prompts) == 2 and "def greet" in provider.prompts[1],
          "with consent the results did not go after the loop's box")
    text, provider = converse(["/workspace send off", f"/agent {QUESTION}"],
                              {_turn(1): plan_reply(app), _turn(2): FINAL}, synthetic=False)
    check("not sent: no consent for this folder" in text and len(provider.prompts) == 1,
          "a revoked consent still sent")

    step("(B2-f) what is stored: no path and no file text")
    values = [str(v) for table in ("tool_calls", "workspace_events", "workspace_consents",
                                   "audit_events", "loop_turns")
              for row in query(f"SELECT * FROM {table}")  # noqa: S608
              for v in row]
    check(not any(folder in v or "demo-alpha" in v or "greet" in v for v in values),
          "a row holds the folder's path or a file's text")
    print(f"workspace_consents: {query('SELECT provider, state FROM workspace_consents')}")


def prepare(target: Path) -> int:
    """Build the synthetic folder and a Mock script in `target` for `/workspace` by hand."""
    import json
    import shlex

    from tests.plan_support import plan_reply

    target = target.resolve()
    if target == ROOT or ROOT in target.parents:
        print("error: DIR must be outside the repository", file=sys.stderr)
        return 2
    target.mkdir(parents=True, exist_ok=True)
    built = _builder().build(target / "base")
    app, util = _step("a", "read", path="src/app.py"), _step("b", "read", path="src/util.py")
    responses = target / "mock-responses.json"
    responses.write_text(json.dumps({
        QUESTION: plan_reply(app, util), _turn(1): plan_reply(_step("l", "list")),
        _turn(2): plan_reply(app), _turn(3): FINAL}, ensure_ascii=False), encoding="utf-8")
    env = {"HARNESS_DATA_DIR": target / "data", "HARNESS_PROVIDER": "mock",
           "HARNESS_MOCK_RESPONSES": responses, "HARNESS_LOOP_PROVIDERS": "mock"}
    print(" ".join(f"{name}={shlex.quote(str(value))}" for name, value in env.items())
          + " uv run python main.py chat")
    print(f"then type: /workspace {shlex.quote(str(built.root))}")
    print(f"           /plan {QUESTION}")
    print(f"           /agent dime {QUESTION}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--prepare":
        sys.exit(prepare(Path(sys.argv[2])))
    sys.exit(run(demo))
