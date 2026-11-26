"""What a skill is on disk and when it is refused (skill-engine D3-D5, D14; SEC-14)."""

import json
import os
import shutil
from pathlib import Path

import pytest

from harness.core.errors import InvalidInput
from harness.skills import definition
from harness.skills.definition import (
    InvalidSkill,
    list_skills,
    load_skill,
    template_path,
    validate_skill_name,
)
from tests.conftest import REPO_ROOT, make_symlink

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "skills"
EFFECTS = ("none",)
# Fixed vector: the hash of tests/fixtures/skills/demo-echo as committed (D4).
DEMO_ECHO_SHA256 = "48d04f52a54c3f26b55ee3629b768cd29c0cfc0bb2142b5531a941adf08110f4"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A disposable copy of the synthetic skills, safe to break."""
    target = tmp_path / "skills"
    shutil.copytree(FIXTURES, target)
    return target


def _reasons(root: Path, name: str) -> str:
    with pytest.raises(InvalidSkill) as caught:
        load_skill(root, name, EFFECTS)
    return "; ".join(caught.value.reasons)


def _workflow(root: Path, name: str) -> dict:
    return json.loads((root / name / "workflow.json").read_text(encoding="utf-8"))


def _save_workflow(root: Path, name: str, data: dict) -> None:
    (root / name / "workflow.json").write_text(json.dumps(data), encoding="utf-8")


# -- 2.1 names and declared paths (pure) ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["../otro", "..\\otro", "a/b", "C:\\x", "\\\\servidor\\r", "CON", "con", "nul", "Demo",
     "-x", "x" * 65, "", "demo.echo", "demo echo"],
)
def test_invalid_skill_names(raw):
    with pytest.raises(InvalidInput, match="invalid skill name"):
        validate_skill_name(raw)


def test_valid_skill_name():
    assert validate_skill_name("demo-echo") == "demo-echo"
    assert validate_skill_name("x" * 64) == "x" * 64


@pytest.mark.parametrize(
    "raw",
    ["templates/../../secreto.md", "/abs.md", "templates\\x.md", "C:/templates/x.md",
     "templates/sub/x.md", "references/x.md", "templates/x.py", "templates/CON.md",
     "templates/.oculto.md", "draft.md"],
)
def test_invalid_template_paths(raw):
    assert template_path(raw) is None


def test_valid_template_path():
    assert template_path("templates/draft.md") == "templates/draft.md"


def test_traversal_in_a_template_path_invalidates_without_reading(root):
    data = _workflow(root, "demo-echo")
    data["steps"][0]["template"] = "templates/../../secreto.md"
    _save_workflow(root, "demo-echo", data)
    (root.parent / "secreto.md").write_text("CANARIO-FUERA", encoding="utf-8")
    assert "template must be templates/<name>.md" in _reasons(root, "demo-echo")


@pytest.mark.parametrize("args", [("skill", "show", "../otro"), ("skill", "show", "..\\otro")])
def test_traversal_name_in_the_cli(data_dir, args):
    from tests.conftest import run_main

    result = run_main(data_dir, *args, HARNESS_SKILLS_DIR=str(FIXTURES))
    assert result.returncode != 0 and "invalid skill name" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (data_dir / "harness.sqlite3").exists()


# -- 2.2 the folder ------------------------------------------------------------------------------


def test_valid_skill_listed(root):
    listing = {item.name: item for item in list_skills(root, EFFECTS)}
    assert listing["demo-echo"].valid and listing["demo-echo"].version == "1.0.0"
    assert listing["demo-json"].valid


@pytest.mark.parametrize(
    "name, reason",
    [
        ("bad-name", "frontmatter name does not match the folder name"),
        ("bad-noworkflow", "missing workflow.json"),
        ("bad-script", "unexpected file: scripts"),
        ("bad-helper", "unexpected file: templates/helper.py"),
        ("bad-tool-kind", "unknown step kind 'tool'"),
    ],
)
def test_invalid_fixtures(root, name, reason):
    assert reason in _reasons(root, name)
    listing = {item.name: item for item in list_skills(root, EFFECTS)}
    assert not listing[name].valid and any(reason in r for r in listing[name].reasons)


def test_hidden_file_is_ignored_and_does_not_change_the_hash(root):
    before = load_skill(root, "demo-echo", EFFECTS).sha256
    (root / "demo-echo" / ".DS_Store").write_bytes(b"\x00\x01binario")
    (root / "demo-echo" / ".git").mkdir()
    (root / "demo-echo" / ".git" / "x.sh").write_text("echo", encoding="utf-8")
    assert load_skill(root, "demo-echo", EFFECTS).sha256 == before


def test_template_linked_outside_the_root(root, tmp_path, capsys):
    outside = tmp_path / "fuera.md"
    outside.write_text("CANARIO-ENLACE-FUERA {{inputs.text}}", encoding="utf-8")
    template = root / "demo-echo" / "templates" / "review.md"
    make_symlink(template, outside)
    reasons = _reasons(root, "demo-echo")
    assert "link: templates/review.md" in reasons
    listing = {item.name: item for item in list_skills(root, EFFECTS)}
    assert not listing["demo-echo"].valid
    shown = repr(listing) + reasons + "".join(capsys.readouterr())
    assert "CANARIO-ENLACE-FUERA" not in shown


def test_linked_skill_folder(root, tmp_path):
    shutil.copytree(root / "demo-echo", tmp_path / "otra")
    make_symlink(root / "enlazado", tmp_path / "otra")
    assert "link" in _reasons(root, "enlazado")


def test_hard_link_is_refused(root, tmp_path):
    extra = tmp_path / "duro.md"
    extra.write_text("texto", encoding="utf-8")
    (root / "demo-echo" / "references").mkdir()
    try:
        os.link(extra, root / "demo-echo" / "references" / "duro.md")
    except OSError as exc:
        pytest.skip(f"cannot create hard links here: {exc}")
    assert "hard link: references/duro.md" in _reasons(root, "demo-echo")


def test_missing_skill(root):
    with pytest.raises(InvalidInput, match="does not exist"):
        load_skill(root, "no-existe", EFFECTS)


# -- 2.3 the workflow ----------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["tool", "shell", "script"])
def test_unknown_step_kind(root, kind):
    data = _workflow(root, "demo-echo")
    data["steps"][0]["kind"] = kind
    _save_workflow(root, "demo-echo", data)
    assert f"unknown step kind '{kind}'" in _reasons(root, "demo-echo")


def test_unknown_field(root):
    data = _workflow(root, "demo-echo")
    data["steps"][0]["command"] = "rm -rf /"
    _save_workflow(root, "demo-echo", data)
    reasons = _reasons(root, "demo-echo")
    assert "unknown field: steps.0.llm.command" in reasons and "rm -rf" not in reasons


def test_unknown_top_level_field(root):
    data = _workflow(root, "demo-echo")
    data["hooks"] = {}
    _save_workflow(root, "demo-echo", data)
    assert "unknown field: hooks" in _reasons(root, "demo-echo")


def test_duplicate_key_in_the_json(root):
    text = (root / "demo-echo" / "workflow.json").read_text(encoding="utf-8")
    text = text.replace('"output": "check"', '"steps": [], "output": "check"')
    (root / "demo-echo" / "workflow.json").write_text(text, encoding="utf-8")
    assert "duplicate key 'steps'" in _reasons(root, "demo-echo")


@pytest.mark.parametrize(
    "text, reason",
    [
        ('{"schema": 1, "version": NaN}', "NaN is not allowed"),
        ("[" * 5000 + "]" * 5000, "nested deeper than 32"),
        ("no es json", "not valid JSON"),
    ],
)
def test_broken_json(root, text, reason):
    (root / "demo-echo" / "workflow.json").write_text(text, encoding="utf-8")
    assert reason in _reasons(root, "demo-echo")


def test_reference_to_a_later_step(root):
    template = root / "demo-echo" / "templates" / "draft.md"
    template.write_text("tarea\n{{steps.check.output}}\n", encoding="utf-8")
    assert "reference to a step that is not earlier: 'check'" in _reasons(root, "demo-echo")


@pytest.mark.parametrize(
    "expression",
    ["{{ inputs.doc.upper() }}", "{{ 1 + 1 }}", "{{inputs.text}", "{{ {{inputs.text}} }}",
     "{{ inputs.__class__ }}", "{{steps.x.fields}}"],
)
def test_expression_in_a_template(root, expression):
    template = root / "demo-echo" / "templates" / "draft.md"
    template.write_text(f"tarea\n{expression}\n", encoding="utf-8")
    _reasons(root, "demo-echo")


def test_undeclared_input_and_field(root):
    (root / "demo-echo" / "templates" / "draft.md").write_text("{{inputs.otro}}", encoding="utf-8")
    assert "undeclared input 'otro'" in _reasons(root, "demo-echo")
    summary = root / "demo-json" / "templates" / "summary.md"
    summary.write_text("{{steps.fields.fields.nada}}", encoding="utf-8")
    assert "undeclared field: 'nada'" in _reasons(root, "demo-json")


def test_unknown_effect(root):
    data = _workflow(root, "demo-echo")
    data["steps"][2]["effect"] = "write_file"
    _save_workflow(root, "demo-echo", data)
    assert "unknown effect 'write_file'" in _reasons(root, "demo-echo")


def test_repeated_step_id(root):
    data = _workflow(root, "demo-echo")
    data["steps"][1]["id"] = "draft"
    _save_workflow(root, "demo-echo", data)
    assert "repeated step id 'draft'" in _reasons(root, "demo-echo")


# -- 2.4 hash ------------------------------------------------------------------------------------


def test_fixed_hash_vector():
    assert load_skill(FIXTURES, "demo-echo", EFFECTS).sha256 == DEMO_ECHO_SHA256


def test_hash_follows_the_documented_formula():
    import hashlib

    digest = hashlib.sha256(b"ai-harness/skill/v1\n")
    folder = FIXTURES / "demo-echo"
    for relative in sorted(["SKILL.md", "templates/draft.md", "workflow.json"]):
        content = (folder / relative).read_bytes().replace(b"\r\n", b"\n")
        digest.update(f"{relative}\0{hashlib.sha256(content).hexdigest()}\n".encode())
    assert digest.hexdigest() == DEMO_ECHO_SHA256


def test_changing_a_template_changes_the_hash(root):
    before = load_skill(root, "demo-echo", EFFECTS)
    template = root / "demo-echo" / "templates" / "draft.md"
    template.write_text(template.read_text(encoding="utf-8") + "x", encoding="utf-8")
    after = load_skill(root, "demo-echo", EFFECTS)
    assert after.sha256 != before.sha256 and after.version == before.version


def _rewrite(folder: Path, change) -> None:
    """Apply `change` to the text of every file, given with LF line ends whatever the checkout
    left on disk (revised on 2026-11-26: on Windows `core.autocrlf` checks the fixtures out with
    CRLF, and a change written for LF text turned them into CR CR LF or CR CR)."""
    for path in folder.rglob("*"):
        if path.is_file():
            text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
            path.write_bytes(change(text).encode("utf-8"))


def _check_out(folder: Path, checkout: str) -> None:
    """The copy as git leaves it: `lf`, or `autocrlf` as a Windows checkout writes it."""
    if checkout == "autocrlf":
        _rewrite(folder, lambda text: text.replace("\n", "\r\n"))


CHECKOUTS = pytest.mark.parametrize("checkout", ["lf", "autocrlf"])


@CHECKOUTS
def test_crlf_line_ends_and_bom_give_the_same_hash(root, checkout):
    folder = root / "demo-echo"
    _check_out(folder, checkout)
    _rewrite(folder, lambda text: "\ufeff" + text.replace("\n", "\r\n"))
    assert b"\r\r" not in (folder / "SKILL.md").read_bytes()
    assert b"\r\n" in (folder / "SKILL.md").read_bytes()
    assert load_skill(root, "demo-echo", EFFECTS).sha256 == DEMO_ECHO_SHA256


@CHECKOUTS
def test_a_lone_carriage_return_is_a_line_end(root, checkout):
    """D4 (revised on 2026-11-25): `\\r\\n` first, then any `\\r` left, become `\\n`. A file
    saved with old Mac line ends gives the same hash; CR CR LF is two line ends."""
    folder = root / "demo-echo"
    _check_out(folder, checkout)
    _rewrite(folder, lambda text: text.replace("\n", "\r"))
    assert b"\n" not in (folder / "SKILL.md").read_bytes()
    assert load_skill(root, "demo-echo", EFFECTS).sha256 == DEMO_ECHO_SHA256
    template = folder / "templates" / "draft.md"
    lines = template.read_bytes().decode("utf-8").split("\r")
    template.write_bytes("\r\r\n".join(lines).encode("utf-8"))
    loaded = load_skill(root, "demo-echo", EFFECTS)
    assert loaded.sha256 != DEMO_ECHO_SHA256
    assert loaded.templates["templates/draft.md"] == "\n\n".join(lines)


# -- 2.5 limits on disk --------------------------------------------------------------------------


def _llm(i: int) -> dict:
    return {"id": f"s{i}", "kind": "llm", "template": "templates/draft.md"}


def test_too_many_steps(root):
    data = _workflow(root, "demo-echo")
    data["steps"] = [_llm(i) for i in range(13)]
    data["output"] = "s0"
    _save_workflow(root, "demo-echo", data)
    assert "too many steps" in _reasons(root, "demo-echo")


def test_twelve_steps_are_fine(root):
    data = _workflow(root, "demo-echo")
    data["steps"] = [_llm(i) for i in range(12)]
    data["output"] = "s0"
    _save_workflow(root, "demo-echo", data)
    assert len(load_skill(root, "demo-echo", EFFECTS).workflow.steps) == 12


def test_template_too_large_is_decided_without_reading_it(root, monkeypatch):
    big = root / "demo-echo" / "templates" / "big.md"
    big.write_bytes(b"x" * 65_537)
    read = []
    original = definition.read_vault_file

    def spy(file):
        read.append(file.relative)
        return original(file)

    monkeypatch.setattr(definition, "read_vault_file", spy)
    assert "file larger than 65536 bytes: templates/big.md" in _reasons(root, "demo-echo")
    assert "templates/big.md" not in read


def test_too_many_files(root):
    references = root / "demo-echo" / "references"
    references.mkdir()
    for i in range(30):
        (references / f"r{i}.md").write_text("x", encoding="utf-8")
    assert "too many files" in _reasons(root, "demo-echo")


def test_too_large_in_total(root):
    references = root / "demo-echo" / "references"
    references.mkdir()
    for i in range(9):
        (references / f"r{i}.md").write_bytes(b"x" * 60 * 1024)
    assert "skill larger than 524288 bytes" in _reasons(root, "demo-echo")


def test_too_many_inputs(root):
    data = _workflow(root, "demo-echo")
    data["inputs"] = {f"i{i}": {} for i in range(9)}
    _save_workflow(root, "demo-echo", data)
    assert "too many inputs" in _reasons(root, "demo-echo")


@pytest.mark.parametrize("timeout", [0, 601, "30"])
def test_step_timeout_out_of_range(root, timeout):
    data = _workflow(root, "demo-echo")
    data["steps"][0]["timeout_s"] = timeout
    _save_workflow(root, "demo-echo", data)
    assert "invalid steps.0.llm.timeout_s" in _reasons(root, "demo-echo")
