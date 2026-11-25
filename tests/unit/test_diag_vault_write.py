"""`scripts/diag_vault_write.py`: the check Wilson runs in his OneDrive folder (task 7.10)."""

from __future__ import annotations

import subprocess
import sys

from tests.conftest import REPO_ROOT, fingerprint


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "scripts/diag_vault_write.py", *args], cwd=REPO_ROOT,
                          capture_output=True, text=True, timeout=60)


def test_it_checks_the_primitives_and_leaves_the_folder_as_it_was(tmp_path):
    folder = tmp_path / "carpeta de prueba"
    folder.mkdir()
    (folder / "existente.md").write_text("no tocar\n", encoding="utf-8")
    before = fingerprint(folder)
    result = _run(str(folder))
    assert result.returncode == 0, result.stderr
    values = dict(line.split(": ", 1) for line in result.stdout.splitlines() if ": " in line)
    for key in ("exclusive_create_ok", "exclusive_create_refuses_existing", "write_fsync_ok",
                "hard_link_ok", "link_refuses_existing", "existing_kept",
                "fstat_lstat_same_inode", "unlink_temp_ok", "note_intact", "cleanup_ok"):
        assert values[key] == "true", key
    assert values["link_count_after_link"] == "2" and values["link_count_after_unlink"] == "1"
    assert {k for k in values if k.startswith("ms_")} >= {"ms_exclusive_create", "ms_link"}
    # Nothing of the folder changed, nothing left behind, and no path in what is pasted back.
    assert {k: v for k, v in fingerprint(folder).items() if k != ""} == before
    assert str(tmp_path) not in result.stdout and "carpeta" not in result.stdout


def test_a_missing_folder_is_a_usage_error(tmp_path):
    result = _run(str(tmp_path / "no-existe"))
    assert result.returncode == 2 and result.stdout == ""
