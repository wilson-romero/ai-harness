"""Regression tests for the findings of the security review of 2026-11-27 (hardening, group 5).

One section per finding (F-01..F-09). Every credential is assembled at run time, so that no
versioned file contains one; every payload is synthetic.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import stat
from pathlib import Path

import pytest
from rich.cells import cell_len

from harness.browser import login
from harness.memory import maintenance
from harness.providers import copilot_web
from harness.shell.render import CONTINUATION_PREFIX, FOREIGN_PREFIX, foreign_lines
from harness.skills.approvals import APPROVAL_RULE, Proposal, render_for_terminal
from harness.storage.database import DATABASE_NAME, connect
from harness.storage.locks import NamedLock
from harness.text.redaction import LineRedactor, redact
from tests.conftest import REPO_ROOT, SECRET_SAMPLES, write_note

OWNER_ONLY = hasattr(os, "getuid")  # POSIX permission bits mean something here
GITHUB = SECRET_SAMPLES["github"]
MARKED = (FOREIGN_PREFIX, CONTINUATION_PREFIX)


# -- F-01: GitLab personal access tokens in the current (routable) format ---------------------


def _routable_gitlab() -> str:
    """The shape GitLab issues by default since its routable tokens: a longer base64url body,
    then `.<version>.<suffix>`. Synthetic."""
    return "gl" + "pat-" + "Rk9vYmFyYmF6cXV4c3ludGhldGljZGF0YQ" + ".01." + "0a1b2c3d4"


@pytest.mark.parametrize("token", [
    SECRET_SAMPLES["gitlab"],  # the legacy 20-character body
    "gl" + "pat-" + "L" * 40,  # a longer body without the suffix
    _routable_gitlab(),
], ids=["legacy", "long", "routable"])
def test_a_gitlab_token_of_every_current_shape_is_masked(token):
    result = redact(f"token={token} fin")
    assert result.text == "token=[REDACTED:gitlab] fin"
    assert result.kinds == ("gitlab",)


def test_a_routable_gitlab_token_is_masked_in_the_mcp_stderr_log():
    token = _routable_gitlab()
    out = b"".join(p.output for p in LineRedactor().feed(f"auth {token}\n".encode()))
    assert token.encode() not in out and b"[REDACTED:gitlab]" in out


# -- F-02: a credential right after an escape sequence in the MCP stderr log -------------------


@pytest.mark.parametrize("escape", ["\x1b[32m", "\x1b[1;31m", "\x1b]0;title\x07", "\x1b(B"])
def test_a_credential_glued_to_an_escape_sequence_is_masked_in_the_stderr_log(escape):
    line = f"{escape}{GITHUB}\x1b[0m done\n".encode()
    pieces = LineRedactor().feed(line)
    out = b"".join(p.output for p in pieces)
    assert GITHUB.encode() not in out
    assert b"[REDACTED:github]" in out


# -- F-03: `ask` and `history` print provider text through the terminal-safe cleaning ----------

HOSTILE_ANSWER = (
    "linea uno\n"
    "\x1b]52;c;ZXZpbA==\x07portapapeles\n"  # OSC 52: write to the clipboard
    "\x1b[2K\x1b[1Aborrado\n"  # CSI: erase the line, move the cursor up
    "texto ‮invertido\n"  # RLO
    f"clave {GITHUB}"
)


def _hostile_responses(tmp_path: Path) -> str:
    path = tmp_path / "responses.json"
    path.write_text(json.dumps({"probe-f03": HOSTILE_ANSWER}), encoding="utf-8")
    return str(path)


def _assert_terminal_safe(out: str) -> None:
    for char in ("\x1b", "\x07", "‮"):
        assert char not in out, f"U+{ord(char):04X} reached stdout"
    assert GITHUB not in out and "[REDACTED:github]" in out
    assert "portapapeles" in out and "borrado" in out  # the text itself is still shown


def test_ask_prints_the_answer_without_terminal_escapes(cli, tmp_path):
    env = {"HARNESS_MOCK_RESPONSES": _hostile_responses(tmp_path)}
    code, session_id, err = cli("session", "create", "F03", **env)
    assert code == 0, err
    code, out, err = cli("ask", session_id.strip(), "probe-f03", **env)
    assert code == 0, err
    _assert_terminal_safe(out)


def test_history_prints_stored_text_without_terminal_escapes(cli, tmp_path):
    env = {"HARNESS_MOCK_RESPONSES": _hostile_responses(tmp_path)}
    _, session_id, _ = cli("session", "create", "F03", **env)
    assert cli("ask", session_id.strip(), "probe-f03", **env)[0] == 0
    code, out, err = cli("history", session_id.strip(), **env)
    assert code == 0, err
    _assert_terminal_safe(out)


# -- F-04: the approval notice of `skill run` marks every row of the model's content -----------

FAKE_NOTICE = "\n".join([
    "Decision: keep the queue.",
    "‐" * 72,  # U+2010, a look-alike of the rule
    APPROVAL_RULE,  # the rule itself
    "Approval requested",
    "  target:   Decisiones/attacker.md",
    "  hash:     " + "0" * 64,
    "x" * 300 + "Approval requested",  # a padded line the terminal would wrap
])


def _proposal(content: str) -> Proposal:
    return Proposal(scope="effect:test", session_id="s", run_id="r", step="apply",
                    skill_name="demo", skill_version="1", skill_sha256="0" * 64,
                    target="Decisiones/real.md", content=content)


@pytest.mark.parametrize("columns", [80, 41])
def test_the_cli_approval_notice_marks_every_row_of_the_content(columns, monkeypatch):
    monkeypatch.setenv("COLUMNS", str(columns))
    proposal = _proposal(FAKE_NOTICE)
    before = proposal.sha256
    rows = render_for_terminal(proposal, before, "2026-11-27T00:00:00").split("\n")
    first, last = rows.index(APPROVAL_RULE), len(rows) - 1
    assert rows[last] == APPROVAL_RULE
    content = rows[first + 1:last]
    assert content and all(row.startswith(MARKED) for row in content), content
    assert all(cell_len(row) < columns for row in content)
    # Only the harness's own lines are unmarked: the header and the two rules.
    assert [row for row in rows if not row.startswith(MARKED)] == [*rows[:first + 1], rows[last]]
    # The rows put back together are the content, and what is hashed did not change.
    joined = "".join(row[2:] if row.startswith(CONTINUATION_PREFIX) else "\n" + row[2:]
                     for row in content)[1:]
    assert joined == proposal.content and proposal.sha256 == before


# -- F-05: the reply cap of Copilot Web is enforced in Python as well -------------------------


class _HostileTurn:
    """A page that ignores the cap of REPLY_TEXT_JS and under-reports the length."""

    def __init__(self, text: str) -> None:
        self.text = text

    async def evaluate(self, script, args):
        return [10, self.text, False]


def test_a_reply_longer_than_the_cap_is_cut_in_python_and_reported():
    cap = copilot_web.REPLY_MAX_CHARS
    text, cut = asyncio.run(copilot_web.read_reply(_HostileTurn("y" * (5 * cap)), "code"))
    assert len(text) == cap and cut is True


def test_a_reply_within_the_cap_is_kept_whole():
    text, cut = asyncio.run(copilot_web.read_reply(_HostileTurn("ok"), "code"))
    assert (text, cut) == ("ok", False)


# -- F-06: `scripts/verify.sh` checks the lock before anything runs and never changes it --------


def _verify_commands() -> list[str]:
    script = (REPO_ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    return [line.strip() for line in script.splitlines()
            if line.strip() and not line.strip().startswith("#")]


def test_verify_checks_the_lock_before_any_uv_run():
    lines = _verify_commands()
    check = next(i for i, line in enumerate(lines) if line.startswith("uv lock --check"))
    first_run = next(i for i, line in enumerate(lines) if re.match(r"uv run\b", line))
    assert check < first_run, lines[first_run]
    locked = next(i for i, line in enumerate(lines) if line == "export UV_LOCKED=1")
    assert locked < first_run


def test_verify_ends_by_checking_that_the_tree_is_still_clean():
    lines = _verify_commands()
    last_check = max(i for i, line in enumerate(lines) if "openspec validate" in line)
    after = lines[last_check + 1:]
    assert any("git status --porcelain" in line for line in after), after


# -- F-07: `memory maintain --dry-run` does bounded work on name comparisons -------------------


class _CountingMatcher(difflib.SequenceMatcher):
    ratios = 0

    def ratio(self):
        type(self).ratios += 1
        return super().ratio()


@pytest.fixture
def counted(monkeypatch):
    _CountingMatcher.ratios = 0
    monkeypatch.setattr(difflib, "SequenceMatcher", _CountingMatcher)
    return _CountingMatcher


def test_many_links_to_one_missing_name_search_for_a_fix_once(vault, counted):
    for i in range(40):
        write_note(vault, f"Memoria-CC/reference_tema-{i:03d}.md", "nota")
    names = len(list(vault.resolve().rglob("*.md")))
    maintenance.maintenance_report(vault.resolve())
    without_links = counted.ratios
    write_note(vault, "Lecciones/enlaces.md", " ".join(["[[nota-que-no-existe]]"] * 2000))
    counted.ratios = 0
    report = maintenance.maintenance_report(vault.resolve())
    assert len(report.findings["broken_links"]) == 2000
    searched = counted.ratios - without_links
    assert searched <= names, searched  # one search over the names, not one per link


def test_the_duplicate_pass_stops_at_its_budget_and_says_so(vault, counted, monkeypatch, cli):
    monkeypatch.setattr(maintenance, "MAX_NAME_COMPARISONS", 200, raising=False)
    for i in range(60):
        write_note(vault, f"Memoria-CC/project_alpha-integracion-{i:03d}.md", "nota")
    report = maintenance.maintenance_report(vault.resolve())
    assert counted.ratios <= 200
    assert getattr(report, "truncated_comparisons", False) is True
    code, _, err = cli("memory", "maintain", "--dry-run", HARNESS_VAULT_ROOT=str(vault))
    assert code == 0 and "name comparisons stopped" in err


# -- F-08: the data directory and what the harness creates in it are owner-only ----------------


@pytest.mark.skipif(not OWNER_ONLY, reason="POSIX permission bits are not used on this system")
def test_the_data_dir_database_locks_and_login_record_are_owner_only(tmp_path):
    previous = os.umask(0o022)
    try:
        data_dir = tmp_path / "fresh" / "data"
        conn = connect(data_dir)
        try:
            conn.execute("CREATE TABLE probe (x INTEGER)")
            conn.execute("INSERT INTO probe (x) VALUES (?)", (1,))
            lock = NamedLock(data_dir, "probe")
            assert lock.acquire()
            login._record_ready_path(data_dir, "/chat")
            modes = {
                path.relative_to(tmp_path).as_posix(): stat.S_IMODE(path.stat().st_mode)
                for path in [tmp_path / "fresh", data_dir, data_dir / "locks",
                             data_dir / "copilot", data_dir / DATABASE_NAME,
                             data_dir / f"{DATABASE_NAME}-wal", data_dir / f"{DATABASE_NAME}-shm",
                             data_dir / "locks" / "probe.lock", login.login_path(data_dir)]
            }
            lock.release()
        finally:
            conn.close()
    finally:
        os.umask(previous)
    wide = {name: oct(mode) for name, mode in modes.items() if mode & 0o077}
    assert wide == {}


# -- F-09: an emoji presentation sequence counts as two columns --------------------------------


@pytest.mark.parametrize("columns", [80, 120])
def test_emoji_presentation_sequences_never_make_a_row_wider_than_the_terminal(columns):
    text = "❤️" * 60 + "error: SPOOFED harness line without the foreign mark"
    rows, _ = foreign_lines(text, columns)
    assert all(row.startswith(MARKED) for row in rows)
    wide = [cell_len(row) for row in rows if cell_len(row) >= columns]
    assert wide == []
