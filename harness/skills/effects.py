"""Effects: what an approved step does (skill-engine D13).

The registry is a literal dictionary in code: a `workflow.json` only names a key, it can never
point to a module or a path. Tests inject their own effects through the engine's constructor.
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from harness.core.errors import HarnessError
from harness.skills.approvals import Proposal

Reconciled = Literal["applied", "absent", "conflict"]


class EffectRefused(HarnessError):
    """A controlled refusal of `prepare` or `apply` (architecture-skills-llm D11).

    From `prepare`: the step and the run fail with `code` before any approval is asked. From
    `apply`: only before any side effect (revised 2026-11-25, independent review); the step
    fails with `code` and the approval, already consumed, is not usable again. From
    `reconcile`: the step stays `uncertain` and `resume` stops with this message.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class EffectBusy(HarnessError):
    """The effect's exclusive section is taken: nothing was consumed or applied."""


class EffectUncertain(HarnessError):
    """`apply` may have had its side effect and cannot tell. The engine treats it, and any
    exception from `apply` other than `EffectRefused`, as `uncertain`: `reconcile` decides."""


@dataclass(frozen=True)
class Prepared:
    """What an approval would let the effect do. `effect_ref` locates it without content."""

    content: str  # the text to approve, before normalisation
    target: str | None
    effect_ref: str | None
    redactions: int = 0  # credentials masked in `content`, shown in the approval header


@dataclass(frozen=True)
class EffectContext:
    """Where an effect runs. Everything comes from SQLite and is the same on every resume."""

    session_id: str
    run_id: str
    step: str
    skill_name: str
    project_slug: str | None = None
    run_created_at: str = ""  # skill_runs.created_at, UTC ISO
    skill_version: str = ""
    skill_sha256: str = ""
    inputs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)  # name -> sha256, bytes
    memory_notes: tuple[tuple[str, str], ...] = ()  # (path, sha256) from request_context


class Effect(Protocol):
    """`prepare` runs once per attempt to apply; `apply` receives only the verified proposal.

    `apply` gets the `Proposal` whose hash was approved and consumed: its `content` and `target`
    are exactly the ones shown and hashed, never a second `prepare` (review 8.3, 2026-11-24).
    `reconcile` answers, after an interruption, whether the content with that SHA-256 is already
    in place (`applied`), not there at all (`absent`) or something else is there (`conflict`);
    it may raise `EffectRefused` to say why it cannot answer yet (the step stays `uncertain`).
    `apply` raises `EffectRefused` only before any side effect; any other exception means
    "may have been applied" and leaves the step `uncertain` (2026-11-25, independent review).
    """

    scope: str

    def prepare(self, context: EffectContext, validated: str) -> Prepared: ...

    def exclusive(self, context: EffectContext) -> AbstractContextManager[None]:
        """Held from before the approval is consumed until `apply` returns; may raise
        `EffectBusy`, in which case nothing is consumed."""
        ...

    def apply(self, context: EffectContext, proposal: Proposal) -> None: ...

    def reconcile(
        self, context: EffectContext, effect_ref: str | None, content_sha256: str
    ) -> Reconciled: ...


class NoEffect:
    """Approves the validated text itself; consuming the approval lets the run go on."""

    scope = "none"

    def prepare(self, context: EffectContext, validated: str) -> Prepared:
        return Prepared(content=validated, target=None, effect_ref=None)

    def exclusive(self, context: EffectContext) -> AbstractContextManager[None]:
        return contextlib.nullcontext()

    def apply(self, context: EffectContext, proposal: Proposal) -> None:
        return None

    def reconcile(
        self, context: EffectContext, effect_ref: str | None, content_sha256: str
    ) -> Reconciled:
        # `applied` is right here only because `apply` changes nothing outside the run: an
        # interrupted step of this effect has nothing that could be applied twice. An effect with
        # a side effect must look at its target and answer `absent` or `conflict` when unsure.
        return "applied"


def default_effects(data_dir: Path | None = None) -> Mapping[str, Effect]:
    """The registry. `data_dir` is needed only by effects that run (for their lock).

    The decision effect is imported here, not at the top of the module: the CLI imports this
    module for every command, and a `memory …` command must never load the vault writer
    (architecture-skills-llm D9, checked by tests/security/test_memory_no_writes.py).
    """
    from harness.skills.decision_effect import DecisionEffect

    return {"none": NoEffect(), DecisionEffect.scope: DecisionEffect(data_dir)}
