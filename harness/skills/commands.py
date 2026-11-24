"""The `skill` commands of the CLI (skill-engine D16)."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from harness.config import Settings
from harness.core.errors import UsageError
from harness.core.service import SessionService
from harness.core.strict_json import read_text_limited
from harness.memory.config import ensure_data_dir_outside_vault, load_memory_settings
from harness.memory.context import ProjectContext, build_context
from harness.providers.registry import provider_factory
from harness.skills.config import load_skill_settings
from harness.storage.database import open_database
from harness.skills.engine import MAX_INPUT_BYTES, RunOutcome, SkillEngine, recover_runs
from harness.skills.definition import (
    InvalidSkill,
    LlmStep,
    ValidateStep,
    find_references,
    list_skills,
    load_skill,
    skills_root,
    validate_skill_name,
)
from harness.skills.effects import default_effects
from harness.memory.safe_text import safe_line, safe_text, terminal_safe

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_AWAITING_APPROVAL = 3


def add_skill_parser(commands: argparse._SubParsersAction) -> None:
    skill = commands.add_parser("skill", help="list, show and run declarative skills")
    sub = skill.add_subparsers(dest="skill_command", required=True)
    sub.add_parser("list", help="list the skills and whether they are valid")
    show = sub.add_parser("show", help="show a skill without running it")
    show.add_argument("name")
    run = sub.add_parser("run", help="run a skill in a session")
    run.add_argument("name")
    run.add_argument("--session", required=True, help="the session identifier")
    _input_arguments(run)
    status = sub.add_parser("status", help="show the state of a run, without contents")
    status.add_argument("run_id")
    status.add_argument("--output", action="store_true", help="print the final output if kept")
    resume = sub.add_parser("resume", help="continue a paused or uncertain run")
    resume.add_argument("run_id")
    _input_arguments(resume)
    resume.add_argument("--retry-step", default=None, help="ask an uncertain step again")
    cancel = sub.add_parser("cancel", help="cancel a run and revoke its approval")
    cancel.add_argument("run_id")


def _input_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--input-file", action="append", default=[], metavar="NAME=PATH")


def run_skill_command(args: argparse.Namespace) -> int:
    if args.skill_command in ("show", "run"):
        validate_skill_name(args.name)  # before the configuration and before the disk
    inputs = _read_inputs(args) if args.skill_command in ("run", "resume") else {}
    skill_settings = load_skill_settings(os.environ)
    root = skills_root(skill_settings.skills_dir)
    effects = default_effects()
    if args.skill_command == "list":
        return _list(root, effects)
    if args.skill_command == "show":
        return _show(root, args.name, effects)

    settings = Settings.from_env(os.environ)
    conn = open_database(settings.data_dir)
    try:
        sessions = SessionService(
            conn, settings.data_dir, provider_factory(settings), settings.provider,
            settings.request_timeout_s,
        )
        sessions.recover()
        recover_runs(conn, settings.data_dir)
        engine = SkillEngine(
            conn, settings.data_dir, sessions, root,
            default_timeout_s=settings.request_timeout_s,
            effects=effects,
            approval_ttl_s=skill_settings.approval_ttl_s,
            context_builder=lambda project: _context(settings.data_dir, project),
            progress=lambda message: print(message, file=sys.stderr),
        )
        if args.skill_command == "run":
            return _report(asyncio.run(engine.run(args.name, args.session, inputs)))
        if args.skill_command == "resume":
            return _report(asyncio.run(engine.resume(args.run_id, inputs, args.retry_step)))
        if args.skill_command == "cancel":
            outcome = engine.cancel(args.run_id)
            print(f"{outcome.run_id}\t{outcome.status}")
            return EXIT_OK
        return _status(engine, args.run_id, args.output)
    finally:
        conn.close()


def _context(data_dir: Path, project: str) -> ProjectContext:
    memory = load_memory_settings(os.environ)
    ensure_data_dir_outside_vault(data_dir, memory.vault_root)
    return build_context(memory.vault_root, project, memory.context_max_bytes)


def _read_inputs(args: argparse.Namespace) -> dict[str, str]:
    """`--input NAME=VALUE` and `--input-file NAME=PATH`; a file is never read past the limit."""
    inputs: dict[str, str] = {}

    def add(raw: str, option: str) -> tuple[str, str]:
        name, sep, value = raw.partition("=")
        if not sep or not name:
            raise UsageError(f"{option} expects NAME=VALUE, got {terminal_safe(raw)!r}")
        if name in inputs:
            raise UsageError(f"input {terminal_safe(name)!r} was given twice")
        return name, value

    for raw in args.input:
        name, value = add(raw, "--input")
        inputs[name] = value
    for raw in args.input_file:
        name, value = add(raw, "--input-file")
        path = Path(value)
        try:
            size = path.stat().st_size
        except OSError:
            raise UsageError(f"input file for {name!r} cannot be read") from None
        if size > MAX_INPUT_BYTES:
            raise UsageError(f"input {name!r} is larger than {MAX_INPUT_BYTES} bytes")
        inputs[name] = read_text_limited(path, max_bytes=MAX_INPUT_BYTES, what=f"input {name!r}")
    return inputs


def printable(text: str) -> str:
    """Model- or skill-derived text for the terminal (review 8.7, 2026-11-24).

    The same cleaning and redaction as every vault text (`safe_text`): no control or format
    character (escape sequences, bidirectional controls, zero-width characters) reaches the
    terminal, whatever step the skill names as its output.
    """
    return safe_text(text).text


def _report(outcome: RunOutcome) -> int:
    if outcome.message:
        print(f"{outcome.run_id}: {safe_line(outcome.message).text}", file=sys.stderr)
    if outcome.status == "completed":
        print(printable(outcome.output) if outcome.output is not None else "")
        return EXIT_OK
    print(f"run {outcome.run_id} is {outcome.status}", file=sys.stderr)
    if outcome.status == "awaiting_approval":
        return EXIT_AWAITING_APPROVAL
    return EXIT_ERROR


def _status(engine: SkillEngine, run_id: str, with_output: bool) -> int:
    info = engine.status(run_id)
    run = info["run"]
    print(f"run: {run['run_id']}")
    print(f"skill: {run['skill_name']} {run['skill_version']} {run['skill_sha256']}")
    print(f"session: {run['session_id']}")
    print(f"status: {run['status']}")
    if run["error_code"]:
        print(f"error: {run['error_code']}")
    for step in info["steps"]:
        error = f" {step['error_code']}" if step["error_code"] else ""
        print(f"step: {step['step_key']} {step['kind']} attempt {step['attempt']} "
              f"{step['status']}{error}")
    approval = info["approval"]
    if approval:
        print(f"approval: {approval['step_key']} {approval['status']} "
              f"id {approval['approval_id']} expires {approval['expires_at']}")
    if with_output:
        output = engine.final_output(run_id)
        print(printable(output) if output is not None else "(output not stored)")
    return EXIT_OK


def _list(root, effects) -> int:
    listings = list_skills(root, effects)
    if not listings:
        print("No skills.")
        return EXIT_OK
    for item in listings:
        status = "valid" if item.valid else "invalid"
        detail = item.description if item.valid else "; ".join(item.reasons)
        print(f"{item.name}\t{item.version}\t{status}\t{detail}")
    return EXIT_OK


def _show(root, name: str, effects) -> int:
    try:
        skill = load_skill(root, name, effects)
    except InvalidSkill as exc:
        print(f"{name}\tinvalid", file=sys.stdout)
        for reason in exc.reasons:
            print(f"reason: {reason}")
        print(f"error: skill {name!r} is invalid", file=sys.stderr)
        return EXIT_ERROR
    print(f"name: {skill.name}")
    print(f"version: {skill.version}")
    print(f"sha256: {skill.sha256}")
    print(f"description: {skill.description}")
    for input_name, spec in skill.workflow.inputs.items():
        required = "required" if spec.required else "optional"
        print(f"input: {input_name} ({required})")
    for position, step in enumerate(skill.workflow.steps, start=1):
        line = f"step {position}: {step.id} {step.kind}"
        if isinstance(step, LlmStep):
            references, _ = find_references(skill.templates[step.template])
            refs = sorted({_ref_text(r) for r in references})
            line += f" template={step.template} memory={step.memory}"
            line += f" refs={','.join(refs) or '-'}"
        elif isinstance(step, ValidateStep):
            line += f" of={step.of} format={step.format}"
        else:
            line += f" of={step.of} effect={step.effect}"
        print(line)
    print(f"output: {skill.workflow.output}")
    return EXIT_OK


def _ref_text(reference) -> str:
    if reference.input is not None:
        return f"inputs.{reference.input}"
    if reference.field is not None:
        return f"steps.{reference.step}.fields.{reference.field}"
    return f"steps.{reference.step}.output"
