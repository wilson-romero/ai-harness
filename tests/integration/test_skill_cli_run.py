"""`skill run|status|resume|cancel` as real processes (skill-engine D10, D16)."""

import json

import pytest

from tests.conftest import query, run_main, spawn_main, wait_for_running
from tests.skill_support import GOOD_ECHO, copy_skills


@pytest.fixture
def env(tmp_path):
    root = copy_skills(tmp_path)
    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps({"tarea: demo-echo/draft": GOOD_ECHO}), encoding="utf-8")
    return {"HARNESS_SKILLS_DIR": str(root), "HARNESS_MOCK_RESPONSES": str(responses)}


def _session(data_dir, env) -> str:
    result = run_main(data_dir, "session", "create", "Demo", **env)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _without_approval(env):
    from pathlib import Path

    path = Path(env["HARNESS_SKILLS_DIR"]) / "demo-echo" / "workflow.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["steps"] = data["steps"][:2]
    path.write_text(json.dumps(data), encoding="utf-8")


def test_complete_run_with_the_mock(data_dir, env):
    _without_approval(env)
    session = _session(data_dir, env)
    result = run_main(data_dir, "skill", "run", "demo-echo", "--session", session,
                      "--input", "text=hola", **env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == GOOD_ECHO
    assert query(data_dir, "SELECT step_key, status FROM skill_steps ORDER BY position") == [
        ("draft", "completed"), ("check", "completed")]


def test_traversal_name_in_run(data_dir, env):
    result = run_main(data_dir, "skill", "run", "..\\otro", "--session", "x", **env)
    assert result.returncode == 1 and "invalid skill name" in result.stderr
    assert not (data_dir / "harness.sqlite3").exists()


def test_missing_session(data_dir, env):
    _session(data_dir, env)
    result = run_main(data_dir, "skill", "run", "demo-echo", "--session",
                      "01a20e71-0b12-7322-b356-41ae571d7513", "--input", "text=x", **env)
    assert result.returncode == 1 and "does not exist" in result.stderr
    assert query(data_dir, "SELECT count(*) FROM skill_runs") == [(0,)]


def test_input_file_too_large(data_dir, env, tmp_path):
    session = _session(data_dir, env)
    big = tmp_path / "grande.md"
    big.write_bytes(b"x" * 65_537)
    result = run_main(data_dir, "skill", "run", "demo-echo", "--session", session,
                      "--input-file", f"text={big}", **env)
    assert result.returncode == 2 and "larger than 65536 bytes" in result.stderr
    assert query(data_dir, "SELECT count(*) FROM skill_runs") == [(0,)]
    assert query(data_dir, "SELECT count(*) FROM requests") == [(0,)]


@pytest.mark.parametrize("ttl", ["30", "7200"])
def test_ttl_out_of_range_creates_no_run(data_dir, env, ttl):
    session = _session(data_dir, env)
    result = run_main(data_dir, "skill", "run", "demo-echo", "--session", session,
                      "--input", "text=x", HARNESS_APPROVAL_TTL_S=ttl, **env)
    assert result.returncode == 1 and "HARNESS_APPROVAL_TTL_S" in result.stderr
    assert query(data_dir, "SELECT count(*) FROM skill_runs") == [(0,)]


def test_invalid_responses_file_creates_no_run(data_dir, env, tmp_path):
    session = _session(data_dir, env)
    bad = tmp_path / "malo.json"
    bad.write_text('{"a": 1}', encoding="utf-8")
    result = run_main(data_dir, "skill", "run", "demo-echo", "--session", session,
                      "--input", "text=x", **{**env, "HARNESS_MOCK_RESPONSES": str(bad)})
    assert result.returncode == 1 and "HARNESS_MOCK_RESPONSES" in result.stderr
    assert query(data_dir, "SELECT count(*) FROM skill_runs") == [(0,)]


def test_non_interactive_run_waits_and_status_after_restart(data_dir, env):
    session = _session(data_dir, env)
    result = run_main(data_dir, "skill", "run", "demo-echo", "--session", session,
                      "--input", "text=hola", **env)
    assert result.returncode == 3, result.stderr
    run_id = query(data_dir, "SELECT run_id FROM skill_runs")[0][0]
    assert f"skill resume {run_id}" in result.stderr
    assert query(data_dir, "SELECT status FROM approvals") == [("pending",)]
    status = run_main(data_dir, "skill", "status", run_id, **env)
    assert status.returncode == 0
    assert "status: awaiting_approval" in status.stdout
    assert "step: confirm approval attempt 1 awaiting_approval" in status.stdout
    approval_id, proposal_hash = query(data_dir, "SELECT approval_id, proposal_hash FROM approvals")[0]
    assert f"approval: confirm pending id {approval_id} expires" in status.stdout
    assert "Texto resumido" not in status.stdout
    # 8.2: the code (any part of the hash) is shown only inside the interactive prompt.
    for text in (result.stdout, result.stderr, status.stdout, status.stderr):
        assert proposal_hash[:8] not in text
    assert approval_id in result.stderr
    output = run_main(data_dir, "skill", "status", run_id, "--output", **env)
    assert output.stdout.strip().endswith("(output not stored)")


def test_process_killed_during_an_llm_step(data_dir, env):
    session = _session(data_dir, env)
    process = spawn_main(data_dir, "skill", "run", "demo-echo", "--session", session,
                         "--input", "text=x", HARNESS_MOCK_DELAY_MS="30000", **env)
    try:
        wait_for_running(data_dir, session)
        live = run_main(data_dir, "skill", "status",
                        query(data_dir, "SELECT run_id FROM skill_runs")[0][0], **env)
        assert "status: running" in live.stdout  # a live run is not touched
    finally:
        process.kill()
        process.wait(timeout=10)
    run_id = query(data_dir, "SELECT run_id FROM skill_runs")[0][0]
    status = run_main(data_dir, "skill", "status", run_id, **env)
    assert "status: uncertain" in status.stdout
    assert "step: draft llm attempt 1 uncertain" in status.stdout
    assert query(data_dir, "SELECT status FROM requests") == [("uncertain",)]
    linked = query(data_dir, "SELECT request_id IS NOT NULL FROM skill_steps WHERE step_key = 'draft'")
    assert linked == [(1,)]
    refused = run_main(data_dir, "skill", "resume", run_id, "--input", "text=x", **env)
    assert refused.returncode == 1 and "--retry-step draft" in refused.stderr
    retried = run_main(data_dir, "skill", "resume", run_id, "--input", "text=x",
                       "--retry-step", "draft", **env)
    assert retried.returncode == 3, retried.stderr


def test_cancel_then_new_run(data_dir, env):
    session = _session(data_dir, env)
    run_main(data_dir, "skill", "run", "demo-echo", "--session", session, "--input", "text=x",
             **env)
    run_id = query(data_dir, "SELECT run_id FROM skill_runs")[0][0]
    cancelled = run_main(data_dir, "skill", "cancel", run_id, **env)
    assert cancelled.returncode == 0 and "cancelled" in cancelled.stdout
    again = run_main(data_dir, "skill", "cancel", run_id, **env)
    assert again.returncode == 1
    second = run_main(data_dir, "skill", "run", "demo-echo", "--session", session,
                      "--input", "text=x", **env)
    assert second.returncode == 3
