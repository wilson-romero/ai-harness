"""`skill list` and `skill show` (skill-engine D16; spec skill-definition)."""

import shutil

from harness.providers.mock import MockProvider
from tests.conftest import REPO_ROOT, query, run_main

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "skills"


def test_valid_skill_listed_in_a_subprocess(data_dir):
    result = run_main(data_dir, "skill", "list", HARNESS_SKILLS_DIR=str(FIXTURES))
    assert result.returncode == 0, result.stderr
    lines = {line.split("\t")[0]: line.split("\t") for line in result.stdout.splitlines()}
    assert lines["demo-echo"][1:3] == ["1.0.0", "valid"]
    assert "Resume un texto" in lines["demo-echo"][3]
    # Invalid skills are listed with their reason without hiding the others.
    assert lines["bad-script"][2] == "invalid" and "unexpected file" in lines["bad-script"][3]
    assert lines["bad-tool-kind"][2] == "invalid" and "unknown step kind" in lines["bad-tool-kind"][3]
    assert lines["demo-json"][2] == "valid"


def test_empty_or_missing_root(data_dir, tmp_path):
    result = run_main(data_dir, "skill", "list", HARNESS_SKILLS_DIR=str(tmp_path / "nada"))
    assert result.returncode == 0 and result.stdout.strip() == "No skills."


def test_relative_skills_dir_is_refused(data_dir):
    result = run_main(data_dir, "skill", "list", HARNESS_SKILLS_DIR="skills")
    assert result.returncode == 1 and "HARNESS_SKILLS_DIR" in result.stderr


def test_show_without_effects(cli, data_dir, monkeypatch):
    calls = []
    original = MockProvider.ask

    async def counting(self, request, on_sent):
        calls.append(request)
        return await original(self, request, on_sent)

    monkeypatch.setattr(MockProvider, "ask", counting)
    code, _, _ = cli("session", "create", "Demo")
    assert code == 0
    code, out, err = cli("skill", "show", "demo-echo", HARNESS_SKILLS_DIR=str(FIXTURES))
    assert code == 0, err
    steps = [line for line in out.splitlines() if line.startswith("step ")]
    assert [line.split()[2] for line in steps] == ["draft", "check", "confirm"]
    assert "refs=inputs.text" in steps[0] and "effect=none" in steps[2]
    assert "sha256: " in out and "version: 1.0.0" in out
    assert query(data_dir, "SELECT count(*) FROM skill_runs") == [(0,)]
    assert calls == []


def test_show_invalid_skill_fails_with_its_reasons(data_dir):
    result = run_main(data_dir, "skill", "show", "bad-helper", HARNESS_SKILLS_DIR=str(FIXTURES))
    assert result.returncode == 1
    assert "unexpected file: templates/helper.py" in result.stdout
    assert "Traceback" not in result.stderr


def test_show_missing_skill(data_dir):
    result = run_main(data_dir, "skill", "show", "no-existe", HARNESS_SKILLS_DIR=str(FIXTURES))
    assert result.returncode == 1 and "does not exist" in result.stderr


def test_changing_a_template_changes_the_shown_hash(data_dir, tmp_path):
    root = tmp_path / "skills"
    shutil.copytree(FIXTURES / "demo-echo", root / "demo-echo")

    def shown() -> tuple[str, str]:
        out = run_main(data_dir, "skill", "show", "demo-echo", HARNESS_SKILLS_DIR=str(root)).stdout
        fields = dict(line.split(": ", 1) for line in out.splitlines() if ": " in line)
        return fields["sha256"], fields["version"]

    before = shown()
    template = root / "demo-echo" / "templates" / "draft.md"
    template.write_text(template.read_text(encoding="utf-8").replace("Resume", "Resumé"),
                        encoding="utf-8")
    after = shown()
    assert after[0] != before[0] and after[1] == before[1]
