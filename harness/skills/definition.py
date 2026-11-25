"""What a skill is on disk and when it is accepted (skill-engine D2-D5, D14; SEC-14).

Deny by default: a skill folder may hold `SKILL.md`, `workflow.json` and Markdown files under
`templates/` and `references/`, nothing else. A link of any kind, a hard link, an unknown file,
an unknown field, an unknown step kind or effect, or a reference that does not resolve makes
the whole skill invalid. No code path loads or runs anything a skill contains: templates are
text, the workflow is data.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from harness.core.errors import HarnessError, InvalidInput
from harness.core.strict_json import loads_strict
from harness.memory.notes import parse_frontmatter
from harness.memory.paths import SkippedRead, VaultFile, is_safe_name, read_vault_file
from harness.text.safe_text import safe_line, terminal_safe

SKILL_FILE = "SKILL.md"
WORKFLOW_FILE = "workflow.json"
CONTENT_DIRS = ("templates", "references")
MAX_FILES = 32
MAX_FILE_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 512 * 1024
MAX_STEPS = 12
MAX_INPUTS = 8
MAX_DESCRIPTION_CHARS = 300
STEP_TIMEOUT_MIN_S = 1
STEP_TIMEOUT_MAX_S = 600
VALIDATE_MAX_BYTES = 128 * 1024
STEP_KINDS = ("llm", "validate", "approval")
HASH_DOMAIN = b"ai-harness/skill/v1\n"

_SKILL_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_REF_NAME = r"[a-z][a-z0-9_-]{0,31}"
_REF_NAME_RE = re.compile(_REF_NAME)
_CONTENT_FILE_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\.md")
_VERSION_RE = r"[0-9A-Za-z.+-]{1,32}"
# The whole grammar of a reference: what is between `{{` and `}}`.
_REFERENCE_RE = re.compile(
    rf"\s*(?:inputs\.(?P<input>{_REF_NAME})"
    rf"|steps\.(?P<step>{_REF_NAME})\.(?:output|fields\.(?P<field>{_REF_NAME})))\s*"
)


class InvalidSkill(HarnessError):
    def __init__(self, name: str, reasons: list[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__(f"skill {name!r} is invalid: " + "; ".join(self.reasons))


# -- the workflow schema (closed: extra fields are an error) -------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


StepId = Annotated[str, Field(pattern=f"^{_REF_NAME}$")]


class InputSpec(_Model):
    description: str = Field(default="", max_length=MAX_DESCRIPTION_CHARS)
    required: bool = True


class LlmStep(_Model):
    id: StepId
    kind: Literal["llm"]
    template: str = Field(max_length=200)
    memory: Literal["none", "project"] = "none"
    timeout_s: int | None = Field(default=None, ge=STEP_TIMEOUT_MIN_S, le=STEP_TIMEOUT_MAX_S)


class FieldSpec(_Model):
    type: Literal["string", "integer", "boolean", "string_list"]
    required: bool = True
    min_length: int | None = Field(default=None, ge=1, le=VALIDATE_MAX_BYTES)
    max_length: int | None = Field(default=None, ge=1, le=VALIDATE_MAX_BYTES)
    single_line: bool = False
    enum: list[str] | None = Field(default=None, min_length=1, max_length=50)
    format: Literal["slug", "date"] | None = None
    min: int | None = None
    max: int | None = None
    max_items: int | None = Field(default=None, ge=1, le=100)


class ValidateStep(_Model):
    id: StepId
    kind: Literal["validate"]
    of: StepId
    format: Literal["text", "markdown", "json"]
    min_bytes: int = Field(default=0, ge=0, le=VALIDATE_MAX_BYTES)
    max_bytes: int = Field(default=VALIDATE_MAX_BYTES, ge=1, le=VALIDATE_MAX_BYTES)
    required_headings: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        default_factory=list, max_length=20
    )
    fields: dict[Annotated[str, Field(pattern=f"^{_REF_NAME}$")], FieldSpec] = Field(
        default_factory=dict, max_length=30
    )


class ApprovalStep(_Model):
    id: StepId
    kind: Literal["approval"]
    of: StepId
    effect: str = Field(max_length=64)


Step = Annotated[LlmStep | ValidateStep | ApprovalStep, Field(discriminator="kind")]


class Workflow(_Model):
    schema_version: Literal[1] = Field(alias="schema")
    version: str = Field(pattern=f"^{_VERSION_RE}$")
    inputs: dict[Annotated[str, Field(pattern=f"^{_REF_NAME}$")], InputSpec] = Field(
        default_factory=dict
    )
    steps: list[Step] = Field(min_length=1)
    output: StepId


# -- the loaded skill ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    workflow: Workflow
    sha256: str
    templates: dict[str, str] = field(default_factory=dict)  # relative path -> normalised text

    @property
    def version(self) -> str:
        return self.workflow.version

    def step(self, step_id: str) -> LlmStep | ValidateStep | ApprovalStep:
        return next(step for step in self.workflow.steps if step.id == step_id)

    def has_approval(self) -> bool:
        return any(step.kind == "approval" for step in self.workflow.steps)


@dataclass(frozen=True)
class SkillListing:
    name: str  # terminal-safe
    valid: bool
    version: str
    description: str
    reasons: tuple[str, ...]


def validate_skill_name(raw: str) -> str:
    """Checked before the disk is touched, with the same answer on every platform."""
    if not _SKILL_NAME_RE.fullmatch(raw) or not is_safe_name(raw):
        raise InvalidInput(
            f"invalid skill name {terminal_safe(raw)!r}: use lowercase letters, digits and "
            "hyphens, at most 64 characters"
        )
    return raw


def skills_root(raw: Path) -> Path | None:
    """The real skills root, or None if it does not exist (no skills)."""
    try:
        root = raw.resolve(strict=True)
    except OSError:
        return None
    return root if root.is_dir() else None


def list_skills(root: Path | None, effects: Collection[str]) -> list[SkillListing]:
    if root is None:
        return []
    listings = []
    for name in sorted(os.listdir(root)):
        entry = root / name
        if name.startswith(".") or not (entry.is_dir() or entry.is_symlink()):
            continue
        try:
            skill = load_skill(root, name, effects)
        except InvalidSkill as exc:
            listings.append(SkillListing(terminal_safe(name), False, "-", "", exc.reasons))
        except InvalidInput as exc:
            listings.append(SkillListing(terminal_safe(name), False, "-", "", (str(exc),)))
        else:
            listings.append(
                SkillListing(skill.name, True, skill.version, skill.description, ())
            )
    return listings


def load_skill(root: Path | None, name: str, effects: Collection[str]) -> Skill:
    """Load and validate one skill. Raises InvalidSkill with every reason found."""
    validate_skill_name(name)
    if root is None or name not in os.listdir(root):
        raise InvalidInput(f"skill {name!r} does not exist")
    folder = root / name
    if folder.is_symlink() or folder.is_junction():
        raise InvalidSkill(name, ["link: the skill folder is a link"])
    if not folder.is_dir():
        raise InvalidInput(f"skill {name!r} does not exist")

    files, reasons = _collect(folder)
    if reasons:
        raise InvalidSkill(name, reasons)
    texts: dict[str, str] = {}
    for relative, info in files:
        try:
            texts[relative] = _read(folder, relative, info)
        except _Problem as problem:
            reasons.append(str(problem))
    if reasons:
        raise InvalidSkill(name, reasons)
    for required in (SKILL_FILE, WORKFLOW_FILE):
        if required not in texts:
            reasons.append(f"missing {required}")
    if reasons:
        raise InvalidSkill(name, reasons)

    description, body = _frontmatter(name, texts[SKILL_FILE], reasons)
    workflow = _workflow(texts[WORKFLOW_FILE], reasons)
    if workflow is not None:
        _check_workflow(workflow, texts, effects, reasons)
    if reasons or workflow is None:
        raise InvalidSkill(name, reasons)
    templates = {path: text for path, text in texts.items() if path.startswith("templates/")}
    return Skill(name, description, body, workflow, skill_hash(texts), templates)


def skill_hash(texts: dict[str, str]) -> str:
    """SHA-256 of the sorted list of files and their normalised content (D4)."""
    digest = hashlib.sha256(HASH_DOMAIN)
    for relative in sorted(texts):
        content = hashlib.sha256(texts[relative].encode("utf-8")).hexdigest()
        digest.update(f"{relative}\0{content}\n".encode())
    return digest.hexdigest()


# -- the folder ----------------------------------------------------------------------------------


class _Problem(Exception):
    pass


def _collect(folder: Path) -> tuple[list[tuple[str, os.stat_result]], list[str]]:
    """Every accepted file with its lstat, or the reasons the folder is refused."""
    files: list[tuple[str, os.stat_result]] = []
    reasons: list[str] = []
    total = 0

    def refuse(relative: str, reason: str) -> None:
        reasons.append(f"{reason}: {terminal_safe(relative)}")

    def unreadable(error: OSError) -> None:
        reasons.append("unreadable folder")

    for dirpath, dirnames, filenames in os.walk(folder, onerror=unreadable, followlinks=False):
        current = Path(dirpath)
        depth = len(current.relative_to(folder).parts)
        keep = []
        for name in sorted(dirnames):
            entry = current / name
            relative = entry.relative_to(folder).as_posix()
            if entry.is_symlink() or entry.is_junction():
                refuse(relative, "link")
            elif name.startswith("."):
                continue  # hidden: never read, never hashed
            elif depth == 0 and name in CONTENT_DIRS:
                keep.append(name)
            else:
                refuse(relative, "unexpected file")
        dirnames[:] = keep
        for name in sorted(filenames):
            entry = current / name
            relative = entry.relative_to(folder).as_posix()
            if entry.is_symlink() or entry.is_junction():
                refuse(relative, "link")
                continue
            if name.startswith("."):
                continue
            allowed = (
                name in (SKILL_FILE, WORKFLOW_FILE)
                if depth == 0
                else bool(_CONTENT_FILE_RE.fullmatch(name)) and is_safe_name(name)
            )
            if not allowed:
                refuse(relative, "unexpected file")
                continue
            try:
                info = entry.lstat()
            except OSError:
                refuse(relative, "unreadable")
                continue
            if not stat.S_ISREG(info.st_mode):
                refuse(relative, "not a regular file")
            elif info.st_nlink > 1:
                refuse(relative, "hard link")
            elif info.st_size > MAX_FILE_BYTES:
                refuse(relative, f"file larger than {MAX_FILE_BYTES} bytes")
            else:
                total += info.st_size
                files.append((relative, info))
    if len(files) > MAX_FILES:
        reasons.append(f"too many files (more than {MAX_FILES})")
    if total > MAX_TOTAL_BYTES:
        reasons.append(f"skill larger than {MAX_TOTAL_BYTES} bytes")
    return files, reasons


def _read(folder: Path, relative: str, info: os.stat_result) -> str:
    walked = VaultFile(folder / relative, relative, info.st_size, info.st_dev, info.st_ino)
    try:
        raw = read_vault_file(walked)  # same file the walk saw, checked on the open descriptor
    except SkippedRead as skipped:
        raise _Problem(f"{skipped.reason}: {terminal_safe(relative)}") from None
    if len(raw) > MAX_FILE_BYTES:
        raise _Problem(f"file larger than {MAX_FILE_BYTES} bytes: {terminal_safe(relative)}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _Problem(f"not UTF-8: {terminal_safe(relative)}") from None
    return text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def _frontmatter(name: str, text: str, reasons: list[str]) -> tuple[str, str]:
    front, body = parse_frontmatter(text)
    if not front.present or not front.syntax_ok:
        reasons.append("SKILL.md has no valid frontmatter")
        return "", body
    fields = front.fields
    unknown = sorted(set(fields) - {"name", "description"})
    if unknown:
        reasons.append("unknown frontmatter field: " + ", ".join(map(terminal_safe, unknown)))
    declared = fields.get("name")
    if declared != name:
        reasons.append("frontmatter name does not match the folder name")
    description = fields.get("description")
    if not isinstance(description, str) or not description.strip():
        reasons.append("frontmatter description is missing")
        return "", body
    if len(description) > MAX_DESCRIPTION_CHARS:
        reasons.append(f"description longer than {MAX_DESCRIPTION_CHARS} characters")
    return safe_line(description).text, body


def _workflow(text: str, reasons: list[str]) -> Workflow | None:
    try:
        data = loads_strict(text, max_bytes=MAX_FILE_BYTES, what=WORKFLOW_FILE)
    except InvalidInput as exc:
        reasons.append(str(exc))
        return None
    if not isinstance(data, dict):
        reasons.append("workflow.json must be an object")
        return None
    steps = data.get("steps")
    if isinstance(steps, list):
        if len(steps) > MAX_STEPS:
            reasons.append(f"too many steps (more than {MAX_STEPS})")
            return None
        for position, step in enumerate(steps):
            kind = step.get("kind") if isinstance(step, dict) else None
            if kind not in STEP_KINDS:
                shown = terminal_safe(kind) if isinstance(kind, str) else "?"
                reasons.append(f"unknown step kind {shown!r} at step {position}")
        if reasons:
            return None
    inputs = data.get("inputs")
    if isinstance(inputs, dict) and len(inputs) > MAX_INPUTS:
        reasons.append(f"too many inputs (more than {MAX_INPUTS})")
        return None
    try:
        return Workflow.model_validate(data)
    except ValidationError as exc:
        reasons.extend(_schema_reasons(exc))
        return None


def _schema_reasons(exc: ValidationError) -> list[str]:
    """Where and what, never the offending value (it comes from the file)."""
    reasons = []
    for error in exc.errors(include_input=False, include_url=False):
        where = ".".join(terminal_safe(str(part)) for part in error["loc"])
        if error["type"] == "extra_forbidden":
            reasons.append(f"unknown field: {where}")
        else:
            reasons.append(f"invalid {where}: {error['type']}")
    return reasons


def _check_workflow(
    workflow: Workflow, texts: dict[str, str], effects: Collection[str], reasons: list[str]
) -> None:
    seen: dict[str, LlmStep | ValidateStep | ApprovalStep] = {}
    for step in workflow.steps:
        if step.id in seen:
            reasons.append(f"repeated step id {step.id!r}")
            continue
        if isinstance(step, LlmStep):
            path = template_path(step.template)
            if path is None:
                reasons.append(f"step {step.id!r}: template must be templates/<name>.md")
            elif path not in texts:
                reasons.append(f"step {step.id!r}: template {path!r} does not exist")
            else:
                for problem in references_problems(texts[path], workflow, seen):
                    reasons.append(f"step {step.id!r}: {problem}")
        else:
            target = seen.get(step.of)
            if target is None:
                reasons.append(f"step {step.id!r}: 'of' must name an earlier step")
            elif isinstance(step, ValidateStep) and isinstance(target, ApprovalStep):
                reasons.append(f"step {step.id!r}: cannot validate an approval")
            elif isinstance(step, ApprovalStep) and not isinstance(target, ValidateStep):
                reasons.append(f"step {step.id!r}: an approval must be of a validate step")
        if isinstance(step, ValidateStep):
            if step.fields and step.format != "json":
                reasons.append(f"step {step.id!r}: fields need format json")
            if step.format == "json" and not step.fields:
                reasons.append(f"step {step.id!r}: format json needs fields")
            if step.required_headings and step.format != "markdown":
                reasons.append(f"step {step.id!r}: required_headings need format markdown")
            if step.min_bytes > step.max_bytes:
                reasons.append(f"step {step.id!r}: min_bytes is larger than max_bytes")
        if isinstance(step, ApprovalStep) and step.effect not in effects:
            reasons.append(f"step {step.id!r}: unknown effect {terminal_safe(step.effect)!r}")
        seen[step.id] = step
    if workflow.output not in seen:
        reasons.append("output must name a step")


def template_path(raw: str) -> str | None:
    """`templates/<name>.md` and nothing else: relative, POSIX, no `..`, one level."""
    if "\\" in raw or ":" in raw:
        return None
    path = PurePosixPath(raw)
    if path.is_absolute() or len(path.parts) != 2 or path.parts[0] != "templates":
        return None
    name = path.parts[1]
    if not _CONTENT_FILE_RE.fullmatch(name) or not is_safe_name(name):
        return None
    return path.as_posix()


@dataclass(frozen=True)
class Reference:
    start: int
    end: int
    input: str | None
    step: str | None
    field: str | None


def find_references(text: str) -> tuple[list[Reference], list[str]]:
    """Every `{{...}}` of a template, in one linear pass, and the problems found.

    A `{{` without its `}}`, a `{{` inside another, or anything that is not the closed grammar
    is a problem. Nothing is evaluated.
    """
    found: list[Reference] = []
    problems: list[str] = []
    pos = 0
    while (start := text.find("{{", pos)) >= 0:
        end = text.find("}}", start + 2)
        if end < 0:
            problems.append("a '{{' is never closed")
            break
        inner = text[start + 2 : end]
        if "{{" in inner:
            problems.append("nested '{{'")
            break
        match = _REFERENCE_RE.fullmatch(inner)
        if match is None:
            problems.append("a '{{ }}' that is not a reference: " + terminal_safe(inner[:40]))
        else:
            found.append(
                Reference(start, end + 2, match["input"], match["step"], match["field"])
            )
        pos = end + 2
    return found, problems


def references_problems(
    text: str, workflow: Workflow, earlier: dict[str, Any]
) -> list[str]:
    references, problems = find_references(text)
    for reference in references:
        if reference.input is not None:
            if reference.input not in workflow.inputs:
                problems.append(f"undeclared input {reference.input!r}")
            continue
        step = earlier.get(reference.step)
        if step is None:
            problems.append(f"reference to a step that is not earlier: {reference.step!r}")
        elif isinstance(step, ApprovalStep):
            problems.append(f"reference to an approval step: {reference.step!r}")
        elif reference.field is not None and not (
            isinstance(step, ValidateStep) and reference.field in step.fields
        ):
            problems.append(f"reference to an undeclared field: {reference.field!r}")
    return problems
