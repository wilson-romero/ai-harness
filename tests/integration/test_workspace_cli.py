"""`main.py workspace check|read|list --root` (workspace-tools slice B1), end to end."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from harness.cli import main
from harness.storage.database import DATABASE_NAME
from harness.workspace.root import HARNESS_REPO
from tests.workspace_support import built, builder  # noqa: F401 - fixtures


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("HARNESS_DATA_DIR", str(data))
    monkeypatch.delenv("HARNESS_VAULT_ROOT", raising=False)
    monkeypatch.delenv("HARNESS_PROVIDER", raising=False)
    return data


def run(capsys, *args: str) -> tuple[int, str, str]:
    code = main(["workspace", *args])
    out, err = capsys.readouterr()
    return code, out, err


def test_read_prints_prefixed_lines_and_a_summary(built, env, capsys):
    code, out, err = run(capsys, "read", "src/app.py", "--root", str(built.root))
    assert code == 0
    assert out.splitlines()[0] == '|      1  """demo-alpha: a synthetic module."""'
    assert all(line.startswith("|") for line in out.splitlines())
    assert err.startswith("read: src/app.py lines 1-9 of 9, sha256 ")


def test_a_hostile_file_cannot_imitate_a_harness_line(built, env, capsys):
    for relative in ("README.md", "hostile.txt"):
        code, out, err = run(capsys, "read", relative, "--root", str(built.root))
        assert code == 0
        assert all(line.startswith("|") for line in out.splitlines())
        assert "\x1b" not in out + err and "‮" not in out + err
        # stderr holds only the harness's own summary line.
        assert err.count("\n") == 1 and err.startswith(f"read: {relative} ")


@pytest.mark.parametrize(("relative", "code"), [
    ("../outside/secret.txt", "dot_component"),
    ("/etc/hosts", "absolute"),
    (".env", "denied_name"),
    (".git/config", "denied_component"),
    ("deploy.pem", "denied_name"),
    ("config/settings.py", "credential_in_file"),
    ("image.bin", "binary"),
    ("big.txt", "too_large"),
    ("src/App.py", "name_not_exact"),
    ("NUL", "reserved_name"),
    ("a.txt:stream", "colon"),
])
def test_refusals_exit_1_with_the_reason_and_print_nothing(built, env, capsys,
                                                          relative: str, code: str):
    status, out, err = run(capsys, "read", relative, "--root", str(built.root))
    assert status == 1 and out == ""
    assert err.startswith(f"error: refused: {code}: ") and err.count("\n") == 1


def test_a_link_out_is_refused(built, env, capsys):
    if not built.links:
        pytest.skip("cannot create symbolic links here")
    status, out, err = run(capsys, "read", "src/escape.py", "--root", str(built.root))
    assert status == 1 and out == "" and err.startswith("error: refused: link")


@pytest.mark.parametrize("which", ["repo", "data"])
def test_the_harness_repo_and_the_data_dir_are_refused_as_root(built, env, capsys, which):
    env.mkdir(parents=True, exist_ok=True)
    target = HARNESS_REPO if which == "repo" else env
    status, _, err = run(capsys, "read", "README.md", "--root", str(target))
    assert status == 1
    assert err.startswith("error: refused: " + ("harness_repo" if which == "repo" else "data_dir"))


def test_check_accepts_and_refuses(built, env, capsys):
    status, _, err = run(capsys, "check", "--root", str(built.root))
    assert status == 0 and err.startswith("workspace: accepted ")
    status, _, err = run(capsys, "check", "--root", "relative/path")
    assert status == 1 and err.startswith("error: refused: not_absolute")


def test_list_prints_entries_and_marks(built, env, capsys):
    status, out, err = run(capsys, "list", "--root", str(built.root))
    assert status == 0
    assert "| .git [denied: denied_component]" in out.splitlines()
    assert "| src/" in out.splitlines()
    assert err.startswith("list: ., ")


@pytest.mark.parametrize("args", [["read", "x", "--limit", "401"], ["read", "x", "--offset", "0"],
                                  ["list", "--depth", "4"]])
def test_bad_ranges_are_usage_errors(built, env, capsys, args):
    status, _, _ = run(capsys, *args, "--root", str(built.root))
    assert status == 2


def test_every_call_is_audited_without_path_or_text(built, env, capsys):
    run(capsys, "read", "hostile.txt", "--root", str(built.root))
    run(capsys, "read", ".env", "--root", str(built.root))
    run(capsys, "read", "src/escape.py", "--root", str(built.root))
    run(capsys, "list", "--root", str(built.root))
    conn = sqlite3.connect(env / DATABASE_NAME)
    rows = conn.execute("SELECT t.tool, t.decision, t.status, e.code FROM tool_calls t "
                        "JOIN workspace_events e USING (call_id) ORDER BY t.created_at").fetchall()
    codes = [r[3] for r in rows]
    assert codes[0] == "ok" and codes[1] == "denied_name" and codes[3] == "ok"
    assert codes[2] in ("link", "not_found")  # not_found where links cannot be created
    every_value = []
    for table in ("tool_calls", "workspace_events"):
        for row in conn.execute(f"SELECT * FROM {table}").fetchall():  # noqa: S608 - test
            every_value += [str(v) for v in row]
    assert not any(word in value for value in every_value
                   for word in ("hostile", ".env", "escape", builder.SENTINEL))


def test_nothing_of_a_file_is_saved_in_the_data_dir(built, env, capsys):
    run(capsys, "read", "hostile.txt", "--root", str(built.root))
    for path in env.rglob("*"):
        if path.is_file():
            assert builder.SENTINEL.encode() not in path.read_bytes(), path


def test_the_command_runs_as_a_separate_process(built, tmp_path: Path):
    result = subprocess.run(
        [sys.executable, "main.py", "workspace", "read", "src/util.py", "--root", str(built.root)],
        cwd=HARNESS_REPO, capture_output=True, text=True, encoding="utf-8", timeout=60,
        env={"HARNESS_DATA_DIR": str(tmp_path / "data"), "PYTHONUTF8": "1",
             "PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["|      1  def add(a: int, b: int) -> int:",
                                          "|      2      return a + b"]
