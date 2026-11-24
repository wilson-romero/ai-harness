"""The `skill` commands of the CLI (skill-engine D16)."""

from __future__ import annotations

import argparse
import os
import sys

from harness.skills.config import load_skill_settings
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

EXIT_OK = 0
EXIT_ERROR = 1


def add_skill_parser(commands: argparse._SubParsersAction) -> None:
    skill = commands.add_parser("skill", help="list, show and run declarative skills")
    sub = skill.add_subparsers(dest="skill_command", required=True)
    sub.add_parser("list", help="list the skills and whether they are valid")
    show = sub.add_parser("show", help="show a skill without running it")
    show.add_argument("name")


def run_skill_command(args: argparse.Namespace) -> int:
    if args.skill_command == "show":
        validate_skill_name(args.name)  # before the configuration and before the disk
    settings = load_skill_settings(os.environ)
    root = skills_root(settings.skills_dir)
    effects = default_effects()
    if args.skill_command == "list":
        return _list(root, effects)
    return _show(root, args.name, effects)


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
