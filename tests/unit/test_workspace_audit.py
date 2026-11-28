"""The audit of a work-folder call (workspace-tools D7, B1-5): no path, no text."""

from __future__ import annotations

import re
from pathlib import Path

from harness.storage.database import open_database
from harness.workspace import audit as audit_module
from harness.workspace.audit import path_hmac, record_call
from harness.workspace.codes import CODES

MIGRATION = (Path(audit_module.__file__).resolve().parent.parent / "storage" / "migrations"
             / "011_workspace_events.sql")


def test_the_migration_lists_exactly_the_codes():
    sql = MIGRATION.read_text(encoding="utf-8")
    listed = re.search(r"code IN\s*\((.*?)\)\)", sql, re.S).group(1)
    assert tuple(re.findall(r"'([a-z_]+)'", listed)) == CODES


def _rows(conn):
    calls = conn.execute("SELECT * FROM tool_calls").fetchall()
    events = conn.execute("SELECT * FROM workspace_events").fetchall()
    return calls, events


def test_each_outcome_leaves_its_rows(tmp_path: Path):
    conn = open_database(tmp_path / "data")
    key = b"k" * 32
    cases = [
        ("ok", False, ("allowed", "allowed", "completed", None)),
        ("dot_component", False, ("denied", "argument_invalid", "denied", None)),
        ("denied_name", False, ("denied", "argument_invalid", "denied", None)),
        ("link", False, ("allowed", "allowed", "failed", "tool_error")),
        ("credential_in_file", False, ("allowed", "allowed", "failed", "tool_error")),
        ("harness_repo", True, ("denied", "server_not_allowed", "denied", None)),
        ("workspace_changed", False, ("denied", "server_not_allowed", "denied", None)),
    ]
    for code, root_refused, expected in cases:
        call_id = record_call(conn, key, tool="read", canonical_args=b'{"path":"a/b.txt"}',
                              code=code, relative="secret-name/b.txt", result_bytes=None,
                              duration_ms=1, root_refused=root_refused)
        row = conn.execute(
            "SELECT decision, reason, status, error_code, server FROM tool_calls "
            "WHERE call_id = ?", (call_id,)).fetchone()
        assert tuple(row)[:4] == expected and row[4] == "workspace"
        event = conn.execute("SELECT code, path_hmac FROM workspace_events WHERE call_id = ?",
                             (call_id,)).fetchone()
        assert event[0] == code and event[1] == path_hmac(key, "secret-name/b.txt")


def test_no_row_holds_the_path_or_a_name(tmp_path: Path):
    conn = open_database(tmp_path / "data")
    record_call(conn, b"k" * 32, tool="read", canonical_args=b'{"path":"secret-name/b.txt"}',
                code="ok", relative="secret-name/b.txt", result_bytes=10, duration_ms=1)
    for table in ("tool_calls", "workspace_events"):
        for row in conn.execute(f"SELECT * FROM {table}").fetchall():  # noqa: S608 - test
            assert not any("secret-name" in str(value) for value in row)


def test_the_path_hmac_has_its_own_domain():
    key = b"k" * 32
    import hashlib
    import hmac

    plain = hmac.new(key, b"a.txt", hashlib.sha256).hexdigest()
    assert path_hmac(key, "a.txt") != plain and len(path_hmac(key, "a.txt")) == 64


def test_a_later_010_still_applies_after_011(tmp_path: Path):
    """The gap is harmless: `feature/code-mode-loop` will add 010 after 011 was applied."""
    from harness.storage.database import MIGRATIONS_DIR, connect, migrate

    shipped = tmp_path / "migrations"
    shipped.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        (shipped / path.name).write_text(path.read_text("utf-8"), "utf-8")
    data = tmp_path / "data"
    data.mkdir()
    conn = connect(data)
    assert migrate(conn, shipped)[-1] == 11
    (shipped / "010_later.sql").write_text("CREATE TABLE later_table (x INTEGER);\n", "utf-8")
    assert migrate(conn, shipped) == [10]
    conn.close()
