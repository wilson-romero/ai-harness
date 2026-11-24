"""The public-repository guard must say NO to each kind of leak, and YES to clean content.

Every bad sample is assembled at run time so that this file itself stays clean.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_public_safety.py"

_spec = importlib.util.spec_from_file_location("check_public_safety", SCRIPT)
guard = importlib.util.module_from_spec(_spec)
sys.modules["check_public_safety"] = guard
_spec.loader.exec_module(guard)

A = "A" * 36
BAD_LINES = {
    "AWS access key": "key = " + "AKIA" + "ABCDEFGHIJKLMNOP",
    "GitHub token": "gh" + "p_" + A,
    "API key (sk-)": "s" + "k-" + A,
    "Slack token": "xox" + "b-" + "1234567890-abcdef",
    "Google API key": "AI" + "za" + "B" * 35,
    "private key block": "-----BEGIN RSA " + "PRIVATE KEY-----",
    "JWT": "ey" + "J" + "a" * 20 + ".ey" + "J" + "b" * 20 + "." + "c" * 20,
    "bearer token": "Authorization: Bear" + "er " + A,
    "credentials in URL": "postgres://admin:" + "hunter2222" + "@db.internal/app",
    "connection string": "Server=x;Database=y;Pass" + "word=" + "S3cretValue;",
    "assigned secret": "pass" + "word = " + '"correct-horse-battery"',
    "personal path": "/Us" + "ers/" + "someone/Documents/notes.md",
    "email address": "contact " + "someone" + "@" + "corp-domain.io",
    "IP address": "host 10." + "20.30.40",
}


@pytest.mark.parametrize("rule", sorted(BAD_LINES))
def test_each_rule_says_no(rule):
    findings = guard.check_text("sample.txt", "clean line\n" + BAD_LINES[rule] + "\n", [])
    assert rule in {f.rule for f in findings}
    assert all(f.line == 2 for f in findings)


def test_windows_personal_path_is_caught():
    line = "C:" + "\\Users\\" + "someone\\vault"
    assert [f.rule for f in guard.check_text("a.md", line, [])] == ["personal path"]


def test_clean_content_passes():
    text = "\n".join(
        [
            "HARNESS_DATA_DIR=./data",
            "reach us at dev@example.com, listen on 127.0.0.1",
            "version 3.14.8 and sqlite 3.53.1",
            "token = settings.token",
            'password = ""',
            "uv run python main.py ask SESSION_ID",
        ]
    )
    assert guard.check_text("README.md", text, []) == []


def test_allow_marker_skips_only_its_line():
    bad = BAD_LINES["IP address"]
    text = f"{bad}  # public-safety: allow\n{bad}\n"
    assert [f.line for f in guard.check_text("a.txt", text, [])] == [2]


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "config/.env.local",
        "data/harness.sqlite3",
        "x/harness.sqlite3-wal",
        "models/corporate.qea",
        "models/legacy.eapx",
        "keys/server.pem",
        "probe/trace.zip",
        "probe/session.har",
        "profile/storage_state.json",
        "tests/fixtures/screenshot.png",
        "run.log",
    ],
)
def test_forbidden_paths_say_no(path):
    assert guard.check_path(path), path


@pytest.mark.parametrize(
    "path", [".env.example", "docs/c4/context.png", "harness/storage/database.py", "uv.lock"]
)
def test_allowed_paths_pass(path):
    assert guard.check_path(path) == []


def test_denylist_matches_without_printing_the_term(tmp_path, capsys):
    term = "Acme" + "Corporativa"
    denylist = tmp_path / "denylist.txt"
    denylist.write_text(f"# local only\n{term}\n", encoding="utf-8")
    sample = tmp_path / "note.md"
    sample.write_text(f"Diagrama para {term.upper()} aprobado\n", encoding="utf-8")

    terms, _, configured = guard.load_denylist({guard.DENYLIST_ENV: str(denylist)})
    assert configured and terms == [term]
    findings = guard.scan([(str(sample), sample.read_bytes())], terms)
    assert [f.rule for f in findings] == ["local denylist term #1"]
    assert term.lower() not in str(findings[0]).lower()


def test_denylist_matches_whole_words_only():
    term = "ac" + "me"
    hits = lambda line, terms: len(guard.check_text("a.md", line, terms))
    assert hits("contrato con ACME firmado", [term]) == 1
    assert hits("acme-portal.internal", [term]) == 1
    assert hits("la academia y el acmeismo", [term]) == 0


def test_case_sensitive_term_spares_the_ordinary_word():
    name = "Cla" + "ra"  # a name that is also an ordinary word in lower case
    hits = lambda line: len(guard.check_text("a.md", line, ["cs:" + name]))
    assert hits(f"Reunion con {name} el lunes") == 1
    assert hits("una respuesta " + name.lower() + " y directa") == 0
    # Without the prefix the ordinary word is flagged too: that is the difference.
    assert len(guard.check_text("a.md", "una respuesta " + name.lower(), [name])) == 1


def test_missing_denylist_is_reported_not_hidden(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "README.md"],
        cwd=REPO_ROOT,
        env={"PATH": "", guard.DENYLIST_ENV: str(tmp_path / "absent.txt")},
        capture_output=True,
        text=True,
    )
    assert "WARNING no local denylist" in result.stderr


def test_lock_file_content_is_not_scanned():
    assert guard.check_text("uv.lock", BAD_LINES["GitHub token"], []) == []


def test_the_repository_itself_is_clean():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_script_fails_on_a_bad_file(tmp_path):
    bad = tmp_path / "leak.txt"
    bad.write_text(BAD_LINES["private key block"] + "\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(bad)], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "private key block" in result.stderr and "FAIL" in result.stderr
